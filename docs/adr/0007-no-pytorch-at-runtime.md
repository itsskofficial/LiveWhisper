# 0007. No PyTorch at runtime

- **Status:** Accepted
- **Date:** 2026-09-21

## Context

PyTorch was needed twice: to run the romanizer's character model, and to
convert community fine-tunes to CTranslate2 when a user installed one. It
would have added over a gigabyte to the installer.

## Decision

- The character model runs in numpy (`livewhisper/script/oov.py`, weights in
  `data/translit.npz`, exported by `tools/export_translit.py`). Identical output
  to PyTorch on 2,400 words across twelve languages, and faster.
- Fine-tunes are converted once, by us, and published with their licence and
  credit as `itsskofficial/livewhisper-<name>` on Hugging Face. The app
  downloads them ready to load (`Specialist.download_repo`); only a source
  checkout converts, and only if the mirror is unreachable.

## Consequences

- The installer is 100 MB and has no CUDA or PyTorch in it.
- We carry the mirrors: a new or updated fine-tune must be converted and
  uploaded before users can get it.
