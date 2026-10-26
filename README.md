# Parakeet Redux for Unraid

<img src="assets/icon.svg" width="96" alt="Parakeet Redux icon">

CPU-only **Moondream Parakeet Redux**, served through an OpenAI-style HTTP API
and **Wyoming** for Home Assistant. One persistent model, two interfaces.

This repository is prepared for manual Unraid installation. **It has not been
submitted to or listed in Community Applications.** Independent integration;
not an official Moondream, NVIDIA, Unraid or Home Assistant app.

## Model versus runtime

- Model: [Moondream Parakeet Redux](https://huggingface.co/moondream/parakeet-redux),
  the ternary multilingual derivative of NVIDIA Parakeet TDT v3, **not** the
  original NVIDIA checkpoint substituted for Redux.
- Runtime: [parakeet.cpp](https://github.com/mudler/parakeet.cpp), MIT, pinned source.
- Model format: `redux-packed.gguf`, converted with `--ternary keep`, 213 MB.
- No Photon or proprietary kestrel kernels. Photon's advertised benchmarks do
  **not** describe this integration. Numerical equivalence to Photon is not claimed.
- 25 supported languages, including German; detection is automatic.
- Linux **amd64 with AVX2**, no GPU or CUDA required. ARM is not supported by this image.
- About 3 GB container memory limit recommended; actual resident use depends on
  audio duration. Model file size is not peak RAM usage.

See [NOTICE.md](NOTICE.md) for licenses, authors, source/model revisions and SHA-256.
Base image, model, native source and Python dependencies are pinned. Since 0.1.1,
Debian and Debian-security repositories are also frozen to **20261026T000000Z**
(`debian.sources`), and directly installed apt packages have explicit versions.
Transitive package resolution uses only that fixed, signed snapshot. Full installed
build/runtime package manifests are retained in `/opt/licenses/*-packages.txt`.
Security updates require a deliberate snapshot/version bump and retest; builds are
not claimed bit-identical because timestamps/tooling metadata can differ. Deploy
an image digest for exact rollback.

## Streaming: what this app actually does

**Audio transport streams; transcription does not.** Wyoming accepts live PCM
chunks, buffers one utterance and returns final text after `audio-stop`. It
advertises `requires_external_vad=true` and `supports_transcript_streaming=false`.
Home Assistant retains endpointing/VAD. No live partial text, SSE, WebSocket ASR
or cache-aware streaming is claimed. Long files are cut at pauses by the model's
built-in VAD into sections of up to 30 seconds after upload completes. The Redux
VAD is not a reliable always-on speech/noise gate; keep HA's VAD in front of it.

## Install on Unraid (manual template, not Community Applications)

1. Download [unraid/parakeet-redux.xml](https://raw.githubusercontent.com/agrestisdavid/parakeet-redux-unraid/main/unraid/parakeet-redux.xml).
2. In an Unraid terminal, copy it to
   `/boot/config/plugins/dockerMan/templates-user/my-Parakeet-Redux.xml`.
   Back up an existing file first; do not overwrite another app's template.
3. Create `/mnt/user/appdata/parakeet-redux/models` and make **only this appdata
   directory** writable by Unraid `nobody:users` (UID 99/GID 100).
4. Docker → Add Container → choose the `Parakeet-Redux` user template.
5. Confirm unused host ports: HTTP **10320**, Wyoming **10330**. Keep your existing
   Whisper ports unchanged. Deploy and wait for the healthcheck.
6. Open the container WebUI (the `/health` JSON endpoint). A first start downloads
   and SHA-256-verifies the pinned model; later starts use the persistent cache.

The template limits the container to two CPU equivalents, 3 GB RAM and 256 PIDs,
uses a read-only root filesystem with a 256 MB temporary filesystem, drops
capabilities, and runs as UID 99/GID 100. Set `CPU_THREADS=2`. If increasing this,
adjust CPU quota and consider other workloads. For consistent latency, pin one
logical thread per physical core using Unraid's CPU controls; there is no
universal CPU numbering suitable for every host.

### Docker alternative

Set `LAN_IP` to your server's LAN address; do not publish these ports to the internet.

```sh
mkdir -p /mnt/user/appdata/parakeet-redux/models
chown -R 99:100 /mnt/user/appdata/parakeet-redux

docker run -d --name Parakeet-Redux --restart unless-stopped \
  --user 99:100 --cpus 2 --memory 3g --pids-limit 256 \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m --stop-timeout 20 \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p "${LAN_IP}:10320:8080" -p "${LAN_IP}:10330:10300" \
  -v /mnt/user/appdata/parakeet-redux:/data \
  -e CPU_THREADS=2 \
  ghcr.io/agrestisdavid/parakeet-redux-unraid:0.1.1
```

## Interfaces

- `GET /health` or `/healthz`: 200 only while model worker is ready, otherwise 503.
- `GET /v1/models`: `parakeet-redux` and compatibility alias `whisper-1`.
- `POST /v1/audio/transcriptions`: multipart `file`, optional `model`, `language`,
  `response_format`. WAV, MP3, FLAC, Ogg, WebM, M4A via bounded FFmpeg decoding.
- Formats: `json`, `text`, `verbose_json`, `srt`, `vtt`. Word timestamps in verbose
  JSON are native; the returned segment/SRT/VTT cue covers the whole utterance.
- `language=de`/`de-DE` is validated but **not forced**. Redux detects language
  implicitly and does not return a language code; verbose JSON reports `null`.
- Nonempty prompts, nonzero temperature and `stream=true` are rejected, not silently
  ignored. This is not a complete drop-in replacement for every Whisper API option.
- Limit: 25 MiB encoded upload, 180 seconds audio by default, four concurrent uploads
  and four Wyoming connections. One inference across both interfaces; when busy,
  HTTP returns 429 / Wyoming an error. Clients may retry after the current request.
- `X-Inference-Seconds` excludes audio decoding/network transport.
- Optional `API_KEY` requires HTTP bearer auth on `/v1/*`; health is public.
- Wyoming PCM: signed little-endian 16 bit, mono or stereo, rates 8000, 16000,
  22050, 24000, 44100, 48000 Hz. Format must remain fixed during each utterance.
  Event payload <=64 KiB; a client sends transcribe, audio-start, audio-chunks,
  audio-stop and waits for transcript. A subsequent utterance can reuse the connection.

```sh
curl "http://${LAN_IP}:10320/v1/audio/transcriptions" \
  -F file=@speech.wav -F model=parakeet-redux -F language=de
```

## Home Assistant (optional manual step)

For a separate trial integration, use Settings → Devices & services → Add
integration → Wyoming Protocol, server LAN address, port **10330**. Then choose
Parakeet Redux in a test Assist pipeline. This project does **not** edit HA,
replace a pipeline, stop Whisper or move ports automatically. Perform that
step only when you intend to change HA configuration. The protocol tests do
not substitute for a real microphone/Assist end-to-end test.

**Security:** Wyoming has no authentication/TLS. Use only on a trusted LAN,
restrict access with your network firewall, and never port-forward it. The
optional HTTP key does not protect Wyoming. No telemetry, cloud inference,
transcript logging or audio persistence is implemented. Temporary audio is
removed after requests; failed process exits are contained by the tmpfs.

## Configuration / operations

| Variable | Default | Purpose |
|---|---|---|
| CPU_THREADS | 2 | Native CPU thread budget, 1–64 |
| MAX_AUDIO_SECONDS | 180 | Maximum length, 1–600 |
| INFERENCE_TIMEOUT | 120 | Native worker deadline, 1–600 seconds |
| MODEL_DIR | /data/models | Persistent model cache |
| HTTP_PORT | 8080 | Internal HTTP listener |
| WYOMING_PORT | 10300 | Internal Wyoming listener |
| API_KEY | empty | Optional bearer token, HTTP only |

A crash, timeout or cancellation kills only the inference subprocess, then
reloads the model. Health is unavailable during reload. Failed reload remains
unhealthy rather than claiming success; inspect `docker logs Parakeet-Redux`.
The model hash is verified at container startup; corrupt cache files cause a
clear startup failure, never a silent replacement with another model.

### Update and rollback

1. Note the currently installed image digest and back up this app's XML/appdata.
2. Read the release notes, select an explicit version/digest and pull it.
3. Recreate **only this container** with unchanged ports/mounts/settings.
4. Verify health, a known HTTP transcript, Wyoming discovery and an audio roundtrip.
5. If those fail, recreate with the previous digest. Do not alter Whisper.

To remove the app: stop/remove `Parakeet-Redux`, remove only its user template,
and optionally delete only `/mnt/user/appdata/parakeet-redux` after verifying
that path. Keeping appdata keeps the model for reinstall. Do not remove shared
images or change HA pipelines as part of this rollback.

## Development and tests

Python 3.12 (Wyoming's audioop dependency is deprecated in newer Python):

```sh
python -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements.lock
pip install pytest==9.1.1 pytest-asyncio==1.4.1 -r benchmarks/requirements.txt
python -m pytest -q
docker build -t parakeet-redux:test .
```

Docker builds run five native C++ checks, including ternary kernels, and CI
runs Python API/protocol/worker tests before publication. Native model inference
must additionally be tested on the target hardware. `v*` tags publish the matching
version to GHCR; main publishes `edge` (not recommended for stable deployment).
Measured comparison: [benchmark results](benchmarks/RESULTS.md),
[method and reproduction](benchmarks/README.md), and [raw results](benchmarks/results/).
In this two-thread CPU deployment, GPU Whisper was faster and more accurate on
these synthetic German recordings. Synthetic TTS tests are not evidence of real
microphone, dialect or everyday performance.
