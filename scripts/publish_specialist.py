#!/usr/bin/env python
"""Upload a converted speech model to Hugging Face, with a model card.

The app downloads its per-language models from `itsskofficial/livewhisper-*`
already converted, because the installed app has no PyTorch to convert with
([ADR 0007](../docs/adr/0007-no-pytorch-at-runtime.md)). This puts one there.

The token is read from HF_TOKEN in the environment and never written anywhere:

    set HF_TOKEN=...   (or pass it inline for this one command)
    python scripts/publish_specialist.py D:/models/ct2/mr-indicwhisper --lang mr

    --dry-run   write the card next to the model and stop
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.script.languages import LANGUAGES  # noqa: E402

_console()

CARD = """---
license: {licence}
language: {lang}
library_name: ctranslate2
tags:
- automatic-speech-recognition
- whisper
- ctranslate2
- livewhisper
base_model: {base}
---

# {title}

{origin} converted to CTranslate2 ({quant}) for
[LiveWhisper](https://github.com/itsskofficial/LiveWhisper), a Windows
voice-dictation app. LiveWhisper ships without PyTorch, so it downloads its
speech models already converted
([ADR 0007](https://github.com/itsskofficial/LiveWhisper/blob/main/docs/adr/0007-no-pytorch-at-runtime.md)).

Nothing about the model was changed beyond the conversion.

## Accuracy

Measured with `tests/bench_asr.py` on the FLEURS test split (40 clips,
{language}), through LiveWhisper's own decoding path:

{table}

`delivered` is what the user is actually given: the transcript after
romanization, scored against every Latin spelling people are attested to use.

## Credit and licence

{credit}

Licence: {licence}, as the original.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--lang", required=True)
    ap.add_argument("--repo", default="", help="default: itsskofficial/livewhisper-<folder name>")
    ap.add_argument("--card", type=Path, help="a written card to use instead of the template")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    folder = args.folder
    if not (folder / "model.bin").exists():
        raise SystemExit(f"{folder} holds no converted model (model.bin)")
    repo = args.repo or f"itsskofficial/livewhisper-{folder.name}"
    card = (args.card or folder.parent / f"{folder.name}.card.md")
    if not card.exists():
        raise SystemExit(f"write the model card first: {card}\n"
                         f"(template fields: {sorted(set(CARD.split('{')[1:]))[:3]}...)")
    language = LANGUAGES[args.lang].name if args.lang in LANGUAGES else args.lang

    print(f"{folder}  ->  https://huggingface.co/{repo}  ({language})")
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1e9
    print(f"{size:.2f} GB in {len(list(folder.rglob('*')))} files")
    if args.dry_run:
        print("dry run; nothing uploaded")
        return 0
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is not set; pass it inline for this one command")

    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.create_repo(repo, repo_type="model", exist_ok=True)
    api.upload_file(path_or_fileobj=str(card), path_in_repo="README.md", repo_id=repo)
    api.upload_folder(folder_path=str(folder), repo_id=repo,
                      ignore_patterns=["*.log", "*.card.md"])
    print(f"uploaded: https://huggingface.co/{repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
