#!/usr/bin/env python
"""Export the transliteration checkpoint to a torch-free numpy archive.

    python tools/export_translit.py [checkpoint.pt] [out.npz]

The app runs the model in pure numpy (livewhisper/script/oov.py) so the
packaged exe does not need PyTorch, which would add over a gigabyte for a
2.56M-parameter model. Training still uses torch; this is the one-way bridge.

Every state-dict tensor is stored as float32 under its own key. The vocabularies,
language list and architecture go in as JSON strings in 0-d unicode arrays, so
the archive loads with allow_pickle=False - an .npz that needs pickle can run
arbitrary code on load, which is exactly what we are avoiding by leaving .pt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.script.oov import (  # noqa: E402
    DATA, LEGACY_CHECKPOINT, MULTI_CHECKPOINT, NPZ_CHECKPOINT, _architecture)


def export(src: Path, dst: Path) -> None:
    import torch

    ck = torch.load(src, map_location="cpu", weights_only=False)
    arrays = {k: v.detach().cpu().numpy().astype(np.float32)
              for k, v in ck["model"].items()}
    arch = ck.get("arch") or _architecture(ck["model"])
    # An empty language list marks the legacy hindi-only model; keep that
    # distinction rather than inventing ["hi"], so .multilingual stays false.
    meta = {
        "src_itos": list(ck["src_itos"]),
        "tgt_itos": list(ck["tgt_itos"]),
        "languages": list(ck.get("languages") or []),
        "arch": {k: int(arch[k]) for k in ("d", "ff", "layers", "heads")},
    }
    for k, v in meta.items():
        arrays[f"meta.{k}"] = np.array(json.dumps(v, ensure_ascii=False))
    np.savez_compressed(dst, **arrays)

    # Prove it round-trips without pickle before anyone relies on it.
    with np.load(dst, allow_pickle=False) as z:
        assert json.loads(str(z["meta.src_itos"])) == meta["src_itos"]
        for k, v in ck["model"].items():
            assert np.array_equal(z[k], v.numpy()), k
    n = sum(a.size for k, a in arrays.items() if not k.startswith("meta."))
    print(f"{src.name} -> {dst}  ({n:,} params, {dst.stat().st_size / 1e6:.1f} MB, "
          f"arch {meta['arch']}, {len(meta['languages']) or 'hindi-only'} languages)")


def main() -> int:
    default = MULTI_CHECKPOINT if MULTI_CHECKPOINT.exists() else LEGACY_CHECKPOINT
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else NPZ_CHECKPOINT
    if not src.exists():
        print(f"no checkpoint at {src} (looked in {DATA})")
        return 1
    export(src, dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
