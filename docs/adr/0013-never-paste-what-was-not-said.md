# 0013. Never paste what was not said, or where it was not meant

- **Status:** Accepted
- **Date:** 2026-09-20 to 2026-09-22

## Context

Three failures seen end to end: dictation started in Notepad was pasted into a
different window the user had moved to; a muted microphone produced "Aapke liye
aapke liye aapke liye" and it was pasted; names read off the screen (actually
Notepad's status bar, "Col, Plain, CRLF") turned a Bengali sentence into one
garbled word.

## Decision

- Paste only into the window that was in front when dictation started;
  otherwise leave the text on the clipboard and say so.
- Drop a transcript that is one phrase looping, or a known silence phrase on
  audio at the noise floor, and say "Nothing was heard" (`livewhisper/guard.py`).
- Give names from the screen only to English and Hinglish decoding, and never
  window chrome (`bias.py`, `LocalBackend.transcribe`).

## Consequences

- The loop check flags 0 of 239,516 real sentences, so real speech is not lost.
- A real dictation of only "okay" or "thank you" on a very quiet microphone is
  dropped; accepted as rare.
