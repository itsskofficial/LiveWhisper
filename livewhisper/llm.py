"""The built-in language model runner: llama.cpp's server, shipped with the app.

Formatting and Ctrl+Alt+W need a small language model. They used to need
Ollama, a separate install that a user of a desktop app should not have to know
about. This runs llama.cpp's `llama-server` (vendor/llama, MIT) on demand
instead, on a private port, with no window.

    formatter   a 0.6B model, kept loaded: it runs on every dictation and must
                answer in a couple of hundred milliseconds
    writer      a larger model for composing, unloaded as soon as it has
                written, so it never holds the GPU memory dictation needs (see
                providers.Ollama.keep_alive for what happened when it did)

The Vulkan build runs on NVIDIA, AMD and Intel GPUs and falls back to the CPU.
Every server is put in a Windows job object that kills it when the app exits,
however the app exits, so none is ever left running in the background.
"""

from __future__ import annotations

import ctypes
import json
import logging
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

RUNTIME = paths.BUNDLE / "vendor" / "llama"
SERVER = RUNTIME / "llama-server.exe"


@dataclass(frozen=True)
class GGUF:
    role: str
    repo: str
    file: str
    size_gb: float
    ctx: int
    label: str

    @property
    def path(self) -> Path:
        return paths.LLM / self.file

    def downloaded(self) -> bool:
        return self.path.exists()


# The formatter was chosen in tests/bench_format_llm.py (qwen3:0.6b: 67% of
# cases exactly right against 40% for rules alone). That was Ollama's 4-bit
# build; Qwen publishes only the 8-bit one, which loses less to quantisation.
FORMATTER = GGUF("formatter", "Qwen/Qwen3-0.6B-GGUF", "Qwen3-0.6B-Q8_0.gguf", 0.64,
                 2048, "Formatting model")
# Composing reads up to 6000 characters of screen, hence the larger context.
WRITER = GGUF("writer", "Qwen/Qwen2.5-3B-Instruct-GGUF",
              "qwen2.5-3b-instruct-q4_k_m.gguf", 2.1, 4096, "Writing model")
MODELS = {m.role: m for m in (FORMATTER, WRITER)}


class LLMError(RuntimeError):
    pass


def runtime_available() -> bool:
    return SERVER.exists()


# ------------------------------------------------------------ job object

_job = None


def _kill_with_app(proc: subprocess.Popen) -> None:
    """Tie the server's life to ours: closing our last handle kills it."""
    global _job
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.OpenProcess.restype = ctypes.c_void_p
        if _job is None:
            job = k32.CreateJobObjectW(None, None)

            class LIMITS(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                            ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", ctypes.c_uint32),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", ctypes.c_uint32),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", ctypes.c_uint32),
                            ("SchedulingClass", ctypes.c_uint32)]

            class IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in
                            ("r", "w", "o", "rb", "wb", "ob")]

            class EXTENDED(ctypes.Structure):
                _fields_ = [("Basic", LIMITS), ("Io", IO),
                            ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            info = EXTENDED()
            info.Basic.LimitFlags = 0x2000          # KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(info),
                                        ctypes.sizeof(info))
            _job = job
        handle = k32.OpenProcess(0x0001 | 0x0100, False, proc.pid)  # TERMINATE|SET_QUOTA
        k32.AssignProcessToJobObject(ctypes.c_void_p(_job), ctypes.c_void_p(handle))
        k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        log.debug("could not tie the model server to the app", exc_info=True)


# ------------------------------------------------------------ the device

_device: tuple | None = None


