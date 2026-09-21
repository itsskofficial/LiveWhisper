"""Every dictation, for the History page and the numbers on Home.

One JSON object per line in paths.HISTORY. Append-only while the app runs, so a
crash mid-write loses at most the line being written, and a damaged line is
skipped rather than taking the rest of the history with it.

Kept on this PC only. "Clear history" deletes the file.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

# A typical typing speed, for "time saved". 40 wpm is the commonly quoted
# average for adults typing prose; dictation is compared against it.
TYPING_WPM = 40
KEEP = 5000                     # entries kept when the file is compacted


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.HISTORY
        self._lock = threading.Lock()

    def add(self, text: str, seconds: float, *, app: str = "", language: str = "",
            mode: str = "dictate", delivered: str = "pasted") -> dict:
        entry = {"id": uuid.uuid4().hex[:12], "ts": time.time(), "text": text,
                 "words": len(text.split()), "seconds": round(float(seconds), 2),
                 "app": app, "language": language, "mode": mode,
                 "delivered": delivered}
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                log.warning("could not write history", exc_info=True)
        return entry

    def entries(self) -> list:
        """Newest first."""
        with self._lock:
            if not self.path.exists():
                return []
            out = []
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
            for line in lines:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        if len(out) > KEEP * 1.2:
            self._rewrite(out[-KEEP:])
            out = out[-KEEP:]
        # By time, and by order written where two share a clock tick.
        order = sorted(range(len(out)), key=lambda i: (out[i].get("ts", 0), i), reverse=True)
        return [out[i] for i in order]

    def delete(self, entry_id: str) -> None:
        kept = [e for e in reversed(self.entries()) if e.get("id") != entry_id]
        self._rewrite(kept)

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                log.warning("could not clear history", exc_info=True)

    def _rewrite(self, entries: list) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                                       for e in entries), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                log.warning("could not rewrite history", exc_info=True)

    def stats(self) -> dict:
        items = [e for e in self.entries() if e.get("mode") != "command"]
        words = sum(e.get("words", 0) for e in items)
        seconds = sum(e.get("seconds", 0.0) for e in items)
        week_ago = time.time() - 7 * 86400
        week = sum(e.get("words", 0) for e in items if e.get("ts", 0) >= week_ago)
        typing_s = words / TYPING_WPM * 60
        return {
            "dictations": len(items),
            "words": words,
            "words_week": week,
            "wpm": round(words / (seconds / 60)) if seconds > 5 else 0,
            "saved_minutes": max(0, round((typing_s - seconds) / 60)),
            "streak_days": _streak(items),
        }


def _streak(items: list) -> int:
    """Consecutive days, ending today or yesterday, with at least one dictation."""
    days = {time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0))) for e in items}
    n, t = 0, time.time()
    if time.strftime("%Y-%m-%d", time.localtime(t)) not in days:
        t -= 86400
    while time.strftime("%Y-%m-%d", time.localtime(t)) in days:
        n += 1
        t -= 86400
    return n
