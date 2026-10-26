# Final synthetic corpus (v2)

All audio is synthetic, generated for this project, and shared under CC0-1.0:
https://creativecommons.org/publicdomain/zero/1.0/ . No user microphone recordings,
private home names or internal server information are present.

Compared with `../audio/`, exactly two clean recordings were repaired before the
final comparison: `cmd05` uses Serena instead of Sohee (clearer pronunciation of
Rollläden); `long02` uses a 250-character TTS segment size instead of 500 so that
a previously skipped sentence is actually spoken. Both were independently checked
by a local Whisper-small decoder before final timed runs. Other clean recordings
are byte-identical. Noise was recreated deterministically; its source clips did
not change. See `../README.md` for settings, corrections and acoustic-audit limits.

`manifest.json` records references, conditions, byte hashes and any per-clip TTS
options. Signal and automatic ASR checks do not substitute for a human listening
test. Final raw results and audit transcripts are in `../results/`.
