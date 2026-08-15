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
    try:
        import nvidia
    except ImportError:
        return []

    registered = []
    for base in nvidia.__path__:
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
