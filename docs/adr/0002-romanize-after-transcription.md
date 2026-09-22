# 0002. Romanize after transcription instead of asking the speech model for Latin

- **Status:** Accepted, with one exception (see Consequences)
- **Date:** before 0.2; recorded 2026-09-22

## Context

Most speakers of the twelve supported languages type them in Latin letters
("kya kar rahe ho"), but speech models write the native script. Ten ways of
getting Latin output from Whisper directly were tried - prompts, forced first
tokens, language tricks (`experiments/exp1_romanized_prompt.py`,
`exp1b_prompt_controls.py`). The best complied for about thirty seconds and then
reverted to Devanagari mid-sentence.

## Decision

Transcribe in the native script, then convert to Latin in the app:
a 30,000-word lexicon per language from Google's Dakshina (92% of Hindi tokens),
a 4.5M-parameter character model for the rest, and letter-by-letter spelling
as a last resort so no native script is ever pasted into romanized text.
The user's own spellings are learned on top ([0011](0011-learn-at-the-next-dictation.md)).

## Consequences

- Romanization is deterministic, local and measurable against human
  romanizations (`tests/bench_romanization.py`): 84.7% of words acceptable
  across the twelve languages.
- The same transcript can be delivered in either script, chosen per field.
- **Exception:** a model trained to write Latin itself is used where it
  measured better - Hindi's Hinglish-Prime (19.5% delivered WER against 24.4%)
  keeps English words English. Its output is respelled, not romanized, and
  corrections to it are learned word for word.
