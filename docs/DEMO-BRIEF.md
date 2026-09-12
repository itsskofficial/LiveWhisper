# Demo brief — LiveWhisper

*Paste this whole file to the demo agent. It is self-contained: what to show,
in what order, with exact sentences that are verified to produce the results
described, plus the things that will ruin a take.*

**Target length: 4–5 minutes.** Screen recording only, 1080p minimum.

---

## The app

**LiveWhisper** — voice dictation for Windows that writes the way *you* write,
not the way a dictionary thinks you should. **Twelve South Asian languages**,
about 1.67 billion speakers.

| | |
| --- | --- |
| Location | `E:\Apps\LiveWhisper` |
| Launch | Start Menu → "LiveWhisper", or `.venv\Scripts\pythonw.exe run.py` |
| Repo | https://github.com/itsskofficial/LiveWhisper |
| Deep explanation | `docs/HOW-IT-WORKS.md` |

Runs in the tray — no main window. A coloured dot (grey idle, red recording,
amber transcribing) and a floating pill while recording.

| Hotkey | Does |
| --- | --- |
| `Ctrl+Alt+Space` | Dictate |
| `Ctrl+Alt+W` | Speak an instruction, it writes the text |
| `Ctrl+Alt+F` | Fix grammar in the current field |
| `Ctrl+Alt+N` | Notes mode |
| `Ctrl+Alt+H` | Keep next dictation in Devanagari |
| `Ctrl+Alt+X` | Discard |

---

## The one idea the demo must land

> Every dictation tool **normalises** your speech — adds punctuation, fixes
> capitalisation, cleans it up. But personal writing style *is* deviation from
> the norm. So the whole category actively destroys the thing that makes text
> sound like you.
>
> **LiveWhisper keeps what the others throw away.**

Two proofs, both verifiable:

1. **Wispr Flow's own documentation** says it learns from your corrections but
   explicitly discards *"capitalization-only changes"*. It keeps vocabulary and
   throws away style — a word→word dictionary has nowhere to store "don't
   capitalise in this app."
2. **Script.** Whisper writes Hindi as `क्या कर रहे हो`. Nobody types Devanagari
   on WhatsApp; they type `kya kar rahe ho`. Voice typing produces the wrong
   *script* for hundreds of millions of people, and no speech engine can be
   asked for romanized Hinglish.

---

## Structure — 4:45

Keep the order. The learning beat (§4) is the emotional peak; everything before
sets it up and everything after is supporting evidence.

---

### 0 — Cold open · 15s

No narration. Just the contrast, fast:

```
    कल मैं ऑफिस जाऊंगा          ← what every dictation app gives you
    kal main office jaunga      ← what you'd actually type
```

Hold two seconds. Cut to title.

---

### 1 — The problem · 30s

Open a chat window. Dictate a Hinglish sentence with script conversion disabled
(**Settings → Writing → Default script → `devanagari`**). It pastes as
Devanagari.

**Caption:** *"Correct Hindi. Nobody types like this."*

Then the second half of the problem — dictate in a chat app and show the output
arriving with capitals and a full stop.

**Caption:** *"And it always writes like a press release."*

This beat names both problems the app solves. Don't rush it.

---

### 2 — Setup wizard · 50s

Delete the profile first (see Prep) so this runs live.

The wizard shows five sentences in Devanagari and asks you to type each one your
way. **Type in genuine chat style** — lowercase, no full stops, your own
spellings. That is the whole point and it must look natural.

Show at least two sentences being typed. Screen 1:

```
   मुझे कल ऑफिस जाना है, तू आ रहा है क्या?
   > muze kal office jana hai, tu aa raha hai kya
```

Linger on the final summary screen, which reports what it learned:

```
   Spelling habits learned:
      jh -> z   (applies to every word)
```

**Caption:** *"One minute. It now knows how you spell."*

**Detail worth narrating:** it isn't memorising words — it learned that you
write **ज** as `z`, which applies to every word containing that letter.

---

### 2.5 — Twelve languages · 30s  **[NEW - lead with this on social]**

The reach is the story for anyone who isn't Indian, and the *names* are the hook
for anyone who is. Quick montage, one line each, same hotkey:

```
   हिन्दी   कल मैं ऑफिस जाऊंगा      →  kal main office jaunga     Hinglish
   தமிழ்    நான் நாளைக்கு வருவேன்    →  naan naalaikku varuven     Tanglish
   বাংলা    আমি কাল আসব             →  ami kal asbo               Banglish
   తెలుగు   నేను రేపు వస్తాను        →  nenu repu vastanu          Thanglish
```

**Caption:** *"Twelve languages. 1.67 billion people. Same problem, nobody
solved it."*

You can shoot this without speaking each language — set **Settings → Writing →
Language**, paste native text into the field, and show the conversion. Say
plainly in the caption that it's a text demo if you do; don't imply you spoke
Tamil.

