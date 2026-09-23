# 0016. IndicWhisper for Marathi, Punjabi and Malayalam - and not the rest

- **Status:** Accepted
- **Date:** 2026-09-23
- **Follows:** [ADR 0003](0003-specialist-models-by-measurement.md), per-language
  models only by measurement

## Context

Five of the twelve languages were listed as weak, waiting on a better openly
licensed model. AI4Bharat's IndicWhisper (Vistaar, MIT) publishes one
Whisper-medium fine-tune per language for twelve Indian languages, and
reports much lower word error than the models here on several of them. Their
scoring is not ours, so the only way to know was to measure all seven weak
languages through this app's own decoding path.

## Decision

Take IndicWhisper for **Marathi, Punjabi and Malayalam**. Keep the current
model for **Kannada, Gujarati, Telugu and Urdu**. The three are uploaded
converted to `itsskofficial/livewhisper-*-indicwhisper`, as every other model
is ([ADR 0007](0007-no-pytorch-at-runtime.md)), with the MIT licence and
credit to AI4Bharat; `scripts/publish_specialist.py` does that.

## Measurement

`tests/bench_asr.py build/fleurs --model <path> --langs <code> --mode forced`,
FLEURS test (40 clips) and dev, word error in the native script, and
"delivered" after romanization. Lower is better.

| | now | IndicWhisper test | IndicWhisper dev | delivered now -> IndicWhisper |
| --- | --- | --- | --- | --- |
| Marathi | 47.2% | **26.5%** | 18.4% | 51.6% -> **31.6%** |
| Punjabi | 60.9% | **40.3%** | 38.9% | 56.3% -> **36.8%** |
| Malayalam | 61.3% | **50.6%** | 52.1% | 58.8% -> **49.3%** |
| Kannada | 32.3% | 30.8% | 26.6% | 30.2% -> 28.7% |
| Gujarati | 49.8% | 51.7% | 50.9% | 48.5% -> 50.5% |
| Telugu | 37.1% | 41.8% | 38.7% | 36.2% -> 42.1% |
| Urdu | 21.8% (large-v3) | 25.6% | 24.5% | 19.6% -> 23.7% |

Dev and test agree everywhere, so no result rests on one split. Kannada's
1.5-point gain is not worth replacing a working model and re-downloading
1.5 GB on every Kannada machine.

AI4Bharat's own FLEURS numbers are lower than these (Marathi 20.5%, Malayalam
22.6%). The gap is scoring, not the model: this app counts a word wrong unless
it matches exactly, with no text normalisation, and decodes through its own
15-second windows.

## Consequences

- Marathi, Punjabi and Malayalam get much better, and their models shrink from
  3-6 GB to 1.5 GB. Malayalam is still the weakest language here.
- All three write English words in their own script, so a code-switched
  sentence loses English words to romanization ("ready" -> "redi"). See
  [ADR 0015](0015-hear-marathi-as-marathi.md) and the open entry on English in
  native script.
- Sinhala and Sindhi are not in IndicWhisper, and stay as they are.
- Anyone who already installed the old Marathi, Punjabi or Malayalam model
  keeps using it until they install the new one; the old entries are gone from
  the catalogue, so nobody new gets them.
