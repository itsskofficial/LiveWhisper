"""Make the pip-installed CUDA runtime DLLs discoverable on Windows.

`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` drops its DLLs into
site-packages/nvidia/*/bin, which is not on the DLL search path. CTranslate2
(under faster-whisper) then fails with "Could not locate cudnn_ops64_9.dll" and
the usual advice is a manual CUDA Toolkit install. Registering the directories
here avoids all of that.

Must run before faster_whisper is imported.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def register() -> list[Path]:
    if sys.platform != "win32":
        return []
    registered = []
    # The installed app downloads cuBLAS itself (livewhisper.components).
    from . import paths
    if (paths.CUDA / "cublas64_12.dll").exists():
        try:
            os.add_dll_directory(str(paths.CUDA))
            registered.append(paths.CUDA)
        except OSError:
            log.debug("could not register %s", paths.CUDA, exc_info=True)
    try:
        import nvidia
    except ImportError:
        nvidia = None

    for base in (nvidia.__path__ if nvidia else []):
        for lib in Path(base).iterdir():
            bin_dir = lib / "bin"
            if not bin_dir.is_dir():
                continue
            try:
                os.add_dll_directory(str(bin_dir))
                registered.append(bin_dir)
            except OSError:
                log.debug("could not register %s", bin_dir, exc_info=True)

    if registered:
        # CTranslate2 resolves some libraries through PATH rather than the
        # per-process DLL directory list, so mirror them there too.
        os.environ["PATH"] = os.pathsep.join(
            [str(p) for p in registered] + [os.environ.get("PATH", "")]
        )
        log.debug("registered %d CUDA lib dirs", len(registered))
    return registered


def cublas_available() -> bool:
    """Can CTranslate2 actually run on the GPU here?

    It needs cuBLAS, and only finds out on the first real decode: a model loads
    "on cuda" without it, and a warm-up on silence never reaches the GPU, so
    the failure used to arrive as a failed dictation. The installed app
    downloads cuBLAS on first launch (livewhisper.components); until it has,
    or on a machine where it could not, the processor is used instead.
    """
    if sys.platform != "win32":
        return True
    register()
    import ctypes
    try:
        ctypes.WinDLL("cublas64_12.dll")
        ctypes.WinDLL("cublasLt64_12.dll")
        return True
    except OSError:
        return False
