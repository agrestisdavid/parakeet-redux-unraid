"""Existing GPU Whisper process-cold benchmark: EXPLICIT MAINTENANCE APPROVAL ONLY.

Restarts only the named faster-whisper container, at most three times. Never
changes its configuration/model/image/ports, never restarts the HTTP bridge or
other services, and stops testing on the first error. Readiness is Wyoming
protocol readiness (not proof of loaded weights); the first actual transcription
is timed separately and also inclusively from restart. OS caches are retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import statistics
import subprocess
import time
import urllib.request
import uuid


def inspect(name):
    return json.loads(subprocess.check_output(['docker', 'inspect', name], timeout=10))[0]


def signature(container):
    result = {key: container[key] for key in ('Id', 'Image', 'Config', 'HostConfig')}
    # Docker constructs this list from a map: ordering is not configuration.
    result['Mounts'] = sorted(container['Mounts'], key=lambda mount: mount['Destination'])
    return result


def protocol_ready(host, port):
    with socket.create_connection((host, port), timeout=1) as s:
        s.settimeout(2)
        s.sendall(b'{"type":"describe"}\n')
        reader = s.makefile('rb')
        header = json.loads(reader.readline(16384))
        assert header.get('type') == 'info', 'No Wyoming info response'
        length = header.get('data_length', 0)
        assert type(length) is int and 0 <= length <= 65536
        data = header.get('data', {})
        if length:
            data.update(json.loads(reader.read(length)))
        assert data.get('asr'), 'No ASR program in discovery response'


def main(args):
    if not args.approved_maintenance:
        raise SystemExit('Requires explicit operator maintenance approval')
    name = 'faster-whisper'
    original = inspect(name)
    assert original['State']['Running'], 'Refuse to start a previously stopped service'
    guards = {n: inspect(n) for n in args.guard_container}
    protected = Path(args.private_record)
    protected.write_text(json.dumps({'whisper': original, 'guards': guards}, indent=2))
    protected.chmod(0o600)
    sig = signature(original)
    audio = Path(args.audio).read_bytes()
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nde\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
            f'Content-Type: audio/wav\r\n\r\n').encode() + audio + f'\r\n--{boundary}--\r\n'.encode()
    maintenance_deadline = time.monotonic() + 180
    rows = []

    def transcribe():
        remaining = maintenance_deadline - time.monotonic()
        if remaining < 1:
            raise TimeoutError('Maintenance budget exhausted')
        req = urllib.request.Request(args.http.rstrip('/') + '/v1/audio/transcriptions', data=body,
                                     headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        started = time.perf_counter()
        with urllib.request.urlopen(req, timeout=min(45, remaining)) as response:
            result = json.load(response)
        elapsed = time.perf_counter() - started
        # This fixture is deliberately generic; no real user speech is recorded.
        normalized = ' '.join(result['text'].lower().strip(' .!?\n').split())
        assert normalized == 'schalte das licht in der küche ein', 'Unexpected first/warm transcript'
        return {'seconds': elapsed, 'text': result['text']}

    def wait_ready(deadline):
        while time.monotonic() < deadline:
            try:
                protocol_ready(args.host, args.wyoming_port)
                return
            except (OSError, ValueError, AssertionError):
                time.sleep(.1)
        raise TimeoutError('Whisper protocol readiness timeout')

    try:
        for _ in range(3):
            if maintenance_deadline - time.monotonic() < 30:
                raise TimeoutError('Not enough maintenance budget for another restart')
            assert signature(inspect(name)) == sig, 'Whisper config changed before restart'
            start = time.perf_counter()
            subprocess.run(['docker', 'restart', '-t', '20', name], check=True, timeout=60,
                           stdout=subprocess.DEVNULL)
            wait_ready(min(time.monotonic() + 45, maintenance_deadline))
            ready = time.perf_counter() - start
            first = transcribe()
            total = time.perf_counter() - start
            warm = [transcribe() for _ in range(3)]
            assert signature(inspect(name)) == sig, 'Whisper config changed during maintenance'
            rows.append({'restart_to_protocol_ready_seconds': ready,
                         'restart_to_first_transcript_seconds': total,
                         'first_request': first, 'warm_requests': warm})
            # Preserve measured timings even if a later guard check fails.
            Path(args.output).write_text(json.dumps({'status': 'partial_pending_final_verification',
                'audio_sha256': hashlib.sha256(audio).hexdigest(), 'runs': rows},
                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except BaseException:
        # No further test cycles. Only restore the same existing container to running.
        if not inspect(name)['State']['Running']:
            subprocess.run(['docker', 'start', name], check=True, timeout=30, stdout=subprocess.DEVNULL)
        wait_ready(time.monotonic() + 60)
        raise
    final = inspect(name)
    assert signature(final) == sig and final['State']['Running']
    for guard, before in guards.items():
        after = inspect(guard)
        assert signature(after) == signature(before), f'Guard config changed: {guard}'
        assert after['State']['Running'] and after['State']['StartedAt'] == before['State']['StartedAt'], f'Guard restarted: {guard}'
    result = {'method': 'Operator-approved maintenance: three existing GPU Whisper process restarts, same fixture as Redux. No model/config/image/port changes. Bridge and guard services not restarted. Model disk and OS caches retained. Protocol readiness is not asserted to mean model weights already loaded.',
              'audio_sha256': hashlib.sha256(audio).hexdigest(), 'runs': rows,
              'median_restart_to_protocol_ready_seconds': statistics.median(r['restart_to_protocol_ready_seconds'] for r in rows),
              'median_restart_to_first_transcript_seconds': statistics.median(r['restart_to_first_transcript_seconds'] for r in rows),
              'median_first_request_seconds': statistics.median(r['first_request']['seconds'] for r in rows),
              'median_warm_request_seconds': statistics.median(x['seconds'] for r in rows for x in r['warm_requests']),
              'verification': {'whisper_running': True, 'whisper_config_image_identity_unchanged': True,
                               'whisper_restart_authorized': True, 'all_guard_configs_and_start_times_unchanged': True}}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--approved-maintenance', action='store_true')
    p.add_argument('--http', required=True)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--wyoming-port', type=int, default=10310)
    p.add_argument('--audio', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--private-record', required=True, help='Protected full inspect backup: NEVER publish this file')
    p.add_argument('--guard-container', action='append', default=[])
    main(p.parse_args())
