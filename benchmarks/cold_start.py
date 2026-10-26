"""Process-cold first-transcription test for the NEW Redux app only.

Run on the Docker host. This deliberately restarts only Parakeet-Redux; never
use it as permission to restart existing Whisper or any unrelated service.
OS/disk caches are not dropped. Reports readiness, first transcription, warm
transcriptions, and restart-to-first-result separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time
import urllib.request
import uuid


def request(url, data, content_type):
    req = urllib.request.Request(url.rstrip('/') + '/v1/audio/transcriptions', data=data,
                                 headers={'Content-Type': content_type})
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as response:
        body = json.load(response)
        seconds = time.perf_counter() - started
        native = float(response.headers['X-Inference-Seconds'])
    return {'seconds': seconds, 'inference_seconds': native, 'text': body['text']}


def main(args):
    if not args.allow_restart:
        raise SystemExit('Explicit --allow-restart is required; only the NEW Redux app may be restarted')
    name = 'Parakeet-Redux'
    inspected = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    if not inspected['Config']['Image'].startswith('ghcr.io/agrestisdavid/parakeet-redux-unraid'):
        raise SystemExit('Refuse: this is not the expected Redux project image')
    data = Path(args.audio).read_bytes()
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nde\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
            f'Content-Type: audio/wav\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
    kind = 'multipart/form-data; boundary=' + boundary
    rows = []
    for _ in range(3):
        start = time.perf_counter()
        subprocess.run(['docker', 'restart', '-t', '20', name], check=True, stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(args.http.rstrip('/') + '/health', timeout=2) as response:
                    health = json.load(response)
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('Readiness timeout')
        readiness = time.perf_counter() - start
        first = request(args.http, body, kind)
        total = time.perf_counter() - start
        warm = [request(args.http, body, kind) for _ in range(3)]
        assert len({r['text'] for r in [first, *warm]}) == 1
        rows.append({'version': health['version'], 'restart_to_ready_seconds': readiness,
                     'restart_to_first_transcript_seconds': total, 'first_request': first, 'warm_requests': warm})
    result = {'method': 'Three independent container/model-process restarts. Persistent disk model cache and OS page cache retained. No system cache flush. Only new Redux app restarted.',
              'image': inspected['Config']['Image'], 'audio_sha256': hashlib.sha256(data).hexdigest(),
              'runs': rows,
              'median_restart_to_ready_seconds': statistics.median(r['restart_to_ready_seconds'] for r in rows),
              'median_restart_to_first_transcript_seconds': statistics.median(r['restart_to_first_transcript_seconds'] for r in rows),
              'median_first_request_seconds': statistics.median(r['first_request']['seconds'] for r in rows),
              'median_warm_request_seconds': statistics.median(x['seconds'] for r in rows for x in r['warm_requests'])}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--http', required=True)
    p.add_argument('--audio', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--allow-restart', action='store_true')
    main(p.parse_args())
