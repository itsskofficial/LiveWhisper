# 0014. Polish is opt-in, English-only, online-only, and checked before pasting

- **Status:** Accepted
- **Date:** 2026-09-22
- **Amends:** [0010](0010-formatter-never-changes-words.md), which still holds
  for formatting; polish is a separate, opt-in step after it

## Context

Rewriting dictation tools such as Typeless remove false starts ("so I was
thinking we could, actually let's meet"), repeated words and filler, and fix
grammar. LiveWhisper's formatter deliberately does none of that
([ADR 0010](0010-formatter-never-changes-words.md)): a model allowed to change
words can answer a question instead of typing it, carry out an instruction,
translate, drop a "not", or respell a name. The maintainer asked for polish as
an opt-in setting with guardrails, English first.

## Decision

- **Opt-in:** `output.polish`, off for new and existing installs; a "Polish my
  English (Beta)" switch on the AI page.
- **Where it runs:** after formatting, before habits, only on text detected as
  English, in Latin script, not romanized or respelled, with no common Hinglish
  words, four words or more, outside code editors and verbatim apps, and never
  on Ctrl+Alt+W text (`polish.applies`).
- **Model:** Groq's `openai/gpt-oss-120b`, so it needs Online. No local
  fallback: when Groq fails or is off, the formatted text is pasted.
- **Guardrails** (`polish.check`): the rewrite is thrown away, and the
  formatted text pasted, if it loses or adds a number (digits or words), email,
  link, code term, acronym, name or Dictionary word; changes a negation or a
  hedge ("maybe", "probably"); brings in a word that is neither a grammar word
  nor a form of one that was said; grows by more than three words; cuts more
  than 40% of the content words; or turns a question into a statement.

## Measurement

`python tests/bench_polish.py --cases <set> --models ... --pace 2.2`. Word
distance is edits to a hand-written polished reference (lower is better).
Violations are pasted text that lost a must-keep word or contains an answer or
an executed instruction; they must be 0.

The guardrails were written and tuned on `tests/data/polish_eval.json` (40
cases). `tests/data/polish_holdout.json` (30 cases) was written afterwards and
is the fair score. One guard (hedges) was added after the held-out run, in
response to the local model's violation there.

Held-out, 28 cases polish applies to:

| Model | Accepted | Word distance | Violations | p50 |
| --- | --- | --- | --- | --- |
| gpt-oss-120b (Groq) | 23, 23 | 35 -> 11, 35 -> 17 | 0, 0 | 0.95 s, 0.99 s |
| gpt-oss-20b (Groq) | 18, 18 | 35 -> 21, 35 -> 21 | 0, 0 | 0.79 s, 0.9 s |
| qwen2.5-3b (this PC) | 21, 20 | 35 -> 35, 35 -> 34 | 1 ("maybe" dropped), 0 | 1.1 s, 1.21 s |

Two runs each; the second after the hedge guard was added, which is why the
local model's violation became a rejection. Groq's replies vary between runs
even at temperature 0.

The guardrails stopped, among others: "17 times 23 is 391", a weather
answer, a definition of "idempotent", "26 miles is about 41.8 km", an executed
"summarise this in two lines", a translation, and "I'm sorry, I can't" in reply
to a prompt injection.

## Consequences

- Polish adds about 1 s to an English dictation when it is on.
- Rejected rewrites are silent: the user gets formatted text, as if polish
  were off. The reason is logged (`not polished: ...`).
- It is conservative: a rewrite that reorders a date or keeps only the
  corrected half of "Thursday, no, Friday" is rejected and the formatted text
  pasted.
- Offline users do not get polish. Revisit when a local model improves the
  held-out distance with 0 violations; `polish.LocalWriter` and the bench are
  kept for that.
- Hinglish, romanized Marathi and the twelve languages are not polished. A
  Latin transcript is skipped when it contains common romanized Hindi or
  Marathi words ("Tu AI system design kuthun shikla?"), in case Whisper labels
  it English; in the end-to-end check Whisper labelled that sentence Hindi.
  Extending polish needs its own evaluation set per language first.
