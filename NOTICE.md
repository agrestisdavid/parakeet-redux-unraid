# Attribution and third-party software

This service is an independent integration, not an official Moondream, NVIDIA,
Unraid or Home Assistant product. Our Python wrapper and thread adapter are MIT.
That license does not relicense the model or OS packages.

## Model (downloaded separately, not embedded in the image)

- **Moondream Parakeet Redux**: https://huggingface.co/moondream/parakeet-redux
- Derived from NVIDIA `parakeet-tdt-0.6b-v3`: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- License: **CC BY 4.0**, https://creativecommons.org/licenses/by/4.0/
- GGUF conversion by the parakeet.cpp project (Ettore Di Giacinto and contributors):
  https://huggingface.co/mudler/parakeet-cpp-gguf
- We use `redux-packed.gguf`, converted with `--ternary keep`, not a newly trained
  model and not the original NVIDIA Parakeet in place of Redux. Format conversion
  and runtime numerics can affect transcripts; exact Photon equivalence is not claimed.
- Pinned GGUF revision: `c77726e46ceaab96b5a5a3328915edb44c73209d`
- SHA-256: `574614b9a4d9f72ab202877a7ad6a1f4bf819dd1d27b9d42dfe8cd429fcebdd5`

## Runtime

- parakeet.cpp: https://github.com/mudler/parakeet.cpp — MIT,
  commit `43dce03cb3c36849d5e5a504076be3d9bea7b6c4`.
- ggml: https://github.com/ggml-org/ggml — MIT,
  submodule `e705c5fed490514458bdd2eaddc43bd098fcce9b`.
- Their license texts are copied into `/opt/licenses` in the image. The upstream
  dr_wav header includes its MIT/public-domain notices in the pinned source.
- Python PSF, aiohttp Apache-2.0, Wyoming MIT, Debian and FFmpeg retain their own
  licenses. Debian package copyright texts remain in `/usr/share/doc`.
  FFmpeg is invoked as a separate executable, not linked into this wrapper;
  its version/configuration and corresponding Debian source packages can be
  obtained with `ffmpeg -version`, `dpkg-query -W`, and Debian's source archive.
- **No Photon, kestrel or proprietary Moondream runtime kernels are bundled.**

A small standalone adapter calls parakeet.cpp's internal thread setter because
its single-backend public C API does not apply `threads_each`. The native source
is pinned, and this adapter must be re-tested when upgrading it.
