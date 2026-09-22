# experiments

One-off measurements behind early decisions, kept so their conclusions can be
re-checked. Results of the numbered experiments are in `results/`. Current
evaluation lives in `tests/` - see [docs/evaluation.md](../docs/evaluation.md).

| Script | Question | Outcome |
| --- | --- | --- |
| `exp1_romanized_prompt.py`, `exp1b_prompt_controls.py` | can a prompt make Whisper write Latin? | no - it reverts to native script ([ADR 0002](../docs/adr/0002-romanize-after-transcription.md)) |
| `exp2_dakshina_coverage.py`, `exp3_apply_lexicon.py` | how far does a lexicon get? | 92% of Hindi tokens |
| `exp4_oov_seq2seq.py` | can a small model spell the rest? | yes - the character model |
| `exp5_spelling_axes.py` | how many corrections does personalisation need? | a handful of letter-level axes |
| `exp6_onboarding_sentences.py` | which sentences should setup ask for? | the five in `onboarding.py` |
| `exp7_multilingual_coverage.py` | does it generalise to the other eleven? | yes, 76-92% coverage |
| `hinglish_settings.py`, `groq_hinglish.py` | best settings for code-switched speech, locally and on Groq | led to the Hinglish model route |
| `capture_accuracy.py`, `compare_engines.py` | accuracy on captured audio; agreement between engines | early engine choice |
| `decode_throughput.py`, `sapi_loopback_e2e.py` | decode speed on long audio; the loopback path | superseded by `tests/bench_latency.py` and `tests/e2e_app.py` |
