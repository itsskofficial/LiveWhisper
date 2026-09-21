"""Everything the app downloads after it is installed, with progress.

The installer carries the app. The large, machine-specific parts come down
from inside the app, on first launch or when a language is added:

    gpu        NVIDIA's cuBLAS, which CTranslate2 needs to run Whisper on the
               GPU. Only two files, lifted out of NVIDIA's own package on PyPI
               with HTTP range requests - 550 MB instead of the 1.3 GB the
               cuBLAS and cuDNN packages weigh together. cuDNN is not needed:
               measured in an environment without PyTorch (which otherwise
               supplies it unnoticed), Whisper never loads it.
    speech     the main Whisper model this machine should run
    lang:xx    a language's specialist model (livewhisper.specialists)
    formatter  the small model that punctuates dictation
    writer     the model behind Ctrl+Alt+W

Downloads resume where they stopped, go one at a time, and land in a temporary
name that is renamed only once complete, so a half-download never looks like a
model. Status is polled by the app window.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import struct
import threading
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import requests

from . import hardware, llm, paths, specialists

log = logging.getLogger(__name__)

CHUNK = 1 << 20
UA = {"User-Agent": "LiveWhisper"}

CUBLAS_WHEEL = ("nvidia-cublas-cu12", "12.9.2.10")
CUBLAS_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll")


class Cancelled(Exception):
    pass


@dataclass
class Component:
    id: str
    name: str
    detail: str
    size_mb: int
    group: str                          # essentials | language | ai
    installed: bool = False
    recommended: bool = False
    state: str = "idle"                 # idle | queued | downloading | error
    done: int = 0
    total: int = 0
    error: str = ""
    extra: dict = field(default_factory=dict)

    def view(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "extra"}
        d.update(self.extra)
        return d


# ---------------------------------------------------------------- fetching

def _fetch(url: str, dest: Path, report, cancelled, expected: int = 0) -> None:
    """Stream url to dest, resuming a partial .part file."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    with requests.get(url, headers=headers, stream=True, timeout=30,
                      allow_redirects=True) as r:
        if r.status_code == 416:            # already complete
            part.replace(dest)
            return
        r.raise_for_status()
        if have and r.status_code != 206:   # server ignored the range
            have = 0
        mode = "ab" if have else "wb"
        with open(part, mode) as f:
            for chunk in r.iter_content(CHUNK):
                if cancelled():
                    raise Cancelled
                f.write(chunk)
                report(len(chunk))
    if expected and part.stat().st_size != expected:
        raise IOError(f"{dest.name}: got {part.stat().st_size} bytes, expected {expected}")
    part.replace(dest)


def _hf_files(repo: str, patterns=None) -> list:
    """[(filename, size)] for a Hugging Face repo."""
    from huggingface_hub import HfApi
    info = HfApi().model_info(repo, files_metadata=True)
    out = []
    for s in info.siblings:
        if patterns and s.rfilename not in patterns:
            continue
        out.append((s.rfilename, s.size or 0))
    return out


def _hf_url(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"


class _RangeFile(io.RawIOBase):
    """A remote file, read with HTTP range requests - enough for zipfile to
    read a wheel's directory without downloading the wheel."""

    def __init__(self, url: str):
        self.url = url
        head = requests.head(url, headers=UA, allow_redirects=True, timeout=30)
        head.raise_for_status()
        self.url = head.url
        self.size = int(head.headers["Content-Length"])
        self.pos = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.size, self.pos + n) - 1
        r = requests.get(self.url, headers={**UA, "Range": f"bytes={self.pos}-{end}"},
                         timeout=60)
        r.raise_for_status()
        self.pos += len(r.content)
        return r.content

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def _wheel_url(package: str, version: str) -> str:
    j = requests.get(f"https://pypi.org/pypi/{package}/{version}/json", headers=UA,
                     timeout=30).json()
    for u in j["urls"]:
        if u["filename"].endswith("win_amd64.whl"):
            return u["url"]
    raise IOError(f"no Windows build of {package} {version}")


def _zip_members(url: str, names) -> list:
    """[(ZipInfo, data_offset)] for the members of a remote zip we want."""
    rf = _RangeFile(url)
    z = zipfile.ZipFile(io.BufferedReader(rf, buffer_size=1 << 16))
    out = []
    for info in z.infolist():
        if Path(info.filename).name in names:
            rf.seek(info.header_offset)
            header = rf.read(30)
            name_len, extra_len = struct.unpack("<HH", header[26:30])
            out.append((info, info.header_offset + 30 + name_len + extra_len))
    return out, rf.url


