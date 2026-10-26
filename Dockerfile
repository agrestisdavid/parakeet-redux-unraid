FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS native
COPY debian.sources /etc/apt/sources.list.d/debian.sources
RUN test ! -f /etc/apt/sources.list && test "$(find /etc/apt/sources.list.d -type f | wc -l)" -eq 1 && apt-get -o Acquire::Retries=3 update && apt-get install -y --no-install-recommends build-essential=12.9 cmake=3.25.1-1 git=1:2.39.5-0+deb12u3 ca-certificates=20250419~deb12u2 curl=7.88.1-10+deb12u15 && rm -rf /var/lib/apt/lists/*
RUN git init /src && cd /src && git remote add origin https://github.com/mudler/parakeet.cpp.git && git fetch --depth 1 origin 43dce03cb3c36849d5e5a504076be3d9bea7b6c4 && git checkout FETCH_HEAD && git submodule update --init --depth 1 third_party/ggml
RUN cmake -S /src -B /src/build -DCMAKE_BUILD_TYPE=Release -DPARAKEET_SHARED=ON -DPARAKEET_BUILD_TESTS=ON -DPARAKEET_BUILD_SERVER=OFF -DPARAKEET_WITH_CED=OFF -DPARAKEET_WITH_VOICEDETECT=OFF -DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_AVX512=OFF -DGGML_AVX_VNNI=OFF -DPARAKEET_VERSION=43dce03 && cmake --build /src/build -j2
RUN ctest --test-dir /src/build --output-on-failure -R '^(test_smoke|test_audio_io|test_fft|test_ternary|test_vad_segmenter)$'
COPY native/thread_control.cpp /thread_control.cpp
RUN mkdir -p /opt/lib /opt/licenses && find /src/build -name '*.so*' -exec cp -P {} /opt/lib/ \; && g++ -shared -fPIC /thread_control.cpp -L/opt/lib -lparakeet -o /opt/lib/libredux_threads.so && cp /src/LICENSE /opt/licenses/parakeet.cpp.txt && cp /src/third_party/ggml/LICENSE /opt/licenses/ggml.txt && dpkg-query -W -f='${Package}=${Version}\n' > /opt/licenses/build-packages.txt

FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
LABEL org.opencontainers.image.source="https://github.com/agrestisdavid/parakeet-redux-unraid" \
      org.opencontainers.image.description="Moondream Parakeet Redux on CPU via parakeet.cpp, with HTTP and Wyoming" \
      org.opencontainers.image.licenses="MIT" org.opencontainers.image.version="0.1.1"
COPY debian.sources /etc/apt/sources.list.d/debian.sources
RUN test ! -f /etc/apt/sources.list && test "$(find /etc/apt/sources.list.d -type f | wc -l)" -eq 1 && apt-get -o Acquire::Retries=3 update && apt-get install -y --no-install-recommends ffmpeg=7:5.1.9-0+deb12u1 libgomp1=12.2.0-14+deb12u1 ca-certificates=20250419~deb12u2 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /opt/app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /opt/app/requirements.lock
COPY --from=native /opt/lib /opt/lib
COPY --from=native /opt/licenses /opt/licenses
COPY LICENSE NOTICE.md /opt/licenses/
RUN dpkg-query -W -f='${Package}=${Version}\n' > /opt/licenses/runtime-packages.txt
COPY redux /opt/app/redux
ENV LD_LIBRARY_PATH=/opt/lib PYTHONPATH=/opt/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MODEL_DIR=/data/models CPU_THREADS=2 MAX_AUDIO_SECONDS=180 INFERENCE_TIMEOUT=120 \
    HTTP_PORT=8080 WYOMING_PORT=10300 OMP_NUM_THREADS=2 OMP_WAIT_POLICY=PASSIVE PARAKEET_DEVICE=cpu HOME=/tmp
RUN mkdir -p /data/models && chown -R 99:100 /data
USER 99:100
WORKDIR /opt/app
EXPOSE 8080 10300
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('HTTP_PORT','8080')+'/health',timeout=3).read()"
CMD ["python", "-m", "redux.server"]
