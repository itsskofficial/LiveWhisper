#!/usr/bin/env python
"""Regenerate assets/livewhisper.ico and .png from livewhisper.icons.

    python assets/make_icons.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import icons  # noqa: E402

if __name__ == "__main__":
    path = icons.write_ico()
    print(f"wrote {path}")
    print(f"wrote {path.with_suffix('.png')}")
