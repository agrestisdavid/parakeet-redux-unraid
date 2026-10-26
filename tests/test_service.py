import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import aiohttp
from aiohttp import web
import pytest
from wyoming.event import Event, async_write_event, async_read_event
from redux.engine import Engine, verify_model
from redux.protocol import Wyoming, info, read_event, language_ok
from redux.server import create_app, stamp


RESULT = {'text': 'Schalte das Licht ein.', 'duration': 1, 'language': None, 'words': [], 'inference_seconds': 0.1}


class FakeService:
    engine = SimpleNamespace(ready=True)
    def __init__(self): self.calls = 0
    async def transcribe(self, source, tmp):
        assert Path(source).read_bytes()
        self.calls += 1
        return RESULT


@pytest.fixture
async def http():
    service = FakeService()
    runner = web.AppRunner(create_app(service, api_key='test', max_upload=4096))
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    async with aiohttp.ClientSession(headers={'Authorization': 'Bearer test'}) as client:
        yield client, f'http://127.0.0.1:{port}', service
    await runner.cleanup()


@pytest.mark.parametrize('fmt', ['json', 'verbose_json', 'text', 'srt', 'vtt'])
async def test_http_formats(http, fmt):
    client, base, svc = http
    form = aiohttp.FormData()
    form.add_field('file', b'fixture', filename='test.wav')
    form.add_field('model', 'whisper-1')
    form.add_field('language', 'de-DE')
    form.add_field('response_format', fmt)
    async with client.post(base + '/v1/audio/transcriptions', data=form) as r:
        assert r.status == 200, await r.text()
        assert 'Schalte das Licht ein.' in await r.text()
        assert r.headers['X-Language-Mode'] == 'automatic'
    assert svc.calls == 1


@pytest.mark.parametrize('field,value', [('stream', 'true'), ('prompt', 'hallucinate'), ('language', 'xx'), ('model', 'wrong'), ('response_format', 'bad'), ('temperature','0.8')])
async def test_reject_fake_capabilities(http, field, value):
    client, base, svc = http
    form = aiohttp.FormData()
    form.add_field('file', b'a', filename='a.wav')
    form.add_field(field, value)
    async with client.post(base + '/v1/audio/transcriptions', data=form) as r:
        assert r.status == 400
    assert svc.calls == 0


async def test_http_limits_auth_health(http):
    client, base, svc = http
    async with client.get(base + '/v1/models', headers={'Authorization': 'wrong'}) as r: assert r.status == 401
    async with client.get(base + '/health') as r: assert r.status == 200
    svc.engine.ready = False
    async with client.get(base + '/health') as r: assert r.status == 503
    svc.engine.ready = True
    form = aiohttp.FormData(); form.add_field('file', b'a' * 5000, filename='a.wav')
    async with client.post(base + '/v1/audio/transcriptions', data=form) as r: assert r.status == 413


@pytest.fixture
async def tcp():
    calls = []
    async def transcribe(pcm, rate, width, channels):
        calls.append((pcm, rate, width, channels))
        return RESULT
    protocol = Wyoming(transcribe, max_seconds=1, idle_timeout=1)
    server = await asyncio.start_server(protocol.handle, '127.0.0.1', 0, limit=16384)
    port = server.sockets[0].getsockname()[1]
    yield port, calls
    server.close(); await server.wait_closed(); await protocol.close()


async def send(writer, kind, data=None, payload=None):
    await async_write_event(Event(type=kind, data=data or {}, payload=payload), writer)


async def test_discovery_and_two_utterances(tcp):
    port, calls = tcp
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    await send(writer, 'describe')
    event = await async_read_event(reader)
    assert event.type == 'info'
    assert 'de' in event.data['asr'][0]['models'][0]['languages']
    assert event.data['asr'][0]['requires_external_vad'] is True
    assert event.data['asr'][0]['supports_transcript_streaming'] is False
    fmt = {'rate': 16000, 'width': 2, 'channels': 1}
    for _ in range(2):
        await send(writer, 'transcribe', {'language': 'de'})
        await send(writer, 'audio-start', fmt)
        for _ in range(3): await send(writer, 'audio-chunk', fmt, b'\x01\x00' * 160)
        # No text should be delivered before audio-stop.
        with pytest.raises(TimeoutError): await asyncio.wait_for(async_read_event(reader), 0.03)
        await send(writer, 'audio-stop')
        event = await async_read_event(reader)
        assert event.type == 'transcript' and event.data['text'] == RESULT['text']
    assert len(calls) == 2 and len(calls[0][0]) == 960
    writer.close(); await writer.wait_closed()


