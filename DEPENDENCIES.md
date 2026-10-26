# Pinned build inputs (0.1.1)

- Python base image: exact digest in Dockerfile (both stages).
- Debian and Debian-security: **20261026T000000Z** snapshots, with normal Debian
  signature validation. `Check-Valid-Until: no` only permits intentional historical
  metadata; it does not disable cryptographic signature checking.
- Only the checked-in snapshot source file is permitted. Build aborts if another
  apt source file or the legacy sources.list exists.
- Direct apt installs use exact versions:
  - build-essential `12.9`
  - cmake `3.25.1-1`
  - git `1:2.39.5-0+deb12u3`
  - curl `7.88.1-10+deb12u15`
  - ca-certificates `20250419~deb12u2`
  - ffmpeg `7:5.1.9-0+deb12u1`
  - libgomp1 `12.2.0-14+deb12u1`
- Transitive apt dependency resolution is confined to the same immutable snapshot,
  not moving Bookworm/Security repositories. Installed build/runtime package
  manifests are emitted into `/opt/licenses/build-packages.txt` and
  `/opt/licenses/runtime-packages.txt` in every image.
- Python runtime: exact versions and wheel hashes in `requirements.lock`.
- parakeet.cpp / ggml source commits, model revision and SHA-256: [NOTICE](NOTICE.md).
- No Photon runtime or proprietary kestrel kernels are included.

Changes require deliberately bumping the base digest/snapshot/package version,
regenerating applicable locks, testing, and publishing a new image version.
The snapshot also freezes security fixes: do not interpret it as automatic
security maintenance. This pins inputs and dependency resolution, not incidental
build timestamps or OCI metadata; no bit-for-bit image-rebuild claim is made.

Version 0.1.0 is retained as the initial benchmarked release but used moving apt
sources. Version 0.1.1 corrects that gap without changing ASR model, decoding,
thread defaults, protocol or port defaults.
