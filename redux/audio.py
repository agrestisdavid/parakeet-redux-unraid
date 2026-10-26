"""Bounded decoding to the single model input format (mono 16 kHz PCM16)."""
import asyncio
from pathlib import Path
import wave


async def normalize(source: Path, dest: Path, max_seconds: float, raw=False):
    args = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1',
            '-protocol_whitelist', 'file,pipe',
            '-format_whitelist', 'wav,flac,mp3,ogg,matroska,webm,mov,aac',
            '-i', str(source), '-vn', '-map_metadata', '-1', '-ac', '1', '-ar', '16000',
            '-t', str(max_seconds + 0.1), '-c:a', 'pcm_s16le', '-threads', '1', '-y', str(dest)]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, errors = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode:
            raise ValueError('Cannot decode this audio file')
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    with wave.open(str(dest), 'rb') as wav:
        duration = wav.getnframes() / wav.getframerate()
        if duration <= 0 or duration > max_seconds:
            raise ValueError(f'Audio must be nonempty and at most {max_seconds:g} seconds')
    return duration


def write_pcm(path, pcm, rate, width, channels):
    with wave.open(str(path), 'wb') as wav:
        wav.setframerate(rate)
        wav.setsampwidth(width)
        wav.setnchannels(channels)
        wav.writeframes(pcm)
