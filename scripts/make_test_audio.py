"""Synthesize test speech in several languages, so the audio path can be tested.

Nothing in the suite has ever exercised transcription - every test starts from a
transcript string. This produces real speech with known ground truth so the whole
chain (audio -> whisper -> language detection -> romanization) can be measured.
"""
import asyncio
import sys
from pathlib import Path

import edge_tts

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "audio")
OUT.mkdir(parents=True, exist_ok=True)

# Sentences written to look like what people actually dictate: code-switched,
# chat register, some English nouns embedded. The expected romanization is what
# a person would type, for a rough sanity check rather than a strict assertion.
CASES = [
    ("hi_1", "hi-IN-MadhurNeural",
     "कल मैं ऑफिस जाऊंगा और मीटिंग अटेंड करूंगा",
     "kal main office jaunga aur meeting attend karunga"),
    ("hi_2", "hi-IN-SwaraNeural",
     "मुझे लगता है कि यह प्रोजेक्ट अच्छा है",
     "mujhe lagta hai ki yah project accha hai"),
    ("hi_3", "hi-IN-MadhurNeural",
     "तुम क्या कर रहे हो आजकल",
     "tum kya kar rahe ho aajkal"),
    ("mr_1", "mr-IN-ManoharNeural",
     "मी उद्या ऑफिसला जाणार आहे",
     "mi udya officela janar aahe"),
    ("ta_1", "ta-IN-ValluvarNeural",
     "நான் நாளைக்கு அலுவலகம் போவேன்",
     "naan naalaikku aluvalagam poven"),
    ("bn_1", "bn-IN-BashkarNeural",
     "আমি কাল অফিসে যাব",
     "ami kal office jabo"),
    ("te_1", "te-IN-MohanNeural",
     "నేను రేపు ఆఫీసుకు వెళ్తాను",
     "nenu repu officeku veltanu"),
    ("gu_1", "gu-IN-NiranjanNeural",
     "હું કાલે ઓફિસ જઈશ",
     "hu kale office jaish"),
    ("kn_1", "kn-IN-GaganNeural",
     "ನಾನು ನಾಳೆ ಕಚೇರಿಗೆ ಹೋಗುತ್ತೇನೆ",
     "naanu naale kacherige hoguttene"),
    ("ml_1", "ml-IN-MidhunNeural",
     "ഞാൻ നാളെ ഓഫീസിൽ പോകും",
     "njan nale officeil pokum"),
    ("ur_1", "ur-PK-AsadNeural",
     "میں کل دفتر جاؤں گا",
     "main kal daftar jaunga"),
    ("pa_1", "pa-IN-OjasNeural",
     "ਮੈਂ ਕੱਲ੍ਹ ਦਫ਼ਤਰ ਜਾਵਾਂਗਾ",
     "main kallh daftar javanga"),
    # English, to confirm nothing is romanized that shouldn't be.
    ("en_1", "en-US-AriaNeural",
     "let's ship the release on Friday and tell the team",
     "let's ship the release on Friday and tell the team"),
    # Code-switched, the realistic case and the hardest one.
    ("mix_1", "hi-IN-SwaraNeural",
     "मैंने pull request review कर लिया है, अब merge कर दो",
     "maine pull request review kar liya hai, ab merge kar do"),
]


async def main() -> None:
    manifest = []
    for name, voice, text, expect in CASES:
        path = OUT / f"{name}.mp3"
        try:
            await edge_tts.Communicate(text, voice).save(str(path))
            size = path.stat().st_size
            print(f"{name:<8} {voice:<24} {size:>7,} bytes")
            manifest.append((name, voice, text, expect))
        except Exception as exc:
            print(f"{name:<8} {voice:<24} FAILED {type(exc).__name__}: {exc}")
    import json
    (OUT / "manifest.json").write_text(
        json.dumps([{"name": n, "voice": v, "native": t, "expect": e}
                    for n, v, t, e in manifest],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(manifest)} clips -> {OUT}")


asyncio.run(main())
