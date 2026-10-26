"""Reproducible synthetic-only benchmark. Endpoints are CLI args, never hardcoded."""
import argparse
import asyncio
import hashlib
import io
import json
from pathlib import Path
import random
import time
import wave
import aiohttp
import numpy as np
from wyoming.event import async_read_event, async_write_event, Event


def wav_read(path):
    with wave.open(str(path),'rb') as w:
        assert w.getsampwidth()==2 and w.getnchannels()==1
        return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float64)/32768,w.getframerate()


def wav_write(path, samples, rate):
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,rate,0,'NONE','not compressed'))
        w.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())


async def generate(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    corpus=json.loads(Path(args.corpus).read_text(encoding='utf-8'))
    manifest=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as client:
        for item in corpus:
            path=out/(item['id']+'.wav')
            params={'input':item['text'],'voice':'sohee','language':'german','response_format':'wav','stream':False,
                    'temperature':0.1,'top_p':0.3,'top_k':150,'repetition_penalty':1.3,'do_sample':True,'seed':0,
                    'max_new_tokens':4096,'non_streaming_mode':False,'streaming_chunk_size':120,
                    'token_safety_margin':8,'max_segment_chars':500,'segment_pause_ms':120}
            params.update(item.get('tts_options', {}))
            # Resume only this corpus: hash records prevent stale audio silently passing.
            request_hash=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
            record=out/(item['id']+'.generation.json')
            if not (path.exists() and record.exists() and json.loads(record.read_text())['request_hash']==request_hash):
                start=time.monotonic()
                async with client.post(args.tts.rstrip('/')+'/v1/audio/speech',json=params) as r:
                    if r.status!=200: raise RuntimeError(f'TTS {r.status}: {(await r.text())[:200]}')
                    audio=await r.read()
                path.write_bytes(audio)
                record.write_text(json.dumps({'request_hash':request_hash,'parameters':params,'generation_seconds':time.monotonic()-start},ensure_ascii=False,indent=2),encoding='utf-8')
            pcm,rate=wav_read(path)
            rms=float(np.sqrt(np.mean(pcm**2)));duration=len(pcm)/rate
            assert rms>0.001 and 1<duration<180, (item['id'],duration,rms)
            entry={**item,'file':path.name,'duration':duration,'sample_rate':rate,'rms':rms,
                   'peak':float(np.max(np.abs(pcm))),'clipped_fraction':float(np.mean(np.abs(pcm)>=0.999)),
                   'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'condition':'clean'}
            manifest.append(entry)
            print(item['id'],round(duration,2),'seconds',flush=True)
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


def variants(args):
    out=Path(args.output)
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    manifest=[x for x in manifest if x['condition']=='clean']
    rng=np.random.default_rng(20261026)
    # Deterministic pink-ish stationary noise, not a claim about real room noise.
    for entry in [x for x in manifest if x['id'] in ('cmd01','cmd03','name01','dict01')]:
        pcm,rate=wav_read(out/entry['file'])
        white=rng.normal(size=len(pcm));freq=np.fft.rfftfreq(len(pcm),1/rate)
        spectrum=np.fft.rfft(white)/np.sqrt(np.maximum(freq,40))
        noise=np.fft.irfft(spectrum,n=len(pcm));noise/=np.sqrt(np.mean(noise**2))
        active=pcm[np.abs(pcm)>0.01]
        speech_rms=np.sqrt(np.mean(active**2))
        for snr in (10,0):
            mixed=pcm+noise*speech_rms/(10**(snr/20))
            mixed*=min(1,0.98/np.max(np.abs(mixed)))
            name=entry['id']+f'_noise{snr}'
            path=out/(name+'.wav');wav_write(path,mixed,rate)
            manifest.append({**entry,'id':name,'file':path.name,'condition':f'noise_{snr}dB',
                             'noise_seed':20261026,'snr_reference':'RMS of speech samples with abs>0.01',
                             'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    silence=out/'silence.wav';wav_write(silence,np.zeros(3*24000),24000)
    manifest.append({'id':'silence','kind':'control','text':'','file':silence.name,'duration':3,'sample_rate':24000,
                     'condition':'silence','sha256':hashlib.sha256(silence.read_bytes()).hexdigest()})
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


async def http_transcribe(client,url,entry,out):
    data=(out/entry['file']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==entry['sha256']
    form=aiohttp.FormData()
    form.add_field('file',data,filename='speech.wav',content_type='audio/wav')
    form.add_field('model','whisper-1');form.add_field('language','de');form.add_field('response_format','json')
    start=time.perf_counter()
    async with client.post(url.rstrip('/')+'/v1/audio/transcriptions',data=form) as r:
        body=await r.text();elapsed=time.perf_counter()-start
        if r.status!=200:raise RuntimeError(f'ASR {r.status}: {body[:200]}')
        text=json.loads(body)['text']
        inference=r.headers.get('X-Inference-Seconds')
    return {'text':text,'seconds':elapsed,'inference_seconds':float(inference) if inference else None}


async def wyoming_transcribe(host,port,entry,out,realtime):
    with wave.open(str(out/entry['file']),'rb') as wav:
        rate,width,channels=wav.getframerate(),wav.getsampwidth(),wav.getnchannels()
        pcm=wav.readframes(wav.getnframes())
    # Current faster-whisper accepts Wyoming native sample-rate metadata.
    reader,writer=await asyncio.open_connection(host,port)
    fmt={'rate':rate,'width':width,'channels':channels}
    async def send(kind,data=None,payload=None):
        await async_write_event(Event(type=kind,data=data or {},payload=payload),writer)
    try:
        await send('transcribe',{'language':'de'})
        await send('audio-start',fmt)
        start=time.perf_counter();chunk_frames=round(rate*.1)
        for index,offset in enumerate(range(0,len(pcm),chunk_frames*width*channels)):
            chunk=pcm[offset:offset+chunk_frames*width*channels]
            # Deliver a chunk only after its samples would have been captured.
            if realtime:
                available=(offset+len(chunk))/(rate*width*channels)
                await asyncio.sleep(max(0,start+available-time.perf_counter()))
            await send('audio-chunk',fmt,chunk)
        audio_end=time.perf_counter()
        await send('audio-stop')
        while True:
            event=await asyncio.wait_for(async_read_event(reader),180)
            if event is None:raise RuntimeError('Wyoming disconnected without transcript')
            if event.type=='error':raise RuntimeError(str(event.data))
            if event.type=='transcript':
                finished=time.perf_counter()
                return {'text':event.data['text'],'seconds':finished-start,'post_audio_seconds':finished-audio_end}
    finally:
        writer.close();await writer.wait_closed()


async def run(args):
    out=Path(args.output);manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    if args.mode=='realtime':manifest=[x for x in manifest if x['condition']=='clean' and x['kind']=='command']
    endpoints={'redux':args.redux,'whisper':args.whisper}
    result_file=out/('results-'+args.mode+'.jsonl')
    # Fail on accidental overwrite. Use a separate output directory for another experiment.
    assert not result_file.exists(), f'{result_file} already exists'
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240)) as client:
        for name,url in endpoints.items():
            warm=await http_transcribe(client,url,manifest[0],out)
            (out/f'warmup-{args.mode}-{name}.json').write_text(json.dumps(warm,ensure_ascii=False),encoding='utf-8')
        rng=random.Random(20261026)
        with result_file.open('w',encoding='utf-8') as log:
            for rep in range(args.repetitions):
                entries=manifest.copy();rng.shuffle(entries)
                for entry in entries:
                    names=list(endpoints);rng.shuffle(names)
                    for name in names:
                        if args.mode=='http':res=await http_transcribe(client,endpoints[name],entry,out)
                        else:res=await wyoming_transcribe(args.host,args.redux_port if name=='redux' else args.whisper_port,entry,out,True)
                        row={'id':entry['id'],'system':name,'repetition':rep,'mode':args.mode,
                             'duration':entry['duration'],'kind':entry['kind'],'condition':entry['condition'],**res}
                        log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
                        print(args.mode,rep,entry['id'],name,round(res['seconds'],3),res['text'],flush=True)
                        await asyncio.sleep(.25)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['generate','variants','run'])
    p.add_argument('--output',default='benchmark-output');p.add_argument('--corpus',default='benchmarks/corpus.json')
    p.add_argument('--tts');p.add_argument('--redux');p.add_argument('--whisper');p.add_argument('--host')
    p.add_argument('--redux-port',type=int,default=10330);p.add_argument('--whisper-port',type=int,default=10310)
    p.add_argument('--mode',choices=['http','realtime'],default='http');p.add_argument('--repetitions',type=int,default=3)
    a=p.parse_args()
    if a.action=='generate':asyncio.run(generate(a))
    elif a.action=='variants':variants(a)
    else:asyncio.run(run(a))

if __name__=='__main__':main()
