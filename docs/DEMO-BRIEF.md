# Demo brief — LiveWhisper

*Paste this to the demo agent. It contains everything needed to build the demo,
including what is verified working, what is fragile, and what to avoid showing.*

---

## What you are demoing

**LiveWhisper** — a voice dictation app for Windows that writes the way the user
writes, rather than the way a dictionary thinks they should.

**Location:** `E:\Apps\LiveWhisper`
**Launch:** `E:\Apps\LiveWhisper\.venv\Scripts\pythonw.exe E:\Apps\LiveWhisper\run.py`
(or the Start Menu / Desktop shortcut "LiveWhisper")
**Repo:** https://github.com/itsskofficial/LiveWhisper
**Full technical explanation:** `E:\Apps\LiveWhisper\docs\HOW-IT-WORKS.md`

It runs as a tray app. There is no main window — a coloured dot in the system
tray (grey = idle, red = recording, amber = transcribing) and a floating pill
that appears while recording.

---

## The one idea the demo must land

> Every dictation tool **normalises** your speech — adds punctuation, fixes
> capitalisation, cleans it up. But personal writing style *is* deviation from
> the norm. So the entire category actively destroys the thing that makes text
> sound like you.
>
> LiveWhisper keeps what the others throw away.

If a viewer remembers one thing, it should be that. Everything below is in
service of it.

**Two concrete proofs, both true and verifiable:**

1. **Wispr Flow's own documentation** states it learns from your corrections but
   explicitly discards *"capitalization-only changes"*. It keeps vocabulary and
   throws away style — because a word→word dictionary has nowhere to store
   "don't capitalise in this app."

2. **Script.** Whisper transcribes Hindi as `क्या कर रहे हो`. Nobody types
   Devanagari on WhatsApp; they type `kya kar rahe ho`. So voice typing produces
   text in the wrong *script* for hundreds of millions of people, and there is
   no way to ask a speech engine for romanized Hinglish.

---

## Suggested structure (~2 minutes)

Adapt freely, but keep the order: **problem → the fix → the learning → the rest.**
The learning moment is the emotional peak; do not bury it at the end.

### Beat 1 — The problem (~15s)

Show the failure, don't describe it. Dictate a Hinglish sentence with the script
conversion turned off (Settings → Writing → Default script → `devanagari`), so
it pastes as:

```
कल मैं ऑफिस जाऊंगा
```

into a chat window. Caption: **"This is what every dictation app gives you."**
The point reads instantly to anyone Indian, and to everyone else the caption
carries it.

### Beat 2 — The fix (~20s)

Switch the setting back to `latin`. Same sentence. Now:

```
kal main office jaunga
```

Caption: **"Same words. The script you actually type in."**

Optional overlay, and a genuinely interesting number:
**92% of this is a dictionary lookup, not AI.**

### Beat 3 — The learning (~40s) — THE KEY BEAT

This is the demo. Give it the most time.

1. Dictate a sentence containing `mujhe` — it pastes as `mujhe lagta hai`
2. **The user edits it by hand** to `muze lagta hai` (show the keystrokes)
3. Dictate a second sentence containing a different `jh` word — `samjho`
4. Edit that one too → `samzo`
5. Dictate a **third, completely new** sentence with yet another `jh` word
6. It comes out `z` **without being corrected**

Caption over the third: **"Two corrections. It generalised to 316 words."**

That number is real: `jh` appears in 316 words in the lexicon. The app learned a
*rule* about the letter ज, not a fact about one word.

Then open **Settings → Writing** and show the panel listing:

```
Spelling conventions (applied to every word):
   jh -> z
```

Caption: **"Plain text you can read, edit, or delete. Not a black box."**

### Beat 4 — The rest (~30s)

Quick cuts, no lingering:

- **`Ctrl+Alt+W`** in Notepad — speak *"write a reply saying I can't make
  Thursday, propose Monday"* → a written reply appears
- **`Ctrl+Alt+F`** — a sentence with bad grammar gets fixed, **while keeping the
  lowercase and slang intact**. That contrast is the interesting part, not the
  correction itself
- **`Ctrl+Alt+N`** — notes mode, system audio transcribed into a Markdown file

### Beat 5 — Close (~10s)

```
Runs on your machine.  No subscription.  No word limits.
Open source.
```

Optional closing number: **~97% of Hindi words correctly romanized, 27x realtime
transcription, all local.**

---

## Exact things you can show, verified working

All of the following were tested and confirmed on this machine today.

