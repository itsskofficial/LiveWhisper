# Evaluation

LiveWhisper's rule: a model, rule or setting ships only if it wins on data it
was not tuned on, and every number anywhere in the project names the script
that produced it. This page lists the data, the harnesses, and the current
results. Raw outputs are committed in `tests/results/`
([index](../tests/results/README.md)).

## Data

| Set | What | Used for |
| --- | --- | --- |
| **FLEURS** test / dev (Google, CC BY 4.0) | read sentences with reference transcripts, 12 languages + English | speech accuracy per language; dev is the held-out check for choices made on test |
| **Dakshina** (Google, CC BY-SA 4.0) | 30k-word lexicons and ~5,000 human-romanized sentences per language | romanization against what people actually type; the lexicons ship in `data/` |
| Dakshina spoken | 15 Dakshina sentences per language read by neural voices | both outputs where FLEURS has no data (Sinhala) |
| `tests/data/hinglish_eval.json` | synthetic code-switched Hindi/English | keeping English words English in Hinglish |
| `tests/data/format_eval.json` | 42 dictations with the formatted text a careful typist would write | formatting quality |
| `tests/data/polish_eval.json`, `polish_holdout.json` | 40 + 30 English dictations with a polished reference, must-keep words and must-not words (answers, executed instructions) | polish; the guardrails were tuned on the first, the second is the fair score |
| end-to-end clips | TTS sentences with checks (commands, lists, corrections) | the real app, speakers → loopback → Notepad |

FLEURS audio is fetched with `scripts/fetch_fleurs.py`; Dakshina from Google's
release. Neither is committed.

Contamination is checked: `steja/whisper-large-sindhi` scored an implausible
1.1% on FLEURS dev, which it was trained on, so Sindhi is reported on test only.

## Harnesses

| Script | Measures |
| --- | --- |
| `tests/eval_outputs.py` | both outputs per language, through the app's own code: native WER/CER, romanized WER against every accepted spelling, "usual spelling" share, native-script leaks |
| `tests/bench_asr.py` | one speech model on FLEURS per language (`--prompt`, `--batch`, `--mode`) |
| `tests/bench_romanization.py` | romanization of Dakshina sentences against the human romanization (`--offset` for a disjoint sample) |
| `tests/eval_dakshina_speech.py` | spoken Dakshina sentences, both outputs (`--try lang=path` for a candidate model) |
| `tests/eval_hinglish.py` | English retention and Hindi spelling on code-switched speech |
| `tests/bench_format_llm.py` | formatting models against the 42 cases (`--models groq:<id>`, `--pace`) |
| `tests/bench_polish.py` | polish: accepted rewrites, word distance to the reference, violations (must be 0) (`--cases`, `--models groq:<id>,builtin`, `--llm-dir`) |
| `tests/e2e_app.py` | the app end to end: English, Hinglish, every language, learning; `--online` |
| `tests/bench_latency.py`, `tests/bench_windows.py`, `tests/bench_compose.py` | latency, decode window length, compose quality |
| `tests/rescore_delivered.py` | re-scores saved outputs as delivered (after respelling) |

## Current results

### Both outputs per language

`python tests/eval_outputs.py build/fleurs --n 20` - held-out FLEURS test, the
language's accuracy model installed. WER: share of words wrong; "usual
spelling": share of romanized words written the way people most often write
them.

| Language | Model | Native WER | Native CER | Romanized WER | Usual spelling |
| --- | --- | --- | --- | --- | --- |
| Hindi | Vaani (native), Hinglish-Prime (romanized) | 10.3% | 3.0% | 18.1% | 75.4% |
| Bengali | Bengali.AI medium | 14.5% | 2.6% | 24.1% | 91.5% |
| Urdu | large-v3 | 23.0% | 9.2% | 20.3% | 87.3% |
| Kannada | IIT Madras medium | 24.3% | 10.8% | 22.8% | 87.3% |
| Tamil | IIT Madras medium | 24.6% | 12.4% | 24.3% | 89.2% |
| Sindhi | Sindhi large | 29.2% | 13.1% | 68.4% | 19.7% |
| Telugu | IIT Madras medium | 31.7% | 19.3% | 31.1% | 82.9% |
| Marathi | Marathi large-v2 | 40.2% | 11.4% | 42.1% | 49.3% |
| Gujarati | IIT Madras medium | 45.2% | 34.1% | 43.6% | 69.1% |
| Malayalam | Malayalam large-v3 | 57.2% | 27.9% | 53.8% | 60.3% |
| Punjabi | Punjabi large-v2 | 57.3% | 28.1% | 52.9% | 53.0% |
| Sinhala | Sinhala large-v3 (spoken Dakshina) | 77.6% | 34.8% | 76.9% | — |
| English | large-v3-turbo (40 clips) | 4.3% | 2.2% | — | — |

No native script leaked into romanized output in 220 dictations.

### Formatting

`python tests/bench_format_llm.py --models ... --pace 2.2` - 42 cases, share
formatted exactly as expected, and words the model invented (must be 0).

| Formatter | Exact | Invented | Latency |
| --- | --- | --- | --- |
| rules only | 40% | 0 | < 1 ms |
| qwen3 0.6B (local) | 67% | 0 | 0.2-0.6 s |
| gpt-oss-20b (Groq, Online) | 71% | 0 | ~0.7 s |

### Polish

`python tests/bench_polish.py --cases tests/data/polish_holdout.json --models ...
--pace 2.2` - 28 held-out cases polish applies to ([ADR 0014](adr/0014-opt-in-english-polish.md)).

| Model | Accepted | Word distance | Violations | Latency (p50) |
| --- | --- | --- | --- | --- |
| gpt-oss-120b (Groq, used) | 23 | 35 -> 11 / 17 | 0 | ~1 s |
| gpt-oss-20b (Groq) | 18 | 35 -> 21 | 0 | ~0.85 s |
| qwen2.5-3b (this PC) | 20-21 | 35 -> 34-35 | 1, then 0 with the hedge guard | ~1.2 s |

Two runs; Groq's replies vary between runs.

### End to end

`python tests/e2e_app.py`: every English and Hinglish case, every language in
the sweep, and learning from a correction pass, locally and with `--online`.
Wait from the end of speech to pasted text: about 1 s locally on mains power,
about 2 s with Online on; a laptop GPU capped on battery takes 5-7 s locally.

### Guards

`guard.looping` flags 0 of 239,516 real Dakshina sentences as invented text.

## Adding or changing a model

1. Measure the candidate against the current choice on FLEURS test with the
   harness above, delivered as the app delivers it.
2. Confirm on FLEURS dev (or a second disjoint sample) before believing it.
3. Add it to `livewhisper/specialists.py` with its measurements; an entry
   without `measured` is never offered to users.
4. If it needs converting, publish the converted copy (see
   [development.md](development.md#releasing)).