@pytest.mark.parametrize('case', ['empty', 'format', 'duration', 'language', 'unknown', 'before_start', 'unaligned'])
async def test_wyoming_errors_and_reconnect(tcp, case):
    port, calls = tcp
    r,w = await asyncio.open_connection('127.0.0.1', port)
    fmt = {'rate':16000, 'width':2, 'channels':1}
    await send(w,'transcribe',{'language':'xx' if case=='language' else 'de'})
    if case != 'language':
        if case != 'before_start': await send(w,'audio-start',fmt)
        if case=='empty': await send(w,'audio-stop')
        elif case=='unknown': await send(w,'bogus')
        else:
            changed = {**fmt,'rate':8000} if case=='format' else fmt
            data = b'\x00' if case=='unaligned' else b'\0'* (32002 if case=='duration' else 320)
            await send(w,'audio-chunk',changed,data)
    event=await asyncio.wait_for(async_read_event(r),2)
    assert event.type=='error'; assert not calls
    w.close(); await w.wait_closed()
    r,w=await asyncio.open_connection('127.0.0.1',port)
    await send(w,'describe'); assert (await async_read_event(r)).type=='info'
    w.close(); await w.wait_closed()


async def test_disconnect_discards_recording(tcp):
    port,calls=tcp
    r,w=await asyncio.open_connection('127.0.0.1',port)
    await send(w,'transcribe'); await send(w,'audio-start',{'rate':16000,'width':2,'channels':1})
    w.close(); await w.wait_closed(); await asyncio.sleep(.02)
    assert not calls


@pytest.mark.parametrize('header', [b'{"type":"x","payload_length":99999999}\n', b'{"type":"x","data_length":-1}\n', b'[]\n', b'{"type":"x","data":[]}\n'])
async def test_bounded_parser(header):
    r=asyncio.StreamReader();r.feed_data(header);r.feed_eof()
    with pytest.raises(ValueError): await read_event(r)


def fake_worker(conn, model, library, threads):
    conn.send({'ready':True})
    try:
        while path:=conn.recv():
            if path=='hang': time.sleep(10)
            if path=='crash': return
            conn.send({'result':RESULT,'inference_seconds':.01})
    except EOFError: pass


async def test_engine_timeout_recovery():
    engine=Engine('unused',timeout=.1,target=fake_worker)
    await engine.start()
    assert (await engine.transcribe('ok'))['result']['text']==RESULT['text']
    with pytest.raises(TimeoutError): await engine.transcribe('hang')
    await engine.recovery
    assert engine.ready
    assert (await engine.transcribe('ok'))['result']['text']==RESULT['text']
    await engine.close();assert not engine.ready


async def test_engine_cancel_and_busy():
    engine=Engine('unused',timeout=30,target=fake_worker)
    await engine.start()
    job=asyncio.create_task(engine.transcribe('hang'));await asyncio.sleep(.05)
    with pytest.raises(BlockingIOError): await engine.transcribe('ok')
    job.cancel();await asyncio.gather(job,return_exceptions=True)
    await engine.recovery
    assert engine.ready
    await engine.close()


def test_hash_guard(tmp_path):
    p=tmp_path/'model';p.write_bytes(b'wrong')
    with pytest.raises(RuntimeError):verify_model(p)


def test_language_and_subtitles():
    assert language_ok('de-DE') and language_ok('auto') and not language_ok('ja')
    assert stamp(61.125,',')=='00:01:01,125'


def test_template():
    root=ET.parse('unraid/parakeet-redux.xml').getroot()
    assert root.tag=='Container' and root.attrib['version']=='2'
    assert root.findtext('Privileged')=='false'
    assert root.findtext('Repository').startswith('ghcr.io/agrestisdavid/')
    ports=[c.attrib['Default'] for c in root.findall('Config') if c.attrib.get('Type')=='Port']
    assert set(ports)=={'10320','10330'}
    assert root.findtext('Icon').startswith('https://')
