import asyncio
import hmac
import json
import logging
import os
from pathlib import Path
import signal
import tempfile
import time
from aiohttp import web
from . import __version__
from .audio import normalize, write_pcm
from .engine import Engine, ensure_model, MODEL_REVISION
from .protocol import Wyoming, language_ok

LOG = logging.getLogger('redux')


def bounded_env(name, default, minimum, maximum):
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return value


class Service:
    def __init__(self, engine, max_seconds=180):
        self.engine, self.max_seconds = engine, max_seconds
        self.admission = asyncio.Lock()

    async def transcribe(self, source, workdir):
        if self.admission.locked():
            raise BlockingIOError('Inference busy; retry shortly')
        async with self.admission:
            dest = Path(workdir) / 'normalized.wav'
            duration = await normalize(Path(source), dest, self.max_seconds)
            result = await self.engine.transcribe(dest)
            doc = result['result']
            return {'text': doc['text'], 'duration': duration, 'language': None,
                    'words': [{'word': w['w'], 'start': w['start'], 'end': w['end']} for w in doc.get('words', [])],
                    'inference_seconds': result['inference_seconds']}

    async def pcm(self, pcm, rate, width, channels):
        with tempfile.TemporaryDirectory(prefix='redux-') as tmp:
            path = Path(tmp) / 'input.wav'
            write_pcm(path, pcm, rate, width, channels)
            return await self.transcribe(path, tmp)


def stamp(seconds, separator):
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, ms = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02}{separator}{ms:03}'


def format_result(result, fmt):
    if fmt == 'json':
        return web.json_response({'text': result['text']})
    if fmt == 'verbose_json':
        return web.json_response({**result, 'task': 'transcribe', 'segments': [
            {'id': 0, 'start': 0, 'end': result['duration'], 'text': result['text']}
        ]})
    if fmt == 'text':
        return web.Response(text=result['text'], content_type='text/plain')
    separator = ',' if fmt == 'srt' else '.'
    header = '1\n' if fmt == 'srt' else 'WEBVTT\n\n'
    text = f'{header}{stamp(0, separator)} --> {stamp(result["duration"], separator)}\n{result["text"]}\n'
    return web.Response(text=text, content_type='text/plain' if fmt == 'srt' else 'text/vtt')


