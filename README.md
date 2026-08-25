<div align="center">

<img src="assets/livewhisper.png" width="96" alt="LiveWhisper">

# LiveWhisper

**Voice dictation that writes the way you write.**

Hold a hotkey, speak, and the words land at your cursor — in your capitalisation,
your punctuation, and your Hinglish spellings. Runs on your own machine.

</div>

---

## Why this exists

Every dictation tool is built to **normalise** your speech: add punctuation, fix
capitalisation, clean it up. But personal writing style *is* deviation from the
norm. So the category's core feature actively destroys the thing that makes text
sound like you.

Two concrete examples that shaped this project:

**Lowercase.** Some people write `nhi yaar kal karta hoon` on WhatsApp and
`Dear Sir,` in email. Wispr Flow reads your corrections — its documentation says
so — but explicitly discards *"capitalization-only changes"*. It keeps
vocabulary and throws away style, because a word→word dictionary has nowhere to
put "don't capitalise in this app."

**Script.** Whisper transcribes Hindi as `क्या कर रहे हो`. Almost nobody types
Devanagari in chat; they type `kya kar rahe ho`. Research confirms there is no
way to ask a speech engine for romanized Hinglish. So voice typing produces text
in the wrong *script* for hundreds of millions of people.

LiveWhisper keeps what the others throw away.

## What it does

| | Hotkey | |
| --- | --- | --- |
| **Dictate** | `Ctrl+Alt+Space` | Speak, text lands at your cursor in your style |
| **Write this for me** | `Ctrl+Alt+W` | Speak an instruction; it reads your screen for context |
| **Fix grammar** | `Ctrl+Alt+F` | Corrects the field you're in, *keeping* your slang and lowercase |
| **Notes** | `Ctrl+Alt+N` | System-audio transcripts append to a Markdown note |
| **Force Devanagari** | `Ctrl+Alt+H` | Keep the next dictation in the original script |

## Install

Windows 10/11, Python 3.10+, NVIDIA GPU recommended.

```powershell
git clone https://github.com/itsskofficial/LiveWhisper.git
cd LiveWhisper
.\install.ps1
```

On first run a one-minute wizard shows five sentences in Devanagari and asks you
to type them your way. That's enough to learn most of your spelling habits
before you dictate anything. It's skippable.

## How the Hinglish part works

Three stages, and only one of them is a neural network:

```
92.3% of words  →  dictionary lookup   →  instant, 1.1 MB, no AI
 7.7% of words  →  2.5M char model     →  10 MB, runs on CPU
      every word →  your conventions    →  learned from your corrections
                                          ─────────────
                                          ~97% correct
```

The dictionary comes from Google's [Dakshina](https://github.com/google-research-datasets/dakshina)
dataset — 30,000 Hindi and 30,000 Marathi words with the Latin spellings real
people use. Coverage was measured against real Whisper output, not a benchmark.

**Why this matters:** nine-tenths of the hard problem is a table lookup. That's
why this can be free and instant where cloud tools charge monthly and count your
words.

## How it learns

Your correction of `mujhe` → `muze` isn't a fact about that word. It's a fact
about how you spell **ज** — and it applies to the 316 other words containing it.

We measured this across 30,000 words. Variation follows 1,200 letter-level
conventions, heavily concentrated:

| Conventions learned | Variation explained |
| --- | --- |
| 5 | 43.9% |
| **10** | **57.0%** |
| 20 | 70.5% |

So about ten corrections — or one minute of setup — gets you most of the way.

**How it notices.** It does *not* watch you type. At the start of your next
dictation, before pasting, it reads what's currently in that field and compares
it with what it left there. Nothing runs in the background.

**What it stores.** Plain readable JSON, one section per app — observed rates,
not settings:

```json
"whatsapp.exe": { "habits": { "capitalize": 0.04, "terminal_period": 0.11 } },
"_global":      { "conventions": { "rules": { "jh": "z" } } }
```

Spelling is global (how you spell ज doesn't change between apps). Habits are
per-app (your WhatsApp voice isn't your email voice). Open it, edit it, delete
it — **Settings → Writing** shows exactly what it has learned.

**Safety rule.** One correction fixes that word but doesn't generalise — you
might have typo'd. Two different words promote it to a rule, and even then the
rule is checked against the lexicon first. This is not theoretical: in testing,
someone typing `too` for तू taught the app `u → oo`, which rewrote `aur` as
`aoor` and `bahut` as `bahoot` — 97% of affected words wrong. Single vowels are
now refused; consonants like `jh → z` pass.

## Local by default

| Stage | Local? |
| --- | --- |
| Audio capture | Always |
| Transcription | Yes — faster-whisper on your GPU |
| Romanization + style | Yes — no network at all |
| Compose & grammar | Yes, via Ollama — or Groq/OpenAI/Anthropic if you prefer |

**Honest note:** local models are genuinely fine for grammar and short rewrites.
For longer composition a frontier model is noticeably better. Ollama support is
a real capability, not parity.

## Measured

| | |
| --- | --- |
| Transcription | 27x realtime (`large-v3`, RTX 4060) |
| Dictionary coverage | 92.3% of Devanagari tokens |
| OOV model | 63.2% exact match, 2.56M params, CPU |
| Combined | ~97% of words correctly romanized |
| Grammar fix (local) | ~9s · Compose (local) ~3s |

Every number is reproducible from `experiments/`.

## Development

```powershell
python check_setup.py       # environment diagnostics
python test_pipeline.py     # romanization, learning, habits, notes
python test_gui.py          # wizard + settings, on a throwaway profile
python run.py -v            # run with debug logging
```

`docs/HOW-IT-WORKS.md` explains the whole system from scratch, assuming no
background in speech recognition or machine learning.

## Licence

Code MIT. The Dakshina lexicons in `data/` are CC BY-SA 4.0 — see
`data/LICENSE-DATA.md`.
