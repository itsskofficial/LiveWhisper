"""One LiveWhisper at a time.

Two copies would both register the hotkeys, both record and both paste. The
first to start listens on a loopback port and writes it to a file; a later
launch finds it there, asks it to show its window, and exits.
"""

from __future__ import annotations

import logging
import socket
import threading

from . import paths

log = logging.getLogger(__name__)

PORT_FILE = paths.HOME / "instance.port"
HELLO = b"LiveWhisper:show\n"


def signal_running() -> bool:
    """True if another copy is running (and has been asked to show itself)."""
    try:
        port = int(PORT_FILE.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5) as s:
            s.sendall(HELLO)
            return s.recv(16).startswith(b"ok")
    except OSError:
        return False


MUTEX = "LiveWhisper.Running"
_mutex = None


def serve(on_show) -> None:
    """Listen for later launches; call on_show() when one arrives."""
    global _mutex
    # Held for the life of the process: the installer looks for it to know
    # the app must be closed before its files are replaced.
    try:
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX)
    except (AttributeError, OSError):
        pass
    try:
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(srv.getsockname()[1]))
    except OSError:
        log.warning("single-instance listener unavailable", exc_info=True)
        return

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(2)
                    if conn.recv(64).startswith(HELLO.strip()):
                        conn.sendall(b"ok")
                        on_show()
                except OSError:
                    pass

    threading.Thread(target=loop, name="instance", daemon=True).start()