def create_app(service, api_key='', max_upload=25 * 1024 * 1024):
    @web.middleware
    async def errors(request, handler):
        try:
            if request.path.startswith('/v1/') and api_key:
                if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + api_key).encode()):
                    return web.json_response({'error': {'message': 'Invalid API key', 'type': 'authentication_error'}}, status=401)
            return await handler(request)
        except web.HTTPException:
            raise
        except (ValueError, json.JSONDecodeError) as exc:
            return web.json_response({'error': {'message': str(exc), 'type': 'invalid_request_error'}}, status=400)
        except BlockingIOError:
            return web.json_response({'error': {'message': 'Inference busy', 'type': 'server_error'}}, status=429, headers={'Retry-After': '2'})
        except TimeoutError:
            return web.json_response({'error': {'message': 'Request timed out', 'type': 'server_error'}}, status=504)
        except Exception:
            LOG.exception('Request failed')
            return web.json_response({'error': {'message': 'Transcription unavailable', 'type': 'server_error'}}, status=503)

    app = web.Application(client_max_size=max_upload, middlewares=[errors])
    uploads = set()

    async def health(request):
        ready = service.engine.ready
        return web.json_response({'status': 'ok' if ready else 'unavailable', 'version': __version__,
                                  'model': 'moondream/parakeet-redux', 'runtime': 'parakeet.cpp', 'device': 'cpu',
                                  'model_revision': MODEL_REVISION, 'transcript_streaming': False,
                                  'audio_chunk_transport': True}, status=200 if ready else 503)

    async def models(request):
        return web.json_response({'object': 'list', 'data': [{'id': x, 'object': 'model', 'owned_by': 'local'} for x in ('parakeet-redux', 'whisper-1')]})

    async def transcription(request):
        if len(uploads) >= 4:
            raise BlockingIOError()
        task = asyncio.current_task()
        uploads.add(task)
        try:
            async with asyncio.timeout(240):
                with tempfile.TemporaryDirectory(prefix='redux-') as tmp:
                    source = Path(tmp) / 'upload'
                    reader = await request.multipart()
                    fields, total, have_file = {}, 0, False
                    while part := await reader.next():
                        if part.name == 'file':
                            if have_file:
                                raise ValueError('Only one file is allowed')
                            have_file = True
                            with source.open('wb') as out:
                                while chunk := await part.read_chunk(65536):
                                    total += len(chunk)
                                    if total > max_upload:
                                        raise web.HTTPRequestEntityTooLarge(max_size=max_upload, actual_size=total)
                                    out.write(chunk)
                        else:
                            name = part.name
                            if name not in {'model', 'language', 'response_format', 'prompt', 'temperature', 'stream', 'timestamp_granularities[]'}:
                                raise ValueError('Unsupported multipart field')
                            if name in fields:
                                raise ValueError('Duplicate multipart field')
                            value = bytearray()
                            while chunk := await part.read_chunk(4096):
                                value.extend(chunk)
                                if len(value) > 4096:
                                    raise ValueError('Form field too long')
                            fields[name] = value.decode('utf-8')
                    if not have_file or not total:
                        raise ValueError('A nonempty file is required')
                    if fields.get('model', 'parakeet-redux') not in ('parakeet-redux', 'whisper-1', 'moondream/parakeet-redux'):
                        raise ValueError('Unknown model')
                    if not language_ok(fields.get('language')):
                        raise ValueError('Unsupported language')
                    if fields.get('prompt', '') or fields.get('temperature', '') not in ('', '0', '0.0'):
                        raise ValueError('Redux does not support prompts or sampling temperature')
                    if fields.get('stream', '').lower() not in ('', 'false', '0'):
                        raise ValueError('Incremental transcript streaming is not supported')
                    if fields.get('timestamp_granularities[]', 'word') not in ('word', 'segment'):
                        raise ValueError('Unsupported timestamp granularity')
                    fmt = fields.get('response_format', 'json')
                    if fmt not in ('json', 'verbose_json', 'text', 'srt', 'vtt'):
                        raise ValueError('Unsupported response format')
                    start = time.monotonic()
                    result = await service.transcribe(source, tmp)
                    response = format_result(result, fmt)
                    response.headers['X-Inference-Seconds'] = str(result['inference_seconds'])
                    response.headers['X-Processing-Seconds'] = str(time.monotonic() - start)
                    response.headers['X-Language-Mode'] = 'automatic'
                    return response
        finally:
            uploads.discard(task)

    app.router.add_get('/health', health)
    app.router.add_get('/healthz', health)
    app.router.add_get('/v1/models', models)
    app.router.add_post('/v1/audio/transcriptions', transcription)
    async def index(request):
        return web.Response(text='Parakeet Redux CPU service. See /health and the project README.')
    app.router.add_get('/', index)
    return app


async def main():
    logging.basicConfig(level=logging.INFO)
    threads = bounded_env('CPU_THREADS', 2, 1, 64)
    max_seconds = bounded_env('MAX_AUDIO_SECONDS', 180, 1, 600)
    timeout = bounded_env('INFERENCE_TIMEOUT', 120, 1, 600)
    http_port = bounded_env('HTTP_PORT', 8080, 1024, 65535)
    wyoming_port = bounded_env('WYOMING_PORT', 10300, 1024, 65535)
    model = Path(os.getenv('MODEL_DIR', '/data/models')) / 'redux-packed.gguf'
    LOG.info('Verifying pinned Redux model cache')
    await asyncio.to_thread(ensure_model, model)
    engine = Engine(model, threads=threads, timeout=timeout)
    await engine.start()
    service = Service(engine, max_seconds)
    wyoming = Wyoming(service.pcm, max_seconds)
    runner = web.AppRunner(create_app(service, os.getenv('API_KEY', '')), handler_cancellation=True, shutdown_timeout=10)
    tcp = None
    try:
        await runner.setup()
        await web.TCPSite(runner, '0.0.0.0', http_port).start()
        tcp = await asyncio.start_server(wyoming.handle, '0.0.0.0', wyoming_port, limit=16384)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        LOG.info('Ready: CPU-only, HTTP=%s Wyoming=%s; no incremental transcript streaming', http_port, wyoming_port)
        await stop.wait()
    finally:
        if tcp:
            tcp.close()
            await tcp.wait_closed()
        await wyoming.close()
        await runner.cleanup()
        await engine.close()


if __name__ == '__main__':
    asyncio.run(main())