### 3 — The script fix · 30s

Set **Default script** back to `latin`. Dictate the same sentence from §1.

```
   कल मैं ऑफिस जाऊंगा     →     kal main office jaunga
```

**Caption:** *"Same words. The script you actually type in."*

Then the number that surprises people:

**Caption:** *"92% of this is a dictionary lookup. Not AI."*

If you want a visual: `data/hi.lexicon.tsv` is 30,000 lines of
`Devanagari → spelling`. Scrolling it for two seconds sells the point.

---

### 4 — The learning loop · 70s — **THE KEY BEAT**

Give this the most time. Do it slowly enough to follow.

1. Dictate a sentence containing **mujhe** → pastes `mujhe lagta hai...`
2. **Correct it by hand** to `muze` — show the keystrokes
3. Dictate a different sentence containing **samjho** → still pastes `samjho`
4. **Correct that one too** → `samzo`
5. Dictate a **third, completely new** sentence with another `jh` word
6. It comes out with `z` — **uncorrected**

**Caption on the third:** *"Two corrections. It generalised to 316 words."*

That number is real — `jh` appears in 316 words in the lexicon.

Then open **Settings → Writing** and show the panel:

```
   Spelling conventions (applied to every word):
      jh -> z
   Exact words remembered: 4
```

**Caption:** *"Plain text you can read, edit, or delete. Not a black box."*

**Optional, 10s, and a strong trust beat:** click **Forget everything**, show
the panel empty. Nothing is locked in.

**Worth narrating:** one correction is *not* enough — it only fixes that word,
because you might have typo'd. Two different words promote it to a rule. And
even then the rule is checked before it generalises: a habit that would rewrite
too much of the language is refused.

---

### 5 — Per-app style · 40s

The idea nobody else implements. Requires seeded history (see Prep).

Dictate the **same sentence** into two different apps.

Say: *"Ok done, main kal bhej dunga. Thanks."*

| App | Output |
| --- | --- |
| WhatsApp | `ok done, main kal bhej dunga. thanks` |
| Outlook | `Ok done, main kal bhej dunga. Thanks.` |

**Caption:** *"Same voice. Different app. It knows the difference."*

This single sentence carries romanization *and* per-app style at once — use it
exactly as written; it is verified to produce these two outputs.

Then show **Settings → Writing** listing the observed rates:

```
   whatsapp.exe   capitals   0%   full stops   0%   (5 samples)
   outlook.exe    capitals 100%   full stops 100%   (5 samples)
```

**Caption:** *"Observed, not configured."* Those are measurements of how you
actually write, not settings you picked.

---

### 6 — Write this for me · 40s

**Use Notepad. Not a browser.** (See Warnings.)

Paste a short email into Notepad so there is something to reply to. Press
`Ctrl+Alt+W` and say:

> *"reply saying I can't make Thursday, propose Monday instead"*

It reads what's on screen, writes the reply, and pastes it — **in your style**,
lowercase if that's how you write in that app.

**Caption:** *"It read the screen. You didn't paste anything."*

Worth showing: the floating pill with the live level meter during the 8-second
listen, so it's clear when it's capturing.

---

### 7 — Grammar that keeps your voice · 35s

The contrast is the point, not the correction.

Type a deliberately messy line in a chat window:

```
   i has went to the market yesterday and buyed some stuff
```

Press `Ctrl+Alt+F`:

```
   i went to the market yesterday and bought some stuff
```

**Caption:** *"Fixed the grammar. Kept the lowercase."*

Say plainly: Grammarly would capitalise that `i` and "correct" your Hinglish
into English. This is explicitly told not to — deliberate lowercase, slang and
romanized spellings are **not errors**.

**Timing warning:** takes 9–11 seconds on the local model. Cut the wait or speed
it up in post.

---

### 8 — Notes · 20s

Press `Ctrl+Alt+N`, play a few seconds of any video or call audio, press it
again. Open the resulting file.

Show it's plain Markdown with timestamps in `E:\Apps\LiveWhisper\notes\`.

**Caption:** *"System audio → notes. Readable without this app."*

---

### 9 — Under the hood · 35s

Earn the "free and local" claim rather than asserting it.

Simple diagram or captions over the Settings → Engine panel:

```
   92% of words   →   dictionary lookup     instant, 1.1 MB, no AI
    8% of words   →   2.5M character model  10 MB, runs on CPU
    every word    →   your conventions      learned from you
                                            ────────────
                                            ~97% correct
```

**Caption:** *"The hardest part isn't a model. It's a table."*

Then, briefly: transcription is Whisper `large-v3` on your GPU at **27x
realtime**. Writing and grammar use Ollama locally. Show the provider dropdown
in Settings → Engine to make it concrete that it's swappable.

---