def _fetch_member(url: str, info, offset: int, dest: Path, report, cancelled) -> None:
    """Stream one deflated zip member straight to disk."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    end = offset + info.compress_size - 1
    d = zlib.decompressobj(-15) if info.compress_type == zipfile.ZIP_DEFLATED else None
    crc = 0
    try:
        with requests.get(url, headers={**UA, "Range": f"bytes={offset}-{end}"},
                          stream=True, timeout=60) as r, open(part, "wb") as f:
            r.raise_for_status()
            for chunk in r.iter_content(CHUNK):
                if cancelled():
                    raise Cancelled
                data = d.decompress(chunk) if d else chunk
                crc = zlib.crc32(data, crc)
                f.write(data)
                report(len(chunk))
            if d:
                tail = d.flush()
                crc = zlib.crc32(tail, crc)
                f.write(tail)
    except zlib.error:
        crc = None                          # damaged beyond decompressing
    if crc != info.CRC:
        part.unlink(missing_ok=True)
        raise IOError(f"{dest.name} was corrupted in transit; try again")
    part.replace(dest)


# ---------------------------------------------------------------- manager

class Components:
    def __init__(self, app=None):
        self.app = app
        self._lock = threading.Lock()
        self._queue: list = []
        self._cancel: set = set()
        self._items: dict = {}
        self._worker: threading.Thread | None = None
        self.machine = hardware.detect()
        self.nvidia = bool(self.machine.gpu) and "nvidia" in (self.machine.gpu or "").lower()

    # -- what exists ------------------------------------------------------

    def _cfg(self) -> dict:
        from . import config as cfgio
        if self.app is not None:
            return self.app.cfg
        return cfgio.load(paths.ensure_config())

    def speech_model(self) -> str:
        return (self._cfg().get("transcription", {}).get("local", {})
                .get("model") or hardware.recommend().model)

    def list(self) -> list:
        """Every component, in display order, with fresh install state."""
        with self._lock:
            items = self._describe()
            for i, c in enumerate(items):
                old = self._items.get(c.id)
                # The download worker holds the old object and keeps counting
                # into it, so an active or failed one stays as it is.
                if old is not None and old.state in ("queued", "downloading", "error"):
                    items[i] = old
                else:
                    self._items[c.id] = c
            return [c.view() for c in items]

    def _describe(self) -> list:
        from .transcribe import LocalBackend
        out = []
        cfg = self._cfg()
        local = cfg.get("transcription", {}).get("local", {})
        cpu = not self.nvidia
        if self.nvidia:
            out.append(Component(
                "gpu", "GPU acceleration",
                f"Runs speech recognition on your {self.machine.gpu}. "
                "Dictation is 5-10x faster than on the processor.",
                550, "essentials", installed=gpu_ready(), recommended=True))
        model = self.speech_model()
        out.append(Component(
            "speech", "Speech model",
            f"Whisper {model}: turns your voice into text, on this PC.",
            {"large-v3": 3100, "large-v3-turbo": 1620, "medium": 1530,
             "small": 490, "base": 150, "tiny": 80}.get(model, 3000),
            "essentials", installed=LocalBackend(dict(local)).is_downloaded(),
            recommended=True, extra={"model": model}))
        routes = local.get("models") or {}
        seen = set()
        for spec in specialists.CATALOGUE:
            if not spec.measured or spec.device != ("cpu" if cpu else "gpu"):
                continue
            cid = f"lang:{spec.lang}" + (":native" if spec.role == "native" else "")
            if cid in seen:
                continue
            seen.add(cid)
            route = routes.get(spec.lang)
            targets = [route] if isinstance(route, str) else \
                [(route or {}).get("path"), (route or {}).get("native")]
            installed = any(t and Path(t).name == spec.name and (Path(t) / "model.bin").exists()
                            for t in targets)
            size = int(spec.size_gb * 1000 / (2 if spec.kind == "convert" else 1))
            out.append(Component(
                cid, "English, faster" if cid == "lang:en" else spec.name, spec.note,
                size, "language", installed=installed, recommended=cid == "lang:en",
                extra={"lang": spec.lang, "role": spec.role,
                       "measured": spec.measured, "latin_output": spec.latin_output}))
        for m in llm.MODELS.values():
            out.append(Component(
                m.role, m.label,
                "Punctuation, lists and paragraphs as you speak - runs on this PC."
                if m.role == "formatter" else
                "Ctrl+Alt+W: say what you want written, get the finished text.",
                int(m.size_gb * 1000), "ai", installed=m.downloaded(),
                recommended=m.role == "formatter"))
        return out

    # -- downloading ------------------------------------------------------

    def start(self, cid: str) -> None:
        with self._lock:
            c = self._items.get(cid)
            if c is None or c.installed or c.state in ("queued", "downloading"):
                return
            c.state, c.error, c.done, c.total = "queued", "", 0, 0
            self._cancel.discard(cid)
            self._queue.append(cid)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="downloads",
                                                daemon=True)
                self._worker.start()

    def cancel(self, cid: str) -> None:
        with self._lock:
            self._cancel.add(cid)
            if cid in self._queue:
                self._queue.remove(cid)
                self._items[cid].state = "idle"

    def busy(self) -> bool:
        with self._lock:
            return any(c.state in ("queued", "downloading") for c in self._items.values())

    def _run(self) -> None:
        from .hub import plain_http
        plain_http()
        while True:
            with self._lock:
                if not self._queue:
                    return
                cid = self._queue.pop(0)
                c = self._items[cid]
                c.state = "downloading"
            try:
                self._install(c)
                with self._lock:
                    c.state, c.installed = "idle", True
                log.info("installed %s", cid)
                if self.app is not None:
                    self.app.component_installed(cid)
            except Cancelled:
                with self._lock:
                    c.state = "idle"
            except Exception as e:
                log.warning("download of %s failed", cid, exc_info=True)
                with self._lock:
                    c.state, c.error = "error", _friendly(e)

    def _reporter(self, c: Component):
        def report(n: int) -> None:
            c.done += n
        return report

    def _cancelled(self, c: Component):
        return lambda: c.id in self._cancel

    def _install(self, c: Component) -> None:
        report, cancelled = self._reporter(c), self._cancelled(c)
        if c.id == "gpu":
            members, url = _zip_members(_wheel_url(*CUBLAS_WHEEL), CUBLAS_DLLS)
            c.total = sum(i.compress_size for i, _ in members)
            for info, offset in members:
                _fetch_member(url, info, offset, paths.CUDA / Path(info.filename).name,
                              report, cancelled)
            from . import _cuda
            _cuda.register()
        elif c.id == "speech":
            from .transcribe import _repo_id
            model = c.extra["model"]
            self._fetch_repo(_repo_id(model), paths.MODELS / model, c,
                             specialists.CT2_FILES)
        elif c.id.startswith("lang:"):
            parts = c.id.split(":")
            spec = next(s for s in specialists.CATALOGUE
                        if s.lang == parts[1] and s.measured
                        and (s.role == "native") == (len(parts) > 2)
                        and s.device == ("gpu" if self.nvidia else "cpu"))
            out = specialists.models_dir(self._cfg()) / spec.name
            self._fetch_repo(spec.download_repo, out, c, specialists.CT2_FILES)
            specialists.register(spec, self.app.config_path if self.app else paths.ensure_config(),
                                 out)
        elif c.id in llm.MODELS:
            m = llm.MODELS[c.id]
            files = _hf_files(m.repo, [m.file])
            c.total = sum(s for _, s in files)
            _fetch(_hf_url(m.repo, m.file), m.path, report, cancelled, files[0][1])
        else:
            raise ValueError(f"unknown component {c.id}")

    def _fetch_repo(self, repo: str, out: Path, c: Component, patterns) -> None:
        files = _hf_files(repo, patterns)
        if not any(f == "model.bin" for f, _ in files):
            raise IOError(f"{repo} is not available yet")
        c.total = sum(s for _, s in files)
        tmp = out.with_name(out.name + ".download")
        for name, size in files:
            dest = tmp / name
            if dest.exists() and dest.stat().st_size == size:
                c.done += size
                continue
            _fetch(_hf_url(repo, name), dest, self._reporter(c), self._cancelled(c), size)
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)
        tmp.replace(out)


def gpu_ready() -> bool:
    """cuBLAS is where CTranslate2 will find it: the app's own download, or -
    in a source checkout - the pip package."""
    if all((paths.CUDA / n).exists() for n in CUBLAS_DLLS):
        return True
    try:
        import nvidia.cublas
        return any((Path(p) / "bin" / CUBLAS_DLLS[0]).exists()
                   for p in nvidia.cublas.__path__)
    except ImportError:
        return False


def _friendly(e: Exception) -> str:
    text = str(e)
    if isinstance(e, requests.ConnectionError) or "NameResolution" in text:
        return "No internet connection. It will resume where it stopped."
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "Not enough disk space."
    return text[:200]
