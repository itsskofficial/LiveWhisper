#!/usr/bin/env python
"""Downloads survive a dropped connection.

Installing the 1.5 GB Marathi model broke 7 MB in ("Connection broken:
IncompleteRead") and the whole install failed, although each file is written
to a .part that could be resumed. These serve a file from a local server that
hangs up mid-stream and check the download still finishes, byte for byte.

    python tests/test_downloads.py
"""

from __future__ import annotations

import hashlib
import http.server
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper import components  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402

_console()
fails = 0
BODY = bytes(range(256)) * 16000         # 4 MB, easy to check
# Past one CHUNK, so a chunk lands on disk before the hang-up, as in the real
# download. A drop inside the first chunk writes nothing - see the last case.
CUT_AFTER = components.CHUNK + 500_000


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


class Server(http.server.BaseHTTPRequestHandler):
    drops = 1                            # hang up on this many requests

    def do_GET(self):                    # noqa: N802 - http.server's name
        start = 0
        if self.headers.get("Range"):
            start = int(self.headers["Range"].split("=")[1].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(BODY)-1}/{len(BODY)}")
        else:
            self.send_response(200)
        rest = BODY[start:]
        self.send_header("Content-Length", str(len(rest)))
        self.end_headers()
        if type(self).drops > 0:
            type(self).drops -= 1
            self.wfile.write(rest[:CUT_AFTER])   # then close: a broken read
            self.close_connection = True
            return
        self.wfile.write(rest)

    def log_message(self, *a):
        pass


def serve() -> tuple:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/model.bin"


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    httpd, url = serve()
    got = []

    print("=== a connection that drops once ===")
    Server.drops = 1
    dest = tmp / "once.bin"
    components._fetch(url, dest, got.append, lambda: False, expected=len(BODY))
    check("the file arrives complete", dest.exists() and dest.read_bytes() == BODY,
          f"{dest.stat().st_size if dest.exists() else 0} of {len(BODY)} bytes")
    check("the digest matches", hashlib.sha256(dest.read_bytes()).hexdigest()
          == hashlib.sha256(BODY).hexdigest())
    check("progress counted every byte once", sum(got) == len(BODY), f"reported {sum(got)}")
    check("no .part left behind", not dest.with_name(dest.name + ".part").exists())

    print("\n=== a connection that drops again and again ===")
    # More drops than FETCH_ATTEMPTS: each one still moved the file forward,
    # and the 1.5 GB Marathi model really did break this often.
    Server.drops = components.FETCH_ATTEMPTS + 4
    dest = tmp / "many.bin"
    components._fetch(url, dest, lambda n: None, lambda: False, expected=len(BODY))
    check("progress keeps the download alive", dest.exists() and dest.read_bytes() == BODY)

    print("\n=== a connection that never gets a whole chunk through ===")
    # Cut inside the first chunk, so nothing reaches the disk: with no
    # progress to keep it alive it must stop, not hammer the server forever.
    global CUT_AFTER
    CUT_AFTER = 300_000                  # less than components.CHUNK
    Server.drops = 99
    dest = tmp / "hopeless.bin"
    try:
        components._fetch(url, dest, lambda n: None, lambda: False, expected=len(BODY))
        check("it gives up", False, "it returned as if complete")
    except Exception as e:
        check("it gives up", not isinstance(e, SystemExit), type(e).__name__)
    check("and the half file is not passed off as the model", not dest.exists())

    print("\n=== cancelling still works ===")
    Server.drops = 0
    dest = tmp / "cancelled.bin"
    try:
        components._fetch(url, dest, lambda n: None, lambda: True, expected=len(BODY))
        check("cancel stops the download", False, "it finished anyway")
    except components.Cancelled:
        check("cancel stops the download", True)
    httpd.shutdown()

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
