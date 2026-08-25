"""Notes from system audio.

The capture side already exists - LiveWhisper records system audio and the mic
on separate channels. This adds the part that makes it useful: a running note
you can append transcribed chunks to, with everything kept on disk as plain
Markdown so it stays readable without this app.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Note:
    title: str
    path: Path
    started: datetime
    entries: list = field(default_factory=list)

    def append(self, text: str, speaker: str = "") -> None:
        if not text.strip():
            return
        stamp = datetime.now()
        elapsed = stamp - self.started
        mins, secs = divmod(int(elapsed.total_seconds()), 60)
        self.entries.append({"at": f"{mins:02d}:{secs:02d}",
                             "speaker": speaker, "text": text.strip()})
        self.flush()

    def flush(self) -> None:
        lines = [f"# {self.title}\n",
                 f"\n_{self.started.strftime('%Y-%m-%d %H:%M')}_\n\n"]
        for e in self.entries:
            who = f"**{e['speaker']}** " if e["speaker"] else ""
            lines.append(f"`{e['at']}` {who}{e['text']}\n\n")
        try:
            self.path.write_text("".join(lines), encoding="utf-8")
        except Exception:
            log.warning("could not write note %s", self.path, exc_info=True)

    @property
    def word_count(self) -> int:
        return sum(len(e["text"].split()) for e in self.entries)


class NoteBook:
    """One active note at a time; finished notes stay on disk."""

    def __init__(self, directory: Path | None = None):
        self.dir = directory or (ROOT / "notes")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.active: Note | None = None

    def start(self, title: str | None = None) -> Note:
        now = datetime.now()
        title = (title or f"Note {now.strftime('%d %b %H:%M')}").strip()
        slug = re.sub(r"[^\w\- ]", "", title).strip().replace(" ", "-")[:50]
        path = self.dir / f"{now.strftime('%Y-%m-%d_%H%M%S')}_{slug or 'note'}.md"
        self.active = Note(title=title, path=path, started=now)
        self.active.flush()
        log.info("started note %s", path.name)
        return self.active

    def append(self, text: str, speaker: str = "") -> Note:
        if self.active is None:
            self.start()
        self.active.append(text, speaker)
        return self.active

    def stop(self) -> Note | None:
        note, self.active = self.active, None
        if note:
            note.flush()
            log.info("closed note %s (%d words)", note.path.name, note.word_count)
        return note

    def recent(self, limit: int = 20) -> list[Path]:
        return sorted(self.dir.glob("*.md"),
                      key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
