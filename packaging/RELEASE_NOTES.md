**Voice typing for Windows, in English and twelve Indian languages, written the way you actually type them.**

Download **LiveWhisper-Setup-1.1.0.exe** below and run it. No Python, no command line, no administrator rights. Upgrading from 1.0 keeps your settings, Dictionary and downloaded models.

On first launch you pick the languages you speak and LiveWhisper downloads what runs on your PC (the speech model, sized to your machine; GPU support on NVIDIA cards; a small formatting model). Then press **Ctrl+Alt+Space**, speak, and press it again. The text appears wherever your cursor is.

> Windows may say *"Windows protected your PC"*: the installer isn't code-signed yet. Click **More info → Run anyway**.

### What's new in 1.1

- **Marathi is heard as Marathi.** Whisper labelled Marathi speech as Hindi and wrote it that way — on a new set of code-switched sentences it got the language right on 22% of held-out clips. It now reconsiders, both from how close Marathi scored and from the words it wrote, and gets 59% right, without turning a single Hindi clip into Marathi. Only for people who dictate in both.
- **Much better Marathi, Punjabi and Malayalam.** New accuracy models (AI4Bharat's IndicWhisper), measured on FLEURS through the app: Marathi 47.2% → **26.5%** of words wrong, Punjabi 60.9% → **40.3%**, Malayalam 61.3% → **50.6%**. Each is 1.5 GB instead of 3–6 GB. Kannada, Gujarati, Telugu and Urdu were no better on measurement, so they keep the models they had.
- **Polish my English (Beta)**, off by default, under **AI**. With Online on, your English dictation is rewritten the way you would have typed it: false starts, repeated words and filler removed, grammar fixed. Every rewrite is checked against what you said first — if it changes a name, number, link, "not" or "maybe", answers a question you were only typing, or adds anything you did not say, it is thrown away and your own words are pasted instead.
- **A dropped connection no longer ruins a model download.** It carries on from where it stopped instead of starting again.

### Known limits

- Polish needs Online. The model that runs on your PC made the text no better on held-out dictation, so it is not offered there.
- A Marathi or Hindi model writes English words in its own script, so "ready" can come back as "redi" in romanized text. Fixing it properly needs an English pronunciation dictionary.
- Gujarati and Sinhala still get about half their words wrong: no better openly licensed model exists yet.
- On a laptop running on battery, Windows caps the GPU and local dictation is several times slower. Plug in, or turn on Online.
- Windows 10/11, 64-bit only.

Full list of changes: [CHANGELOG.md](https://github.com/itsskofficial/LiveWhisper/blob/main/CHANGELOG.md)
