# PyInstaller spec for the LiveWhisper desktop app.
#
#   .venv\Scripts\pyinstaller packaging\LiveWhisper.spec --noconfirm
#
# One folder, not one file: a one-file exe unpacks ~250 MB to a temp folder on
# every launch, which is seconds of waiting and trips antivirus heuristics.
# The folder is what the installer (packaging/installer.iss) ships.
#
# Left out on purpose: PyTorch and transformers (the romanizer runs on numpy;
# specialist models come pre-converted) and the pip CUDA packages (the app
# downloads the two cuBLAS files it needs - livewhisper/components.py).

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "livewhisper" / "ui" / "index.html"), "livewhisper/ui"),
    (str(ROOT / "config.yaml"), "."),
    (str(ROOT / "assets" / "livewhisper.ico"), "assets"),
    (str(ROOT / "assets" / "livewhisper.png"), "assets"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "data" / "LICENSE-DATA.md"), "data"),
    (str(ROOT / "data" / "translit.npz"), "data"),
    (str(ROOT / "vendor" / "llama"), "vendor/llama"),
]
datas += [(str(p), "data") for p in (ROOT / "data").glob("*.lexicon.tsv")]
datas += collect_data_files("faster_whisper")          # the Silero VAD model
datas += collect_data_files("webview")                 # pywebview's bridge JS
datas += collect_data_files("pyaudiowpatch")

binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")

excludes = [
    "torch", "torchaudio", "torchvision", "transformers", "nvidia", "tensorflow",
    "tkinter", "customtkinter", "matplotlib", "IPython", "jupyter", "notebook",
    "pytest", "scipy", "pandas", "sklearn", "edge_tts", "datasets",
    # The optional screenshot-OCR fallback (context.py) and its 115 MB of
    # OpenCV; and xet transfers, which the app turns off (hub.plain_http).
    "rapidocr_onnxruntime", "cv2", "shapely", "hf_xet",
]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["webview.platforms.edgechromium", "webview.platforms.winforms",
                   "clr", "pystray._win32", "comtypes.stream"],
    excludes=excludes,
    noarchive=False,
)
# PyInstaller also copies llama.cpp's DLLs to the bundle root, where the
# runner - which inherits the bundle's DLL directory - would load ggml.dll
# from, and then look beside it for its GPU backend and not find one.
_llama = ("ggml", "llama", "mtmd", "libomp")
a.binaries = [b for b in a.binaries
              if "/" in b[0].replace("\\", "/") or not b[0].lower().startswith(_llama)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LiveWhisper",
    icon=str(ROOT / "assets" / "livewhisper.ico"),
    console=False,
    version=str(ROOT / "packaging" / "version.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LiveWhisper", upx=False)
