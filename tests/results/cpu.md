# Which model, on which machine

All on the development machine: RTX 4060 8 GB, 16-core CPU. Accuracy is 40
FLEURS recordings per language through the batched path the app uses, with
15-second windows. Hindi is *delivered* word error — the text the user
receives, after romanization or (for the Hinglish models) respelling, against
every accepted spelling; see `tests/rescore_delivered.py`. Latency is the
decode of a 4-second dictation with the model warm, median of 4–8 clips
(`tests/bench_dictation.py`); language detection is excluded because the app
now runs it while you are still speaking.

## Hindi

| Model | Runs on | Size | Delivered WER | 4 s dictation |
| --- | --- | --- | --- | --- |
| Hinglish-Prime | GPU | 2.9 GB | **20.1%** | **1.1 s** |
| large-v3 | GPU | 3 GB | 23.9% | 2.05 s |
| large-v3-turbo | GPU | 1.6 GB | 26.6% | — |
| **Hinglish-Swift** | **CPU** | **144 MB** | **25.6%** | **0.84 s** |
| small | CPU | 464 MB | 52.9% | 2.5 s |
| large-v3-turbo | CPU | 1.6 GB | 26.6% | 10.7 s |

## English

| Model | Runs on | WER | 4 s dictation |
| --- | --- | --- | --- |
| large-v3 | GPU | 4.8% | 0.87 s |
| large-v3-turbo | GPU | 4.6% | — |
| small | CPU | 5.6% | 2.4 s |
| large-v3-turbo | CPU | 4.6% | 9.9 s |

## What follows

**On a GPU, Hindi should use Hinglish-Prime.** It is the most accurate and it
decodes twice as fast as large-v3, because Latin text costs far fewer tokens
than Devanagari: every Devanagari word is several tokens, and decode time is
per token.

**On a CPU, the old default was the wrong choice for Hindi.** `small` got more
than half of Hindi words wrong. Hinglish-Swift, a model a fifth its size, gets
25.6% — within two points of large-v3 on a GPU — in under a second. The
installer now offers it to Hindi speakers on machines without CUDA.

**Turbo is not a CPU model.** Its speed comes from a smaller decoder; its
encoder is large-v3's, and on a CPU the encoder is nearly all of the cost. It
took 9.9 s for a four-second English clip.

Language detection on a CPU is an encoder pass too (2 s with `small`, 0.7 s
with Swift), which is why moving it into the recording matters most on exactly
these machines.

Beam size was also measured on large-v3 (Hindi 23.9% at beam 5, 24.8% at beam
1) and stays at 5.
