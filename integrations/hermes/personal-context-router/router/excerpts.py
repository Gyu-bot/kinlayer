from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Excerpt:
    label: str
    path: Path
    text: str


def _section_text(markdown: str, heading: str) -> str:
    wanted = heading.strip().lower()
    lines = markdown.splitlines()
    start = -1
    start_level = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if stripped.lower() == wanted:
            start = idx
            start_level = len(stripped) - len(stripped.lstrip("#"))
            break
    if start < 0:
        return ""

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        stripped = lines[idx].strip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        if level <= start_level:
            end = idx
            break
    return "\n".join(lines[start:end]).strip()


def _bounded(text: str, budget_tokens: int) -> str:
    limit = max(300, int(budget_tokens or 300) * 4)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[excerpt truncated]"


def excerpt_markdown_sections(
    path: Path,
    sections: Iterable[str],
    budget_tokens: int,
    label: str | None = None,
) -> Excerpt | None:
    if not path.exists() or not path.is_file():
        return None
    markdown = path.read_text(encoding="utf-8", errors="replace")
    pieces = []
    for section in sections:
        text = _section_text(markdown, section)
        if text:
            pieces.append(text)
    if not pieces:
        return None
    return Excerpt(label=label or path.name, path=path, text=_bounded("\n\n".join(pieces), budget_tokens))
