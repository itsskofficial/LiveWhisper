# 0012. Online is one switch, and languages with their own model stay local

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Groq gives about 2 s from the end of speech to pasted text on any PC, against
5-7 s on a laptop GPU capped on battery. Users should not have to reason about
which of speech, formatting and writing is where. But Groq only runs the
general Whisper model, which is far worse than an installed language model:
Bengali 73% of words wrong against 21%, Tamil 57% against 23%.

## Decision

`processing: local | online` is the only switch (AI page, or Ctrl+Alt+G).
Online sends speech, formatting (gpt-oss-20b) and writing (gpt-oss-120b) to
Groq, each falling back to this PC when Groq cannot answer. A language whose
own model is downloaded is still decoded here: routed by the language guessed
while the user speaks, or redone here if Groq reports that language
(`AutoBackend._local_is_better`).

## Consequences

- Measured end to end with `--online`: English and Hinglish about 2 s; online
  Marathi 80% -> 39-47% word error and Kannada 73% -> 0-8% once routed locally.
- Online still needs the local models for fallback and for those languages.
- Groq model names change: the Llama models used before were retired and had
  broken online writing; the current ones are chosen in the bench, not assumed.
