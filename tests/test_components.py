#!/usr/bin/env python
"""The in-app downloader, against a local server - no internet needed.

A first launch downloads gigabytes over whatever connection the user has, so
what matters is what happens when it goes wrong: a dropped connection resumes,
Cancel stops, a corrupted file is caught, and only the two DLLs are lifted out
of NVIDIA's 550 MB package.

    python tests/test_components.py
"""

from __future__ import annotations

import http.server
import io
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["LIVEWHISPER_HOME"] = str(HOME)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import components as comp  # noqa: E402

fails = 0
FILES: dict = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


class Ranged(http.server.BaseHTTPRequestHandler):
    """Serves FILES with HEAD and single byte ranges, like a CDN."""

    def log_message(self, *a):
        pass

    def _body(self):
        data = FILES.get(self.path)
        if data is None:
            self.send_error(404)
            return None, None
        rng = self.headers.get("Range")
        if rng:
            start, _, end = rng.split("=")[1].partition("-")
            start = int(start)
            end = int(end) if end else len(data) - 1
            if start >= len(data):
                self.send_response(416)
                self.end_headers()
                return None, None
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            chunk = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        return chunk, True

    def do_HEAD(self):
        data = FILES.get(self.path)
        if data is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()

    def do_GET(self):
        chunk, ok = self._body()
        if ok:
            self.wfile.write(chunk)


def main() -> int:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ranged)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    out = HOME / "out"
    never = lambda: False            # noqa: E731
    try:
        print("=== lifting two files out of a wheel ===")
        dll_a, dll_b = os.urandom(300_000), os.urandom(200_000)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("nvidia/cublas/bin/cublas64_12.dll", dll_a)
            z.writestr("nvidia/cublas/bin/cublasLt64_12.dll", dll_b)
            z.writestr("nvidia/cublas/include/big_header.h", os.urandom(2_000_000))
        FILES["/cublas.whl"] = buf.getvalue()
        members, url = comp._zip_members(base + "/cublas.whl", comp.CUBLAS_DLLS)
        check("both DLLs found in the zip directory", len(members) == 2)
        got = []
        for info, offset in members:
            comp._fetch_member(url, info, offset, out / Path(info.filename).name,
                               got.append, never)
        check("extracted byte for byte",
              (out / "cublas64_12.dll").read_bytes() == dll_a
              and (out / "cublasLt64_12.dll").read_bytes() == dll_b)
        check("the rest of the package is never downloaded",
              sum(got) < len(FILES["/cublas.whl"]) / 2, f"{sum(got)} bytes")

        print("\n=== a corrupted transfer is caught ===")
        data = bytearray(FILES["/cublas.whl"])
        info, offset = members[0]
        data[offset + 1000] ^= 0xFF
        FILES["/bad.whl"] = bytes(data)
        try:
            comp._fetch_member(base + "/bad.whl", info, offset, out / "bad.dll", lambda n: None, never)
            check("a flipped byte is refused", False)
        except OSError:
            check("a flipped byte is refused", not (out / "bad.dll").exists())

        print("\n=== resume and cancel ===")
        model = os.urandom(3_000_000)
        FILES["/model.bin"] = model
        dest = out / "model.bin"
        part = dest.with_name("model.bin.part")
        part.write_bytes(model[:1_234_567])              # a dropped connection
        got = []
        comp._fetch(base + "/model.bin", dest, got.append, never, len(model))
        check("a partial download resumes where it stopped",
              dest.read_bytes() == model and sum(got) == len(model) - 1_234_567,
              f"{sum(got)} bytes fetched")
        dest.unlink()
        try:
            comp._fetch(base + "/model.bin", dest, lambda n: None, lambda: True)
            check("Cancel stops the download", False)
        except comp.Cancelled:
            check("Cancel stops the download", not dest.exists())
        part.unlink(missing_ok=True)
        FILES["/short.bin"] = model[:1000]
        try:
            comp._fetch(base + "/short.bin", out / "short.bin", lambda n: None, never,
                        expected=len(model))
            check("a truncated file never looks complete", False)
        except OSError:
            check("a truncated file never looks complete", not (out / "short.bin").exists())

        print("\n=== what is offered ===")
        c = comp.Components()
        c.nvidia = False
        ids = [x["id"] for x in c.list()]
        check("no GPU download offered without an NVIDIA card", "gpu" not in ids)
        check("the speech model and both language models are listed",
              {"speech", "formatter", "writer"} <= set(ids))
        check("a CPU machine is offered the CPU Hindi model",
              "lang:hi" in ids and "lang:en" not in ids)
        c.nvidia = True
        ids = [x["id"] for x in c.list()]
        check("an NVIDIA machine is offered GPU support and faster English",
              "gpu" in ids and "lang:en" in ids)
        mirrors = {s.name: s.download_repo for s in comp.specialists.CATALOGUE}
        check("models that need converting come from the converted mirror",
              mirrors["bn-medium"] == "itsskofficial/livewhisper-bn-medium"
              and mirrors["en-turbo"] == "mobiuslabsgmbh/faster-whisper-large-v3-turbo")
    finally:
        srv.shutdown()
        shutil.rmtree(HOME, ignore_errors=True)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
