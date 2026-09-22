# 0003. Route each language to its own model, chosen only by measurement

- **Status:** Accepted
- **Date:** 0.2 to 1.0; recorded 2026-09-22

## Context

One general model (Whisper large-v3) is weak on most of the twelve languages:
73% of Bengali words wrong, 57% of Tamil, and Sindhi not written at all.
Community fine-tunes are often far better, but some are worse, some were
trained on the test data, and some only win in one script.

## Decision

A language is decoded by its own model when one is installed
(`LocalBackend._model_for`); detection stays on the main model. A model enters
the catalogue (`livewhisper/specialists.py`) only with measurements on held-out
FLEURS, delivered as the app delivers it, confirmed on a second split or
sample. Entries without measurements are never offered. A language can have
two: one for romanized output and one for native script (Hindi: Hinglish-Prime
and Vaani). At most `max_extra_models` stay loaded, least recently used out,
sized from VRAM.

## Consequences

- Bengali 73% -> 14.5% WER, Tamil 57% -> 24.6%, Hindi native 26.5% -> 10.3%,
  Sindhi from unwritable to 29.2% (`tests/eval_outputs.py`).
- Rejected on evidence: an Urdu fine-tune (no better), adaptive decode
  windows (worse), and Sindhi's dev-split score (contaminated).
- Each model is a 0.15-3 GB download and a first-use load of several seconds.
- Weak languages stay weak until a better openly licensed model exists; the
  README says so.
