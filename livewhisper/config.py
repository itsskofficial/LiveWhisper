"""Config load/save that keeps the comments intact.

The GUI writes this file back on every save. Plain PyYAML would round-trip the
values fine but strip every explanatory comment, so the file degrades into bare
keys the first time you touch a setting. ruamel's round-trip loader preserves
them.
"""

from __future__ import annotations

import io
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # never re-wrap long prompt lines


def load(path: Path | str) -> dict:
    with open(path, encoding="utf-8") as f:
        return _yaml.load(f)


def save(path: Path | str, data: dict) -> None:
    # Serialise fully before touching the file, so a dump error cannot leave a
    # truncated config behind.
    buf = io.StringIO()
    _yaml.dump(data, buf)
    Path(path).write_text(buf.getvalue(), encoding="utf-8")


def write_env(path: Path | str, key: str, value: str) -> None:
    """Set one key in a .env file, leaving every other line untouched."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def literal_block(text: str):
    """Force a multi-line string to dump as a `|` block rather than escaped."""
    from ruamel.yaml.scalarstring import LiteralScalarString, SingleQuotedScalarString

    text = text.replace("\r\n", "\n")
    if "\n" in text:
        # Trailing newline keeps the `|` form; without it ruamel emits `|-`.
        return LiteralScalarString(text if text.endswith("\n") else text + "\n")
    return SingleQuotedScalarString(text)
