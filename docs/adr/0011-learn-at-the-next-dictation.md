# 0011. Learn from corrections by reading the field at the next dictation

- **Status:** Accepted
- **Date:** 0.2, extended 2026-09-22
-
## Context

The user's corrections are the best signal of how they spell. Watching them
type would be keylogging.

## Decision

At the start of the next dictation, read the focused field through UI
Automation and compare it with what was pasted. If it is plausibly an edit of
our text, learn: for romanized text, the native word's new spelling and, when
the same letter change appears in two words, a rule; for a Hinglish model's
Latin text, the word's respelling - but only when the consonants match after
the usual romanization choices are set aside, so "karunga" -> "karoonga" is
learned and "meeting" -> "meetings" is not. Rules are validated against the
lexicon before they apply everywhere.

## Consequences

- Nothing runs in the background and nothing records keystrokes.
- Learning needs the next dictation to happen in the same field; edits made
  elsewhere are not seen.
- Until 1.0, corrections to the Hinglish model's output were silently ignored
  (found end to end); the Latin path fixed that.
