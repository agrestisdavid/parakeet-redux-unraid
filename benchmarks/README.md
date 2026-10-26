# Reproducing the comparison

See [RESULTS.md](RESULTS.md) for the measured, bounded conclusion. The primary
comparison uses **v2**, not the initial TTS pilot.

## Data and scripts

- `corpus.json`, `audio/`: original requested text, generated WAVs and pilot corpus.
- `corpus-v2.json`, `audio-v2/`: final corpus. Two documented TTS repairs; all other
  clean clips are byte-identical to the pilot.
- `results/`: raw final HTTP/paced-Wyoming results, summaries, per-clip outputs and
  automated acoustic audit. No internal endpoints or server identifiers.
- `results/pilot-*`: initial observations retained to make the reference correction
  transparent, **not** used for the main quality comparison.
- `run.py`: generate with Qwen3-TTS, create reproducible noise, run paired tests.
- `analyze.py`: German number/time/percent normalization, word/character Levenshtein
  distance, exact-match and required-slot checks. Whitespace and punctuation are
  normalized, case ignored, `ß` maps to `ss`. Numbers and percent signs expand to
  spoken German. Compounds are **not** heuristically merged. CER excludes spaces.

Use Python 3.12 with the project's runtime lock plus `benchmarks/requirements.txt`.
A recognizer's `whisper-1` compatibility alias is used on both HTTP endpoints.
Both receive exactly the same PCM WAVs. `language=de` forces the existing Whisper
but is only validated by Redux, whose language detection is automatic.

```sh
python benchmarks/run.py generate --corpus benchmarks/corpus-v2.json \
  --tts "${TTS_URL}" --output benchmark-output
python benchmarks/run.py variants --output benchmark-output
# Audit that TTS actually spoke the requested text BEFORE timing/quality scoring.
python benchmarks/run.py run --redux "${REDUX_URL}" --whisper "${WHISPER_URL}" \
  --mode http --output benchmark-output
python benchmarks/run.py run --redux "${REDUX_URL}" --whisper "${WHISPER_URL}" \
  --host "${SERVER_HOST}" --redux-port 10330 --whisper-port 10310 \
  --mode realtime --output benchmark-output
python benchmarks/analyze.py benchmark-output
```

To repeat with the exact published WAVs rather than regenerating them, copy
`audio-v2/` into `benchmark-output/` first, and skip generation/variants.
The run script refuses to overwrite a result file. Use another directory for a
new experiment. Regenerating TTS may produce different audio even with a seed;
SHA-256 hashes identify the fixtures actually evaluated.

## Acoustic reference check

The pilot showed a whole missing sentence in `long02` in both engines. A third,
local **Whisper small / whisper.cpp b5454** CPU recognizer independently confirmed
that omission without being given reference text. Regenerating with a 250-character
TTS segment size (instead of 500) restored the sentence. Sohee's `cmd05` rendition
of “Rollläden” was ambiguous to all three recognizers; seed 1 did not solve it.
That clip was regenerated with **Serena**. All other final clips use **Sohee**.
No global TTS configuration or model was changed.

The third recognizer checked all 14 final clean clips: 13 matched the normalized
reference exactly; in `dict01` it spelled “ändere” as “endere” (one character),
while both benchmark systems returned “ändere”. Signal RMS, duration and clipping
were checked, and raw audit transcripts are retained. This is an **automated
acoustic/reference check, not a human hearing test**. The reference selection can
still favor Whisper-family recognizers; no broad German accuracy claim follows.
The pilot remains available and is not silently rewritten.

## Method limits

- 14 clean + 8 noise variants + 1 silence control; three repeats per engine.
  Repeats do not create more independent speech samples.
- HTTP: pre-uploaded/file processing measured from request start through complete
  response. Warmup separately recorded. Native Redux timing is also returned but
  not compared to Whisper network timing.
- Paced Wyoming: six short commands, 100 ms audio chunks released only when those
  samples would exist in real capture, then `audio-stop`. Measure post-audio final
  transcript latency separately from audio duration. No microphone, HA VAD,
  network satellite, LLM or TTS reply time is included.
- Endpoint order and clip order are deterministically shuffled (seed 20261026).
  Requests are sequential; TTS generation finishes before ASR timing starts.
- A shared host remains under normal unrelated load; no production service was
  stopped to create an idle benchmark. This is deployment behavior, not a hardware
  maximum. CPU inference uses only two physical cores / two threads and a 2-CPU quota.
- p95 is omitted below 40 observations. Even where present, it describes this
  mixture of clip lengths, not an independently estimated population percentile.
- `slots_correct` checks whole normalized expected phrases. It is **not** an HA
  intent/action execution test; no home devices were controlled.
- All zero-audio silence control runs bypass HA's VAD intentionally and are excluded
  from WER/CER. Noise is synthetic stationary noise, not real competing speech.
- A separate, operator-approved maintenance follow-up now measures both systems'
  process-cold restart-to-first-transcript latency: three final cycles per system,
  followed by three warm requests each, same `cmd01` WAV and Docker-host client.
  Model/disk and OS caches were retained. Whisper's `describe` readiness is not
  assumed to mean fully loaded weights. See RESULTS.md for inclusive timings,
  limitations and the repeated preliminary series caused by a mount-order guard
  false positive. Only Whisper was restarted during its approved maintenance;
  its config/image/model/ports and all other protected services stayed unchanged.
