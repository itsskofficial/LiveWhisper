#!/usr/bin/env python
"""Diagnose the environment before running LiveWhisper for real.

Checks imports, the WASAPI loopback device, the microphone, CUDA availability,
and the Groq key. Run this first: it turns the usual cryptic runtime failures
into a readable list.
"""

import os
import sys

import livewhisper  # noqa: F401 - loads .env and registers the CUDA DLL dirs

OK, BAD, WARN = "[ ok ]", "[FAIL]", "[warn]"
problems = []


def check(label, fn, fatal=True):
    try:
        detail = fn()
        print(f"{OK} {label}" + (f" - {detail}" if detail else ""))
        return True
    except Exception as e:
        print(f"{BAD if fatal else WARN} {label} - {e}")
        if fatal:
            problems.append(label)
        return False


def imports():
    import keyboard, numpy, pyaudiowpatch, pyperclip, pystray, requests  # noqa: F401
    import soundfile, soxr, yaml  # noqa: F401
    from PIL import Image  # noqa: F401
    return f"python {sys.version.split()[0]}"


def loopback():
    import pyaudiowpatch as pyaudio
    from livewhisper.audio import _default_loopback

    with pyaudio.PyAudio() as p:
        d = _default_loopback(p)
        return f"{d['name']} ({int(d['maxInputChannels'])} ch @ {int(d['defaultSampleRate'])} Hz)"


def microphone():
    import pyaudiowpatch as pyaudio

    with pyaudio.PyAudio() as p:
        d = p.get_default_input_device_info()
        return d["name"]


def cuda():
    from faster_whisper import WhisperModel

    m = WhisperModel("tiny", device="cuda", compute_type="int8_float16")
    del m
    return "CUDA + cuDNN working"


def groq():
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set (only needed for the Groq backend)")
    return f"key present ({key[:6]}...)"


print("LiveWhisper setup check\n" + "-" * 60)
check("dependencies", imports)
check("WASAPI loopback (system audio)", loopback)
check("microphone", microphone, fatal=False)
check("CUDA / cuDNN for faster-whisper", cuda, fatal=False)
check("Groq API key", groq, fatal=False)
print("-" * 60)

if problems:
    print(f"\n{len(problems)} blocking problem(s): {', '.join(problems)}")
    sys.exit(1)
print("\nReady. Start with:  python run.py")
