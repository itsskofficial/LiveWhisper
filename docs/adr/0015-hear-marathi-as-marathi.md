# 0015. Correct Whisper when it hears Marathi as Hindi

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

A user dictated "tu AI system design kuthun shikla?" - Marathi with English
words. Every voice tried came back as Hindi, and was then decoded as Hindi:
कुठून became कुछून, and the romanized text was Hindi-flavoured. Measured with
a new harness on 40 code-switched Marathi sentences in two voices
(`tests/eval_codeswitch.py`, `tests/data/codeswitch_mr.json`), the app as
shipped heard Marathi as Marathi on 6% of the tuning clips and 22% of the
held-out ones.

Two languages here share a script and sound alike: Hindi and Marathi
(Devanagari), Urdu and Sindhi (Arabic). Whisper decides the language from the
first seconds of sound, before any word is written.

## Decision

Both corrections apply only to speakers whose language list has both
languages, so nobody who dictates one of them pays for the other.

- **At detection** (`LocalBackend._second_guess_hindi`): Whisper rarely lets
  Marathi win outright, but scores it far higher on Marathi speech than on
  Hindi. Decode as Marathi when log10(P(mr)/P(hi)) > -1.5.
- **After decoding** (`script/langcheck.py`): when the transcript holds at
  least two words that only the sibling language's lexicon knows, and more of
  them than words only the heard language knows, decode again in that
  language. The same check runs on the Groq path, which re-asks Groq with the
  language set; Online then moves the clip to this PC if a better model for it
  is installed here.

## Measurement

Detection threshold, tuned on dev clips (FLEURS dev, the Hinglish set, the
dev half of the Marathi set) and checked on the held-out half:

| At -1.5 | Marathi decoded as Marathi | Hindi flipped to Marathi |
| --- | --- | --- |
| dev | 64 of 78 | 0 of 80 |
| held out | 19 of 32 | 0 of 40 |

The highest log10(P(mr)/P(hi)) on any Hindi clip was -2.05, so -1.5 leaves a
margin; -2 would recover more and sit on top of that clip.

The word check on reference text: 357 of 370 sentences recovered from the
wrong sibling, 0 of 370 correct ones flipped (`tests/test_langcheck.py` keeps
the FLEURS half of this).

End to end on the held-out Marathi clips (`tests/eval_codeswitch.py --split
test`), with [ADR 0016](0016-indicwhisper-specialists.md)'s model in the last
column:

| | shipped | + these fixes | + IndicWhisper |
| --- | --- | --- | --- |
| heard as Marathi | 22% | 53% | 59% |
| Marathi words in a spelling people use | 30% | 46% | 55% |
| native script exact | 39% | 54% | 72% |
| English words kept in English | 72% | 62% | 62% |

## Consequences

- A corrected clip is decoded twice, so those dictations take about twice as
  long. Only the corrected ones.
- English words come back in English less often than before. The Hinglish
  model keeps English words well but writes Marathi as Hindi; with the clip
  correctly on a Marathi model, English words are written in Devanagari and
  romanize as "redi" or "kensal". The gain in Marathi words outweighs it, and
  the remaining loss is [issue: English written in Devanagari](../decisions.md).
- The word check is weak on Latin-writing routes: the Hinglish model's output
  has no Devanagari to read, so only the detection threshold helps there.
- A code-switched example in the decoding prompt was tried and did not help
  (43.3% -> 44.0% English kept, and 52% -> 50% on IndicWhisper), matching the
  earlier Hindi experiment in `experiments/hinglish_settings.py`.
- Only Hindi/Marathi is measured. Urdu/Sindhi shares the word-check path
  because the lexicons support it, but no audio measurement has been made; the
  detection threshold is Hindi/Marathi only.
