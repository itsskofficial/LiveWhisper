# 0010. The formatting model may add punctuation, never change words

- **Status:** Accepted; polish, an opt-in step after formatting, is
  [ADR 0014](0014-opt-in-english-polish.md)
- **Date:** 0.2; recorded 2026-09-22

## Context

Rules handle spoken commands, lists and corrections exactly but cannot punctuate
a run-on sentence or spot names. Language models can, but small ones answer
questions they were asked to format, and any model may "improve" words -
destroying the user's own spelling and slang, which is what the app is for.

## Decision

The model's output is projected back onto the words that were said
(`llm_format.LLMFormatter`): only punctuation, capitals and line breaks
transfer; if the words do not align, the rules' result is used. For romanized
text, capitals the model adds mid-sentence are undone (online models read
romanized words as names). Rules always run first and are the fallback.

## Consequences

- Measured on 42 cases (`tests/bench_format_llm.py`): rules 40% exactly right,
  local model 67%, Groq 71%, and 0 invented words for all.
- The formatter will not polish grammar or remove false starts the way cloud
  rewriters do. A separate, opt-in "polish" mode would be a new decision.