### 10 — Close · 15s

```
   Runs on your machine.
   No subscription. No word limits.
   Open source.
```

Optional final card: *~97% of Hindi words correctly romanized · 27x realtime ·
all local.*

---

## Prep before recording

```powershell
cd E:\Apps\LiveWhisper

# 1. Health check - 22 checks, all should pass
.\.venv\Scripts\python.exe verify.py

# 2. Ollama must be running (needed for Ctrl+Alt+W and Ctrl+Alt+F)
ollama list                      # expect qwen2.5:7b

# 3a. To demo the WIZARD (beat 2), clear the profile:
.\.venv\Scripts\python.exe demo_seed.py --clear

# 3b. To demo PER-APP STYLE (beat 5), seed realistic history:
.\.venv\Scripts\python.exe demo_seed.py

# check what is currently learned at any point:
.\.venv\Scripts\python.exe demo_seed.py --show
```

**3a and 3b conflict.** The wizard only runs when no profile exists. So either
record beat 2 first, then seed and record beat 5 — or record them in two
sessions. Do not try to do both from one state.

**About seeding:** `demo_seed.py` feeds the app the same observations it would
collect from you writing in those apps for a week. The behaviour it produces is
real — it just saves ten minutes of dictating on camera to reach three samples
per app. Showing the "(5 samples)" counts on screen keeps it honest.

**Warm-up:** the first launch loads a 3 GB model and takes ~15 seconds before
the first dictation works. Launch and wait before the first take.

---

## Things that will break the demo

**Use Notepad, not Chrome or Brave, for anything that reads the screen.**
Measured today: reading a Brave window returned **16 characters**. Chrome and
Electron apps (Slack, Discord, VS Code, web Gmail) hide their text from the
Windows accessibility layer. Notepad, WordPad and native Windows apps work.
This is the app's weakest area — do not build a beat on it.

**The app records system audio as well as your microphone.** If you narrate
while screen-recording, that narration gets captured by the dictation itself.
Either turn off **Settings → Audio → Capture system audio**, or record narration
separately in post. **This will bite you if ignored.**

**Grammar fix takes 9–11 seconds** locally. Cut around it, or switch
**Settings → Engine → Provider** to `groq` first — much faster, but then it is
no longer a local-only demo, so don't claim local in that beat.

**Don't demo:** browser text fields, dictations over ~60s, or the OCR fallback
(works, but 2.3s per screen and visually dull).

---

## Tone

**Do**

- Show text changing. Don't describe it.
- Use the real numbers — 92%, 316 words, two corrections, 27x. They're measured,
  and more persuasive than adjectives.
- Let the Hinglish be Hinglish. Captions carry non-Hindi viewers; don't overlay
  a translation on every line.
- State the local/private angle once, at the end.

**Don't**

- Call it "AI-powered". The most interesting fact is that the hardest part is a
  **dictionary lookup**.
- Oversell the writing assistant — every competitor has one. The **style
  learning** is what nobody else does.
- Claim it beats Wispr Flow on dictation accuracy. It doesn't. It beats them at
  sounding like you.
- Use stock footage of people talking into phones. Screen recording only.

---

## Claims you can make safely

| Claim | Basis |
| --- | --- |
| 92.3% of Hindi words covered by dictionary lookup | Measured on real Whisper output |
| ~97% of words correctly romanized end to end | Dictionary + model combined |
| 316 words affected by one `jh → z` correction | Counted in the lexicon |
| 10 corrections ≈ 57% of spelling variation | Measured across 30,000 words |
| 27x realtime transcription | Measured on an RTX 4060 |
| Whisper can't be prompted into romanized output | Tested 10 ways, all failed |
| 12 languages, 87.4% average coverage | Measured per language on running text |
| ~1.67 billion speakers reached | Sum of the twelve |
| Wispr Flow discards capitalization-only changes | Their own documentation |
| Runs fully offline | True for dictation, romanization and style |

**Do not claim:** extensive real-user testing (there has been none), that the
local writing assistant matches cloud models (it doesn't), or any accuracy
figure for English dictation (not measured).

**Especially do not claim** the non-Hindi languages are verified. Eleven of the
twelve have never been checked by a native speaker - the numbers say the
dictionary contains the words, not that the spellings are ones a speaker would
choose. If a demo shows Tamil or Bengali, say the coverage is measured and the
quality is unreviewed. Getting this wrong in public would be the fastest way to
lose the people we most want contributing.

---

## Deliverables

1. **Main demo** — 4–5 min, the structure above
2. **60-second cut** — beats 0, 3, 4, 5 only. Script fix + learning + per-app is
   the complete story
3. **15-second social cut** — beat 0 and beat 4's payoff
4. **Thumbnail** — the side-by-side from the cold open

Text must be legible at mobile size: zoom into the text field rather than
showing the whole desktop.
