<div align="center">

<img src="assets/livewhisper.png" width="88" alt="LiveWhisper">

# LiveWhisper

**Voice typing for the 1.6 billion people who type their language in English letters.**

You speak Hindi. You type `kya kar rahe ho`.
Every dictation app gives you `क्या कर रहे हो`.

*Hinglish · Tanglish · Banglish · Thanglish · Manglish · Punglish · and six more*

</div>

---

## The problem, in one line

Speech engines write the "correct" script. Nobody types the correct script.

```
   you say:            "kal main office jaunga"
   Whisper writes:      कल मैं ऑफिस जाऊंगा        ← correct Hindi. unusable in chat.
   LiveWhisper writes:  kal main office jaunga    ← what you'd have typed
```

There is **no way to ask a speech engine for romanized output**. We tested ten
different approaches and every one failed, so LiveWhisper converts the script
itself — and then learns the spellings *you personally* use.

## And a second problem nobody solves

Dictation tools **normalise** your writing: they add punctuation, fix
capitalisation, clean it up. But personal style *is* deviation from the norm, so
the whole category destroys the thing that makes text sound like you.

Wispr Flow's own documentation says it learns from your corrections but
explicitly discards *"capitalization-only changes"*. If you write in lowercase
on WhatsApp, it sees you delete that capital every single time — and throws the
signal away, because a word→word dictionary has nowhere to put "don't capitalise
in this app."

**LiveWhisper keeps what the others throw away.**

---

## Twelve languages

| | Language | Romanized as | Speakers | Lexicon coverage |
| --- | --- | --- | --- | --- |
| 🇮🇳 | Hindi | Hinglish | 610M | 87.3% |
| 🇧🇩 | Bengali | Banglish | 270M | 83.4% |
| 🇵🇰 | Urdu | Urdish | 230M | **92.1%** |
| 🇮🇳 | Punjabi | Punglish | 125M | 91.4% |
| 🇮🇳 | Marathi | Minglish | 83M | 90.9% |
| 🇮🇳 | Telugu | Thanglish | 83M | 86.2% |
| 🇮🇳 | Tamil | Tanglish | 79M | 86.9% |
| 🇮🇳 | Gujarati | Gujlish | 57M | 90.8% |
| 🇮🇳 | Kannada | Kanglish | 44M | 88.2% |
| 🇮🇳 | Malayalam | Manglish | 38M | 88.1% |
| 🇵🇰 | Sindhi | Sindhlish | 32M | 88.0% |
| 🇱🇰 | Sinhala | Singlish | 17M | 76.2% |

**87.4% average**, measured on running text, not a benchmark. It picks the
language from what you actually said — speak Tamil at work and Hindi at home
without touching a setting.

---

## Install

Windows 10/11 · Python 3.10+ · NVIDIA GPU recommended (works without)

```powershell
git clone https://github.com/itsskofficial/LiveWhisper.git
cd LiveWhisper
.\install.ps1
```

A one-minute wizard then asks you to type a few sentences your way. That alone
teaches it most of your spelling habits. Skippable.

| Hotkey | |
| --- | --- |
| `Ctrl+Alt+Space` | Dictate |
| `Ctrl+Alt+W` | Speak an instruction — it reads your screen and writes the text |
| `Ctrl+Alt+F` | Fix grammar, *keeping* your lowercase and slang |
| `Ctrl+Alt+N` | Notes from system audio |
| `Ctrl+Alt+H` | Keep the next dictation in the original script |

---

## How it learns you

Correct `mujhe` → `muze` once. That isn't a fact about that word — it's a fact
about how you spell **ज**, and it applies to the **316 other words** containing
it.

We measured this across 30,000 words. Variation follows 1,200 letter-level
conventions, heavily concentrated:

| Corrections | Variation explained |
| --- | --- |
| 5 | 43.9% |
| **10** | **57.0%** |
| 20 | 70.5% |

**It does not watch you type.** At the start of your next dictation, before
pasting, it reads what's in that field and compares it with what it left there.
Nothing runs in the background.

**What it stores** is plain readable JSON — observed rates, not settings:

```json
"whatsapp.exe": { "habits": { "capitalize": 0.04, "terminal_period": 0.11 } },
"_global":      { "conventions": { "rules": { "jh": "z" } } }
```

Spelling is global; how you spell ज doesn't change between apps. Habits are
per-app; your WhatsApp voice isn't your email voice. **Settings → Writing**
shows exactly what it has learned, with a button to forget all of it.

### It refuses to learn nonsense

Type `too` for तू once and a naive system learns `u → oo`, which rewrites `aur`
as `aoor` and `bahut` as `bahoot` — **97% of affected words wrong**, measured.

So a rule needs two *different* words before it generalises, and even then it's
checked: a single Latin vowel stands for several native vowels, so replacing it
everywhere destroys the distinction. Consonants like `jh → z` map reliably and
pass. Rejected substitutions still apply to that one word.

---

## How it works

Three stages, and only one is a neural network:

```
  87% of words  →  dictionary lookup     instant · 17 MB · no AI
  13% of words  →  2.5M character model  runs on CPU
  every word    →  your own conventions  learned from your corrections
```

The dictionary is Google's [Dakshina](https://github.com/google-research-datasets/dakshina)
dataset — 350,000 words across twelve languages, with the Latin spellings real
people actually use.

**The hardest part isn't a model. It's a table.** That's why this is free and
instant where cloud tools charge monthly and count your words.

---

## Local by default

| | Local? |
| --- | --- |
| Audio capture | Always |
| Transcription | Yes — faster-whisper on your GPU, 27x realtime |
| Romanization + style | Yes — no network at all |
| Compose & grammar | Yes via Ollama — or Groq/OpenAI/Anthropic if you prefer |

No telemetry. No account. No word limits. Your profile is a file on your disk.

**Honest note:** local models are fine for grammar and short rewrites. For
longer composition a frontier model is noticeably better. Ollama support is a
real capability, not parity.

---

## Measured, not claimed

| | |
| --- | --- |
| Lexicon coverage, 12 languages | **87.4%** average on running text |
| Transcription | 27x realtime (`large-v3`, RTX 4060) |
| Character model (Hindi) | 63.2% exact match, 2.56M params, CPU |
| 10 corrections | 57% of spelling variation |
| Whisper → romanized via prompting | **Impossible** — 10 approaches, all failed |

Every number is reproducible from [`experiments/`](experiments/).

---

## Contributing

**The most valuable thing a native speaker can do** takes ten minutes: write
five natural chat-register sentences in your language for the setup wizard.
Hindi has them; the other eleven currently generate word prompts from the
lexicon instead, which works but is less good.

See [CONTRIBUTING.md](CONTRIBUTING.md) — it's a single file edit, and there's an
issue template that walks you through it.

Also wanted: curated common-word lists per language, macOS and Linux support,
and anyone who can tell us the romanization looks wrong for their language.

```powershell
python -m tools.check_data    # lexicon integrity, all 12 languages
python -m tools.check_core    # romanization, learning rules, profiles
python verify.py              # full readiness check, 22 checks
```

## Licence

Code MIT. The Dakshina lexicons in `data/` are CC BY-SA 4.0 — see
[data/LICENSE-DATA.md](data/LICENSE-DATA.md).