| What | How | Notes |
| --- | --- | --- |
| Romanization | Dictate any Hinglish sentence | `कल मैं office जाऊंगा` → `kal main office jaunga` |
| Setup wizard | Launches automatically on first run | Profile was cleared, so it **will** appear |
| Learning a rule | Two corrections of `jh` words | Verified: promotes to `jh → z` |
| Settings → Writing | Tray → Settings → Writing | Lists learned rules, has Forget button |
| Grammar fix | `Ctrl+Alt+F` | ~9–11s on local model. Plan around this |
| Compose | `Ctrl+Alt+W` | ~3s. Listens 8s for the instruction |
| Notes | `Ctrl+Alt+N` | Writes to `E:\Apps\LiveWhisper\notes\` |
| Force Devanagari | `Ctrl+Alt+H` | Next dictation stays in original script |

---

## Things that will break the demo — read this

**Use Notepad, not Chrome or Brave, for anything involving reading the screen.**
Measured today: reading a Brave window returned **16 characters**. Chrome and
Electron apps (Slack, Discord, VS Code, web Gmail) hide their text from the
Windows accessibility layer. Notepad, WordPad and native apps work correctly.
This is the app's weakest area — do not build a beat around it.

**Grammar fix takes 9–11 seconds** on the local model. Either cut around it,
speed it up in post, or switch the provider to Groq in Settings → Engine first
(much faster, but then it is not a local-only demo).

**The first launch after a reboot loads a 3 GB model** and takes ~15 seconds
before the first dictation works. Warm it up before recording.

**Never show the tray notification text as a headline** — notifications are
small and transient. Use captions instead.

**Do not demo:** anything in a browser text field, very long dictations
(>60s adds a wait), or the OCR fallback (works, but 2.3s per screen and visually
uninteresting).

---

## Setup before recording

```powershell
# 1. Confirm everything is healthy - 22 checks, all should pass
cd E:\Apps\LiveWhisper
.\.venv\Scripts\python.exe verify.py

# 2. Make sure Ollama is running (needed for Ctrl+Alt+W and Ctrl+Alt+F)
ollama list        # should show qwen2.5:7b

# 3. To demo the setup wizard, ensure no profile exists
#    (already cleared, but re-check if you have run the app since)
del E:\Apps\LiveWhisper\profiles.json   # only if you want the wizard to appear

# 4. Launch and let it warm up for ~20 seconds before the first take
```

**Audio:** the app records the microphone *and* system audio. If you are
recording a screencast with narration, that narration will be captured by the
dictation too. Either mute system audio capture (Settings → Audio → Capture
system audio → off) or record narration separately in post. **This will bite you
if you ignore it.**

---

## Tone and framing

**Do:**

- Be concrete. Show the text changing, don't describe it.
- Use the real numbers — 92%, 316 words, two corrections, 27x realtime. They are
  measured, not marketing, and they are more persuasive than adjectives.
- Let the Hinglish be Hinglish. Do not add a translation overlay for every line;
  the audience who cares will read it, and the captions carry the rest.
- Keep the local/private angle understated. State it once at the end.

**Don't:**

- Call it "AI-powered". The most interesting fact is that the hardest part is a
  *dictionary lookup*, not a model.
- Oversell the writing assistant. It is real but ordinary — every competitor has
  one. The style learning is what nobody else does.
- Claim it beats Wispr Flow at dictation accuracy. It does not; it beats them at
  sounding like you.
- Use stock footage of people talking into phones. Screen recording only.

---

## Facts you can quote safely

| Claim | Status |
| --- | --- |
| 92.3% of Hindi words covered by dictionary lookup | Measured on real Whisper output |
| ~97% of words correctly romanized end to end | Dictionary + model combined |
| 316 words affected by one `jh → z` correction | Counted in the lexicon |
| 10 corrections ≈ 57% of spelling variation | Measured across 30,000 words |
| 27x realtime transcription | Measured on an RTX 4060 |
| Whisper cannot be prompted into romanized output | Tested 10 ways, all failed |
| Wispr Flow discards capitalization-only changes | Their own documentation |

**Do not claim:** that it has been tested extensively with real users (it has
not), that the writing assistant matches cloud models (it does not), or any
specific accuracy figure for English dictation (not measured).

---

## Deliverables

1. **Main demo** — ~2 minutes, the structure above
2. **15-second cut** — beats 1–3 only, for social. The script switch and the
   learning moment are the whole story
3. **Thumbnail/still** — the side-by-side of `कल मैं ऑफिस जाऊंगा` and
   `kal main office jaunga`

Screen recording at 1080p minimum. Text must be legible at mobile size — zoom
into the text field rather than showing the whole desktop.
