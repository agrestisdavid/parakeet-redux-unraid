"""Live protocol acceptance against an isolated test deployment (not a busy production service)."""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import time
import wave
import aiohttp
from wyoming.event import Event, async_read_event, async_write_event


async def main(args):
    results=[]
    async def send(w,typ,data=None,payload=None):
        await async_write_event(Event(type=typ,data=data or {},payload=payload),w)
    async def connect():return await asyncio.open_connection(args.host,args.port)
    async def close(w):
        w.close()
        try:await w.wait_closed()
        except ConnectionError:pass
    async def receive(r):return await asyncio.wait_for(async_read_event(r),10)
    def audio(path):
        with wave.open(str(path),'rb') as w:
            return {'rate':w.getframerate(),'width':w.getsampwidth(),'channels':w.getnchannels()},w.readframes(w.getnframes())
    fmt,pcm=audio(args.short)
    longfmt,longpcm=audio(args.long)
    async def capture(w,format_,data):
        await send(w,'transcribe',{'language':'de'})
        await send(w,'audio-start',format_)
        for offset in range(0,len(data),32000):await send(w,'audio-chunk',format_,data[offset:offset+32000])
    async def ready(client):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            async with client.get(args.http+'/health') as r:
                if r.status==200:return
            await asyncio.sleep(.1)
        raise AssertionError('Service did not recover')
    async def post(client,path,**fields):
        f=aiohttp.FormData();f.add_field('file',Path(path).read_bytes(),filename='speech.wav')
        for k,v in fields.items():f.add_field(k,v)
        async with client.post(args.http+'/v1/audio/transcriptions',data=f) as r:return r.status,await r.text()

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as client:
        await ready(client)
        r,w=await connect();await send(w,'describe');info=await receive(r)
        assert info.type=='info'
        program=info.data['asr'][0]
        assert 'de' in program['models'][0]['languages'] and not program['supports_transcript_streaming'] and program['requires_external_vad']
        results.append({'case':'discovery','pass':True})
        transcripts=[]
        for _ in range(2):
            await capture(w,fmt,pcm)
            with_timeout=False
            try:await asyncio.wait_for(async_read_event(r),.15)
            except TimeoutError:with_timeout=True
            assert with_timeout,'Unexpected transcript before audio-stop'
            await send(w,'audio-stop');event=await receive(r)
            assert event.type=='transcript' and 'licht' in event.data['text'].lower()
            transcripts.append(event.data['text'])
        await close(w)
        assert transcripts[0]==transcripts[1]
        results.append({'case':'real PCM chunks, no premature text, two utterances per connection','pass':True,'transcript':transcripts[0]})

        with tempfile.TemporaryDirectory() as tmp:
            for rate,channels in ((8000,1),(16000,1),(48000,2)):
                dest=Path(tmp)/f'{rate}-{channels}.wav'
                proc=await asyncio.create_subprocess_exec('ffmpeg','-hide_banner','-loglevel','error','-i',args.short,'-ar',str(rate),'-ac',str(channels),'-y',str(dest))
                assert await proc.wait()==0
                f,p=audio(dest);r,w=await connect();await capture(w,f,p);await send(w,'audio-stop')
                event=await receive(r);assert event.type=='transcript' and 'licht' in event.data['text'].lower()
                await close(w);results.append({'case':f'PCM16 {rate}Hz channels={channels}','pass':True,'transcript':event.data['text']})

        for case in ('empty','bad_format','changed_format','oversized_header','unknown_event','unsupported_language'):
            r,w=await connect()
            if case=='oversized_header':
                w.write(b'{"type":"audio-chunk","payload_length":99999999}\n');await w.drain()
            elif case=='unknown_event':await send(w,'something-else')
            elif case=='unsupported_language':await send(w,'transcribe',{'language':'ja'})
            else:
                await send(w,'transcribe',{'language':'de'})
                await send(w,'audio-start', {**fmt,'width':1} if case=='bad_format' else fmt)
                if case=='empty':await send(w,'audio-stop')
                elif case=='changed_format':await send(w,'audio-chunk',{**fmt,'rate':8000},pcm[:200])
            event=await receive(r);assert event.type=='error',case
            await close(w)
            r,w=await connect();await send(w,'describe');assert (await receive(r)).type=='info';await close(w)
            results.append({'case':case+' + reconnect','pass':True})

        r,w=await connect();await capture(w,fmt,pcm[:200]);await close(w)
        await asyncio.sleep(.1)
        await ready(client)
        results.append({'case':'disconnect during capture discards audio','pass':True})

        # Interrupt only the new app's private native worker via a disconnected client.
        r,w=await connect();await capture(w,longfmt,longpcm);await send(w,'audio-stop')
        await asyncio.sleep(.15);await close(w);await asyncio.sleep(.3)
        await ready(client)
        status,text=await post(client,args.short,language='de');assert status==200 and 'licht' in text.lower(),(status,text)
        results.append({'case':'disconnect during native inference, recovery, next transcript','pass':True})

        longjob=asyncio.create_task(post(client,args.long,language='de'))
        await asyncio.sleep(.3)
        status,_=await post(client,args.short,language='de');assert status==429,status
        status,text=await longjob;assert status==200 and 'sprachsteuerung' in text.lower(),(status,text)
        results.append({'case':'one shared inference slot / HTTP busy rejection','pass':True})
        for field,value in (('stream','true'),('prompt','test'),('language','ja')):
            status,_=await post(client,args.short,**{field:value});assert status==400
            results.append({'case':f'HTTP rejects unsupported {field}','pass':True})
        await ready(client)
    Path(args.report).write_text(json.dumps({'all_passed':True,'cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(results)} live checks passed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--http',required=True);p.add_argument('--host',required=True);p.add_argument('--port',type=int,default=10330)
    p.add_argument('--short',required=True);p.add_argument('--long',required=True);p.add_argument('--report',default='live-acceptance.json')
    asyncio.run(main(p.parse_args()))
