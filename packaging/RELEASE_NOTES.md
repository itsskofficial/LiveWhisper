**Voice typing for Windows, in English and twelve Indian languages, written the way you actually type them.**

Download **LiveWhisper-Setup-1.0.0.exe** below and run it. No Python, no command line, no administrator rights.

On first launch you pick the languages you speak and LiveWhisper downloads what runs on your PC (the speech model, sized to your machine; GPU support on NVIDIA cards; a small formatting model). Then press **Ctrl+Alt+Space**, speak, and press it again. The text appears wherever your cursor is.

> Windows may say *"Windows protected your PC"*: the installer isn't code-signed yet. Click **More info → Run anyway**.

### What's in 1.0

- **A real desktop app.** A window for your History, Dictionary, Languages, AI and Settings, and a small recording pill with a live waveform that never steals focus from the box you're typing in.
- **Your language, your script.** Hindi, Bengali, Urdu, Punjabi, Marathi, Telugu, Tamil, Gujarati, Kannada, Malayalam, Sinhala and Sindhi, in their own script or romanized (Hinglish, Tanglish, Banglish…), switched automatically by the box you're typing in, or with **Ctrl+Alt+H**.
- **Accuracy models per language**, one click each. Native-script Hindi at 10% word error, Bengali 14.5%, Tamil and Kannada about 24%. Every number, including the weak ones, is in the README.
- **Finished text, not a transcript.** Say "comma", "new paragraph", "bullet point", or correct yourself ("Monday, I mean Tuesday"). A small local model punctuates what you didn't say out loud. It never changes your words.
- **It learns your spelling.** Fix a word after it's pasted and the fix sticks; teach it your Hinglish in a minute from the Dictionary.
- **Write for me** (**Ctrl+Alt+W**): say *"reply saying I'll be there at five"* and get the finished message. **Ctrl+Alt+F** fixes the grammar in the box you're in, keeping your style.
- **Private by default, online with one switch.** Speech, formatting and writing all run on your PC. Turn on **Online** (free Groq key) and all three run in the cloud, about 2 s from the end of speech to pasted text, falling back to your PC whenever you're offline.

### Known limits

- Gujarati, Punjabi, Malayalam and Marathi still get about half the words wrong, and Sinhala most of them: no better openly licensed model exists yet.
- On a laptop running on battery, Windows caps the GPU and local dictation is several times slower. Plug in, or turn on Online.
- Windows 10/11, 64-bit only.

Full list of changes: [CHANGELOG.md](https://github.com/itsskofficial/LiveWhisper/blob/main/CHANGELOG.md)
