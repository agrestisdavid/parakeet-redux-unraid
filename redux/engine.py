"""One isolated, persistent CPU model; kill/reload only this worker on failure."""
import asyncio
import ctypes as C
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import time
import urllib.request

MODEL_SHA256 = "574614b9a4d9f72ab202877a7ad6a1f4bf819dd1d27b9d42dfe8cd429fcebdd5"
MODEL_REVISION = "c77726e46ceaab96b5a5a3328915edb44c73209d"
MODEL_URL = f"https://huggingface.co/mudler/parakeet-cpp-gguf/resolve/{MODEL_REVISION}/redux-packed.gguf"
MODEL_BYTES = 213319296


def ensure_model(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temp = path.with_suffix('.download')
        try:
            with urllib.request.urlopen(MODEL_URL, timeout=60) as response, temp.open('wb') as out:
                count = 0
                while data := response.read(1024 * 1024):
                    count += len(data)
                    if count > MODEL_BYTES:
                        raise RuntimeError('Model download exceeds expected size')
                    out.write(data)
            verify_model(temp)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    verify_model(path)


def verify_model(path):
    with Path(path).open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    if digest != MODEL_SHA256:
        raise RuntimeError('Model SHA256 mismatch: remove the invalid cache file manually')


def worker(conn, model_path, library, threads):
    ctx = None
    lib = None
    try:
        # No CUDA/Vulkan/Metal libraries are compiled into our image.
        lib = C.CDLL(library)
        for name, args, result in [
            ('parakeet_capi_load', [C.c_char_p], C.c_void_p),
            ('parakeet_capi_load_error', [], C.c_char_p),
            ('parakeet_capi_last_error', [C.c_void_p], C.c_char_p),
            ('parakeet_capi_free', [C.c_void_p], None),
            ('parakeet_capi_free_string', [C.c_void_p], None),
            ('parakeet_capi_set_concurrency', [C.c_void_p, C.c_int, C.c_int], C.c_int),
            ('parakeet_capi_transcribe_path_json_vad', [C.c_void_p, C.c_char_p, C.c_int], C.c_void_p),
        ]:
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, result
        shim = C.CDLL(str(Path(library).with_name('libredux_threads.so')))
        shim.redux_set_threads.argtypes = [C.c_int]
        shim.redux_set_threads.restype = None
        shim.redux_set_threads(threads)
        ctx = lib.parakeet_capi_load(os.fsencode(model_path))
        if not ctx:
            raise RuntimeError(lib.parakeet_capi_load_error().decode())
        if lib.parakeet_capi_set_concurrency(ctx, 1, threads) != 1:
            raise RuntimeError('Could not configure CPU thread budget')
        conn.send({'ready': True})
        while path := conn.recv():
            started = time.monotonic()
            ptr = lib.parakeet_capi_transcribe_path_json_vad(ctx, os.fsencode(path), 0)
            if not ptr:
                raise RuntimeError(lib.parakeet_capi_last_error(ctx).decode())
            try:
                result = json.loads(C.string_at(ptr))
            finally:
                lib.parakeet_capi_free_string(ptr)
            conn.send({'result': result, 'inference_seconds': time.monotonic() - started})
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            conn.send({'error': str(exc)})
        except (BrokenPipeError, OSError):
            pass
    finally:
        if ctx:
            lib.parakeet_capi_free(ctx)
        conn.close()


class Engine:
    def __init__(self, model_path, threads=2, timeout=120, library='/opt/lib/libparakeet.so', target=worker):
        self.model_path, self.threads, self.timeout = str(model_path), threads, timeout
        self.library, self.target = library, target
        self.proc = self.conn = None
        self.ready = False
        self.lock = asyncio.Lock()
        self.recovery = None
        self.closed = False

    async def start(self):
        ctx = mp.get_context('spawn')
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=self.target, args=(child, self.model_path, self.library, self.threads), daemon=True)
        self.proc.start()
        child.close()
        try:
            message = await self.receive(120)
            if not message.get('ready'):
                raise RuntimeError(message.get('error', 'Worker failed to initialize'))
            self.ready = True
        except BaseException:
            self.stop_worker()
            raise

    async def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.conn.poll():
                return self.conn.recv()
            if not self.proc.is_alive():
                raise RuntimeError('Inference worker exited')
            await asyncio.sleep(0.01)
        raise TimeoutError('Inference worker timeout')

    async def transcribe(self, path):
        if not self.ready:
            raise RuntimeError('Model not ready')
        # No await between checking and acquiring the uncontended lock.
        if self.lock.locked():
            raise BlockingIOError('Inference busy; retry after the current utterance')
        async with self.lock:
            try:
                self.conn.send(str(path))
                message = await self.receive(self.timeout)
                if 'error' in message:
                    raise RuntimeError(message['error'])
                return message
            except BaseException:
                self.stop_worker()
                if not self.closed:
                    self.recovery = asyncio.create_task(self.recover())
                raise

    async def recover(self):
        try:
            await self.start()
        except Exception:
            # Failed healthcheck lets the operator see a durable failure.
            self.ready = False

    def stop_worker(self):
        self.ready = False
        if self.proc:
            if self.proc.is_alive():
                self.proc.terminate()
            self.proc.join(timeout=2)
            if self.proc.is_alive():
                self.proc.kill()
                self.proc.join(timeout=2)
            self.proc.close()
            self.proc = None
        if self.conn:
            self.conn.close()
            self.conn = None

    async def close(self):
        self.closed = True
        if self.recovery and not self.recovery.done():
            self.recovery.cancel()
            await asyncio.gather(self.recovery, return_exceptions=True)
        self.stop_worker()