def pick_device() -> tuple:
    """(flags, description) for the best GPU, or the CPU.

    Laptops list the integrated GPU first; it reports shared system memory as
    its own and would run the model several times slower than the discrete one.
    """
    global _device
    if _device is not None:
        return _device
    _device = ([], "CPU")
    if not runtime_available():
        return _device
    try:
        proc = _spawn([str(SERVER), "--list-devices"], stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
        t0 = time.monotonic()
        out = proc.communicate(timeout=30)[0]
        log.debug("device list in %.1f s: %s", time.monotonic() - t0, out[-400:])
    except (OSError, subprocess.SubprocessError):
        log.warning("could not list GPUs for the model runner", exc_info=True)
        return _device
    devices = re.findall(r"^\s*(Vulkan\d+):\s*(.+?)\s*\((\d+) MiB", out, re.M)

    def rank(d):
        name = d[1].lower()
        discrete = any(k in name for k in ("nvidia", "geforce", "rtx", "radeon rx",
                                           "arc a", "arc b", "quadro"))
        integrated = any(k in name for k in ("(tm) graphics", "uhd", "iris",
                                             "radeon graphics", "radeon(tm) graphics"))
        return (discrete, not integrated, int(d[2]))

    if devices:
        best = max(devices, key=rank)
        if int(best[2]) >= 1500:
            _device = (["--device", best[0], "-ngl", "99"], best[1])
    log.info("language model device: %s", _device[1])
    return _device


_NO_WINDOW = 0x08000000


def _spawn(cmd: list, **kw) -> subprocess.Popen:
    """Start a runner process with the normal DLL search path.

    The installed app's bootloader points the DLL search at its own folder,
    and child processes inherit that: llama-server then loaded the wrong copy
    of its libraries and silently ran on the CPU.
    """
    k32 = ctypes.windll.kernel32
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        k32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen(cmd, creationflags=_NO_WINDOW, cwd=str(RUNTIME), **kw)
    finally:
        if bundle:
            k32.SetDllDirectoryW(bundle)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------ the server

class Server:
    """One llama-server with one model, started on first use."""

    def __init__(self, model: GGUF):
        self.model = model
        self._proc: subprocess.Popen | None = None
        self._port = 0
        self._lock = threading.Lock()
        self.last_used = 0.0

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def available(self) -> bool:
        return runtime_available() and self.model.downloaded()

    def start(self, timeout: float = 90.0) -> None:
        with self._lock:
            if self.running:
                return
            if not self.available():
                raise LLMError(f"{self.model.label} is not downloaded")
            flags, where = pick_device()
            self._port = _free_port()
            cmd = [str(SERVER), "-m", str(self.model.path), "--host", "127.0.0.1",
                   "--port", str(self._port), "-c", str(self.model.ctx),
                   "--parallel", "1", "--no-webui", *flags]
            log.info("starting %s on %s", self.model.file, where)
            log_path = paths.LLM / f"{self.model.role}-server.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            out = open(log_path, "w", encoding="utf-8", errors="replace")
            try:
                self._proc = _spawn(cmd, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL)
            except OSError as e:
                out.close()
                raise LLMError(f"could not start the model runner: {e}") from e
            _kill_with_app(self._proc)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    raise LLMError(f"the model runner exited (see {log_path})")
                try:
                    with urllib.request.urlopen(f"{self.url}/health", timeout=2) as r:
                        if r.status == 200:
                            return
                except (urllib.error.URLError, OSError):
                    pass
                time.sleep(0.15)
            self.stop()
            raise LLMError("the model runner did not start in time")

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    self._proc.wait(5)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def chat(self, messages: list, max_tokens: int = 1024, temperature: float = 0.3,
             timeout: float = 120.0, seed: int | None = None) -> str:
        self.start()
        payload = {"messages": messages, "max_tokens": max_tokens,
                   "temperature": temperature, "stream": False,
                   # Qwen3 reasons out loud unless told not to: seconds of
                   # waiting, and the reasoning can leak into the pasted text.
                   "chat_template_kwargs": {"enable_thinking": False}}
        if seed is not None:
            payload["seed"] = seed
        req = urllib.request.Request(f"{self.url}/v1/chat/completions",
                                     data=json.dumps(payload).encode("utf-8"),
                                     method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise LLMError(f"{e.code}: {e.read()[:300].decode('utf-8', 'replace')}") from e
        except Exception as e:
            raise LLMError(str(e)) from e
        finally:
            self.last_used = time.monotonic()
        text = out["choices"][0]["message"].get("content") or ""
        return re.sub(r"(?s)<think>.*?</think>", "", text).strip()


_servers: dict = {}
_servers_lock = threading.Lock()


def server(role: str) -> Server:
    with _servers_lock:
        if role not in _servers:
            _servers[role] = Server(MODELS[role])
        return _servers[role]


def shutdown() -> None:
    for s in list(_servers.values()):
        s.stop()

