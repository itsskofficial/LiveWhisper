# Benchmark results

Raw output of the measurement scripts, kept so every number in the README and
`docs/HOW-IT-WORKS.md` can be traced to a run.

| File | Produced by | What it measures |
| --- | --- | --- |
| `bench_romanization.md` | `tests/bench_romanization.py` | romanization against human-written Latin spellings |
| `asr_*.json` | `tests/bench_asr.py` | speech models on real recordings, per language |

The `asr_*.json` files name the model and language mode in the file name
(`auto`, `constrained`, `forced`; `heldout-` for the FLEURS dev split, `spec-`
for a specialist) and include up to 200 sample transcripts, so errors can be
read rather than only counted.

## Data credits

- Speech recordings and reference transcripts: **FLEURS**, Google (Conneau et
  al., 2022), CC BY 4.0. <https://huggingface.co/datasets/google/fleurs>
- Human romanizations: **Dakshina**, Google Research (Roark et al., 2020),
  CC BY-SA 4.0. See `data/LICENSE-DATA.md`.
