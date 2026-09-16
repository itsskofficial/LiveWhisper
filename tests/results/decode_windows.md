# How much of a long recording actually gets transcribed

Measured on the development machine: RTX 4060 8 GB, `large-v3`, `int8_float16`,
beam 5, batch size 8, through faster-whisper's batched pipeline — the path the
app decodes with.

## The problem

The batched pipeline finds speech with VAD, then packs it into windows as long
as the model allows: 30 seconds. Whisper answers a full window by stopping
early, and nothing reports that it did. The transcript simply ends sooner than
the recording.

It does not show on the recordings accuracy is usually measured on. A FLEURS
clip is one sentence of about ten seconds, so it never fills a window. It shows
the moment someone dictates a paragraph.

## The measurement

`tests/bench_windows.py`: 36 FLEURS sentences per language, decoded on their
own, and the same sentences joined three at a time with 0.8 s pauses into 12
paragraph-length recordings (a stand-in for dictating a paragraph; a single
sentence read aloud has no pause to split on). "Kept" is the share of spoken
words that came back at all.

**Hindi** — sentences median 11 s, paragraphs median 37 s

| Window | Sentences WER | Paragraphs WER | Kept |
| --- | --- | --- | --- |
| 30 s (library default, shipped before) | 27.6% | **47.6%** | **74%** |
| 20 s | 27.6% | 31.7% | 94% |
| **15 s (shipped now)** | **27.5%** | 30.9% | 96% |
| 10 s | 31.2% | 30.0% | 97% |
| 30 s if the recording fits, else 15 s | 27.6% | 31.4% | 95% |

**English** — sentences median 10 s, paragraphs median 30 s

| Window | Sentences WER | Paragraphs WER | Kept |
| --- | --- | --- | --- |
| 30 s (library default, shipped before) | 5.3% | **27.5%** | **77%** |
| 20 s | 5.3% | 22.9% | 81% |
| **15 s (shipped now)** | **5.3%** | **11.6%** | **93%** |
| 10 s | 5.7% | 18.5% | 87% |
| 30 s if the recording fits, else 15 s | 5.3% | 18.1% | 87% |

## What it means

**The default lost a quarter of every paragraph**, in both languages, with no
error and a transcript that reads as if the speaker simply stopped.

**15 seconds keeps the words and costs nothing on single sentences.** Hindi
sentence error 27.6% → 27.5%, English unchanged at 5.3%, while paragraph error
falls from 47.6% to 30.9% (Hindi) and from 27.5% to 11.6% (English).

**Shorter is not better.** 10-second windows start cutting sentences in the
middle and lose context: single-sentence Hindi rose to 31.2%. That was the first
fix tried, on the evidence of one 40-second recording, and the FLEURS check
caught it before it shipped.

**Deciding by length lost too.** Decoding whole anything that fits in one
window, and in 15-second windows otherwise, was worse on English paragraphs
(18.1%): recordings just under the cut-off still filled their window and still
lost words. A fixed 15 seconds is simpler and better.

Paragraph wall-clock times were measured once per setting and varied more
between runs than between settings, so they are not reported as a result.
`transcription.local.chunk_length` overrides the window.

### An earlier, smaller run

The first sign of this was a single recording per case, before the table above:

| Recording | 30 s windows | 10 s windows |
| --- | --- | --- |
| Hindi, 40 s, 92 words | 62 words back, 55.4% WER | 91 back, 30.4% |
| English, 32 s, 71 words | 70 back, 11.3% | 70 back, 9.9% |

The English recording kept its words that time; the 12-paragraph run shows that
was luck.
