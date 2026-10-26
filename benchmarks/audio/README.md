# Synthetic benchmark fixtures

All speech here was generated for this project, not recorded from a real user.
Names, places and commands are generic fictional test content. No personal or
home-configuration information is present. Audio is shared for reproducibility
under CC0-1.0: https://creativecommons.org/publicdomain/zero/1.0/ .

Generation: Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice, GGML backend, voice sohee,
language german, seed 0, temperature 0.1, top_p 0.3, top_k 150,
repetition_penalty 1.3, do_sample true, max_new_tokens 4096,
non_streaming_mode false, streaming_chunk_size 120, token_safety_margin 8,
max_segment_chars 500, segment_pause_ms 120. Existing TTS global settings were
not changed. All audio was generated before timed recognition runs.

`manifest.json` records original requested TTS text, WAV hashes, duration and
conditions. Requested text is NOT automatically guaranteed to equal spoken
speech; acoustic validation and ambiguities must be reported separately.
`audit-video.mp4` is a black-picture compilation of only the 14 clean clips,
separated by one second of silence, for independent acoustic review. It is
AAC-encoded for review only; benchmarks use the exact PCM WAV files.
`audit-boundaries.json` gives the clip positions in that compilation.

Noise is deterministic, generated pink-ish stationary noise (seed 20261026).
The SNR reference is the RMS of speech samples with absolute level >0.01,
not a standardized active-speech measurement. Noise conditions are not a
substitute for real room recordings, reverberation or competing speakers.
