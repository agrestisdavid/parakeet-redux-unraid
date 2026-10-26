"""Bounded Wyoming audio transport. Redux is utterance-final, not incremental ASR."""
import asyncio
import json
import time
from wyoming.event import Event, async_write_event
from wyoming.asr import Transcript
from wyoming.error import Error
from wyoming.info import Info, AsrProgram, AsrModel, Attribution
from . import __version__

LANGUAGES = 'bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro ru sk sl es sv uk'.split()
RATES = {8000, 16000, 22050, 24000, 44100, 48000}


def language_ok(language):
    return language in (None, '', 'auto') or (isinstance(language, str) and language.lower().replace('_', '-').split('-')[0] in LANGUAGES)


def info():
    return Info(asr=[AsrProgram(
        name='parakeet-redux', attribution=Attribution(name='Parakeet Redux Unraid', url='https://github.com/agrestisdavid/parakeet-redux-unraid'),
        installed=True, description='CPU speech recognition; audio chunks, final transcript after audio-stop', version=__version__,
        models=[AsrModel(name='parakeet-redux', attribution=Attribution(name='Moondream and NVIDIA', url='https://huggingface.co/moondream/parakeet-redux'),
                         installed=True, description='Redux packed GGUF via parakeet.cpp; automatic language detection', version='c77726e', languages=LANGUAGES)],
        supports_transcript_streaming=False, requires_external_vad=True)]).event()


async def read_event(reader):
    line = await reader.readline()  # server StreamReader limit caps the header
    if not line:
        return None
    if len(line) > 16384:
        raise ValueError('Wyoming header too large')
    header = json.loads(line)
    if not isinstance(header, dict) or not isinstance(header.get('type'), str):
        raise ValueError('Invalid Wyoming header')
    data = header.get('data', {})
    lengths = []
    for key, maximum in [('data_length', 16384), ('payload_length', 65536)]:
        size = header.get(key, 0)
        if type(size) is not int or not 0 <= size <= maximum:
            raise ValueError(f'Invalid {key}')
        lengths.append(size)
    if lengths[0]:
        extra = json.loads(await reader.readexactly(lengths[0]))
        if not isinstance(data, dict) or not isinstance(extra, dict):
            raise ValueError('Invalid event data')
        data = {**data, **extra}
    if not isinstance(data, dict):
        raise ValueError('Invalid event data')
    payload = await reader.readexactly(lengths[1]) if lengths[1] else None
    return Event(type=header['type'], data=data, payload=payload)


class Wyoming:
    def __init__(self, transcribe_pcm, max_seconds=180, idle_timeout=30, max_clients=4):
        self.transcribe_pcm = transcribe_pcm
        self.max_seconds, self.idle_timeout, self.max_clients = max_seconds, idle_timeout, max_clients
        self.clients = set()
        self.tasks = set()

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        if len(self.clients) >= self.max_clients:
            writer.close()
            await writer.wait_closed()
            return
        self.clients.add(writer)
        self.tasks.add(task)
        pcm = bytearray()
        fmt = None
        started = None
        requested = False
        inference = watcher = None
        try:
            while True:
                timeout = self.idle_timeout
                if started is not None:
                    timeout = min(timeout, max(0.001, started + self.max_seconds + 10 - time.monotonic()))
                event = await asyncio.wait_for(read_event(reader), timeout)
                if event is None:
                    return
                if event.type == 'describe':
                    await async_write_event(info(), writer)
                elif event.type == 'transcribe':
                    if fmt is not None:
                        raise ValueError('Recording already active')
                    if not language_ok(event.data.get('language')):
                        raise ValueError('Unsupported language')
                    requested = True
                elif event.type == 'audio-start':
                    if not requested or fmt is not None:
                        raise ValueError('Send transcribe before one audio-start')
                    rate, width, channels = (event.data.get(k) for k in ('rate', 'width', 'channels'))
                    if any(type(v) is not int for v in (rate, width, channels)) or rate not in RATES or width != 2 or channels not in (1, 2):
                        raise ValueError('Supported audio: PCM16LE, mono/stereo, 8–48 kHz standard rates')
                    fmt = (rate, width, channels)
                    started = time.monotonic()
                    pcm.clear()
                elif event.type == 'audio-chunk':
                    if fmt is None or not event.payload:
                        raise ValueError('Audio chunk requires audio-start and nonempty PCM')
                    if tuple(event.data.get(k) for k in ('rate', 'width', 'channels')) != fmt:
                        raise ValueError('Audio format changed mid-recording')
                    if len(event.payload) % (fmt[1] * fmt[2]):
                        raise ValueError('Incomplete PCM frame')
                    if len(pcm) + len(event.payload) > self.max_seconds * fmt[0] * fmt[1] * fmt[2]:
                        raise ValueError('Audio too long')
                    pcm.extend(event.payload)
                elif event.type == 'audio-stop':
                    if fmt is None or not pcm:
                        raise ValueError('No audio to transcribe')
                    inference = asyncio.create_task(self.transcribe_pcm(bytes(pcm), *fmt))
                    async def watch_disconnect():
                        while not reader.at_eof():
                            await asyncio.sleep(0.05)
                    watcher = asyncio.create_task(watch_disconnect())
                    done, _ = await asyncio.wait([inference, watcher], return_when=asyncio.FIRST_COMPLETED)
                    if inference not in done:
                        inference.cancel()
                        await asyncio.gather(inference, return_exceptions=True)
                        return
                    result = await inference
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)
                    await async_write_event(Transcript(text=result['text']).event(), writer)
                    pcm.clear()
                    fmt, started, requested = None, None, False
                else:
                    raise ValueError('Unsupported event')
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = 'busy' if isinstance(exc, BlockingIOError) else 'transcription-failed'
            # Do not send internal paths or native errors to network clients.
            text = str(exc) if isinstance(exc, (ValueError, BlockingIOError)) else 'Transcription unavailable or timed out'
            try:
                await async_write_event(Error(text=text, code=code).event(), writer)
            except (ConnectionError, OSError):
                pass
        finally:
            for child in (inference, watcher):
                if child and not child.done():
                    child.cancel()
                    await asyncio.gather(child, return_exceptions=True)
            self.clients.discard(writer)
            self.tasks.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
