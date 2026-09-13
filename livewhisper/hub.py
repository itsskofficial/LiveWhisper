"""Downloads from Hugging Face that do not hang.

huggingface_hub prefers its "xet" transfer backend when the hf_xet package is
installed. In testing here that backend stalled silently on multi-gigabyte
files: the progress bar froze, the process sat at zero CPU, and nothing grew on
disk for as long as it was left. Plain HTTP on the same connection ran at
~5 MB/s and resumed the partial file.

A frozen 3 GB download during install is the worst first impression the app can
make, so every download goes through `plain_http()` first.

The library reads its setting at import, but checks `constants.HF_HUB_DISABLE_XET`
again on each download - so flipping the constant works even when faster-whisper
imported huggingface_hub long before this runs. The environment variable is set
too, for any child process.
"""

from __future__ import annotations

import os


def plain_http() -> None:
    """Make subsequent Hugging Face downloads use plain HTTP."""
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    try:
        from huggingface_hub import constants
        constants.HF_HUB_DISABLE_XET = True
    except Exception:
        pass
