from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import is_under_gyurin_knowledge_root
from .cultural import cultural_item_label, normalized_medium


RAW_OR_SECRET_RE = re.compile(
    r"(?is)(raw transcript|verbatim transcript|BEGIN TRANSCRIPT|api[_-]?key|token|secret|password|credential)"
)

MAX_CONTEXT_UPDATES_PER_SECTION = 12


@dataclass
class MarkdownWriteRequest:
    domain: str
    target_path: Path
    section: str
    entry: str
    allowlist: list[Path]
    backup_dir: Path
    metadata: dict[str, Any] | None = None


@dataclass
class MarkdownWriteResult:
    wrote: bool
    reason: str
    backup_path: Path | None = None


def _allowed_path(path: Path, allowlist: list[Path]) -> bool:
    resolved = path.resolve()
    if not is_under_gyurin_knowledge_root(resolved):
        return False
    return any(resolved == allowed.resolve() for allowed in allowlist)


def _append_under_section(
    markdown: str, section: str, entry: str, metadata: dict[str, Any] | None = None,
) -> str:
    heading = f"## {section}".strip()
    lines = markdown.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().lower() != heading.lower():
            continue
        insert_at = len(lines)
        for probe in range(idx + 1, len(lines)):
            if lines[probe].startswith("## "):
                insert_at = probe
                break
        new_lines = lines[:insert_at]
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(entry.rstrip())
        context_entries = set((metadata or {}).get("context_entries", []))
        if entry in context_entries or entry.lstrip().startswith("- Context update ("):
            new_lines = _prune_context_update_lines(new_lines, idx + 1, context_entries)
        new_lines.extend(lines[insert_at:])
        return "\n".join(new_lines).rstrip() + "\n"
    return markdown.rstrip() + f"\n\n{heading}\n{entry.rstrip()}\n"


def _prune_context_update_lines(
    lines: list[str], section_body_start: int, context_entries: set[str] | None = None,
) -> list[str]:
    update_indices = [
        idx
        for idx in range(section_body_start, len(lines))
        if lines[idx].lstrip().startswith("- Context update (")
        or lines[idx] in (context_entries or set())
    ]
    overflow = len(update_indices) - MAX_CONTEXT_UPDATES_PER_SECTION
    if overflow <= 0:
        return lines
    remove = set(update_indices[:overflow])
    return [line for idx, line in enumerate(lines) if idx not in remove]


def _normalized_item_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _bold_item_label(line: str) -> str:
    match = re.match(r"^\s*-\s+\*\*(.+?)\*\*", line or "")
    return match.group(1).strip() if match else ""


def _cultural_line_key(line: str) -> str:
    label = _normalized_item_label(_bold_item_label(line))
    medium_match = re.match(r"^\s*-\s+\*\*.+?\*\*\s*\(([^;)]+)", line or "")
    medium = normalized_medium(medium_match.group(1)) if medium_match else ""
    return f"{medium}|{label}"


def _upsert_cultural_item(
    markdown: str,
    section: str,
    entry: str,
    metadata: dict[str, Any],
) -> str:
    heading = f"## {section}".strip()
    lines = markdown.splitlines()
    heading_index = next(
        (idx for idx, line in enumerate(lines) if line.strip().casefold() == heading.casefold()),
        None,
    )
    if heading_index is None:
        return markdown.rstrip() + f"\n\n{heading}\n{entry.rstrip()}\n"

    section_end = next(
        (
            idx
            for idx in range(heading_index + 1, len(lines))
            if lines[idx].startswith("## ")
        ),
        len(lines),
    )
    item = metadata.get("cultural_item") if isinstance(metadata, dict) else {}
    wanted_label = cultural_item_label(item) if isinstance(item, dict) else _bold_item_label(entry)
    wanted_medium = normalized_medium(item.get("medium")) if isinstance(item, dict) else ""
    wanted_key = f"{wanted_medium}|{_normalized_item_label(wanted_label)}"
    duplicate_index = next(
        (
            idx
            for idx in range(heading_index + 1, section_end)
            if wanted_key and _cultural_line_key(lines[idx]) == wanted_key
        ),
        None,
    )
    if duplicate_index is not None:
        # Replace prose only. Historical provenance remains in the JSONL ledger;
        # never carry legacy inline evidence IDs into a newly rendered item.
        del lines[duplicate_index]
        section_end -= 1

    insert_at = section_end
    if insert_at > heading_index + 1 and lines[insert_at - 1].strip():
        lines.insert(insert_at, "")
        insert_at += 1
    lines.insert(insert_at, entry.rstrip())

    max_items = metadata.get("max_items_per_section", 12)
    try:
        max_items = max(1, int(max_items))
    except (TypeError, ValueError):
        max_items = 12
    section_end = next(
        (
            idx
            for idx in range(heading_index + 1, len(lines))
            if lines[idx].startswith("## ")
        ),
        len(lines),
    )
    item_indices = [
        idx
        for idx in range(heading_index + 1, section_end)
        if _bold_item_label(lines[idx])
    ]
    for idx in reversed(item_indices[: max(0, len(item_indices) - max_items)]):
        del lines[idx]
    return "\n".join(lines).rstrip() + "\n"


def _strip_person_suffix(value: str) -> str:
    text = re.sub(r"\s+", "", value or "").strip()
    for suffix in ("선생님께", "선생님", "님께", "씨랑", "님이랑", "이랑", "랑", "씨", "님"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _normalize_person_label(value: str) -> str:
    return _strip_person_suffix(value).lower()


def _relationship_candidate_subjects(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("subjects") if isinstance(metadata, dict) else []
    if not isinstance(raw, list):
        raw = []
    blocked = {
        "user", "사용자", "romanticinterest", "romantic_interest", "썸상대",
        "친구", "상대", "사람", "대화", "메시지", "답장", "추천", "지금", "오늘", "내일", "이번", "저번",
    }
    result: list[str] = []
    seen: set[str] = set()

    for item in raw:
        display = _strip_person_suffix(str(item).strip())
        norm = _normalize_person_label(display)
        if not display or not norm or norm in blocked or len(norm) < 2:
            continue
        if norm not in seen:
            seen.add(norm)
            result.append(display)
    return result


def _find_relationship_person_bounds(lines: list[str], subjects: list[str]) -> tuple[int, int] | None:
    if not subjects:
        return None
    normalized_subjects = [_normalize_person_label(subject) for subject in subjects]
    normalized_subjects = [subject for subject in normalized_subjects if subject]
    if not normalized_subjects:
        return None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("### "):
            continue
        heading = stripped[4:].strip()
        heading_norm = _normalize_person_label(heading)
        if not any(subject in heading_norm or heading_norm in subject for subject in normalized_subjects):
            continue
        end = len(lines)
        for probe in range(idx + 1, len(lines)):
            if lines[probe].startswith("### ") or lines[probe].startswith("## "):
                end = probe
                break
        return idx, end
    return None


def _relationship_map_bounds(lines: list[str]) -> tuple[int, int] | None:
    for idx, line in enumerate(lines):
        if line.strip().lower() != "## relationship map":
            continue
        end = len(lines)
        for probe in range(idx + 1, len(lines)):
            if lines[probe].startswith("## "):
                end = probe
                break
        return idx, end
    return None


def _append_relationship_entry(markdown: str, entry: str, metadata: dict[str, Any]) -> str:
    # Kinlayer now owns real person-specific relationship memory. The Markdown
    # relationships file is only the gyurin-level coaching/non-person context
    # layer, so the post-turn writer must never create or update `### Person`
    # records here. Person-specific writes are routed before this function; any
    # remaining relationship-domain Markdown promotion is gyurin-level context.
    section = str((metadata or {}).get("section") or "Current Known Context").strip()
    if not section or section.lower() in {"relationship map", "recent observations"}:
        section = "Current Known Context"
    return _append_under_section(markdown, section, entry, metadata)


def _apply_domain_append(markdown: str, domain: str, section: str, entry: str, metadata: dict[str, Any] | None = None) -> str:
    if domain == "relationships":
        meta = dict(metadata or {})
        meta.setdefault("section", section)
        return _append_relationship_entry(markdown, entry, meta)
    if domain == "cultural_taste":
        return _upsert_cultural_item(markdown, section, entry, dict(metadata or {}))
    return _append_under_section(markdown, section, entry, metadata)


def append_domain_entry(request: MarkdownWriteRequest) -> MarkdownWriteResult:
    if RAW_OR_SECRET_RE.search(request.entry or ""):
        return MarkdownWriteResult(False, "blocked_raw_or_secret")
    if not _allowed_path(request.target_path, request.allowlist):
        return MarkdownWriteResult(False, "blocked_path")
    if not request.target_path.exists():
        return MarkdownWriteResult(False, "missing_target")

    request.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = request.backup_dir / f"{request.target_path.name}.{stamp}.bak"
    shutil.copy2(request.target_path, backup_path)

    current = request.target_path.read_text(encoding="utf-8", errors="replace")
    updated = _apply_domain_append(current, request.domain, request.section, request.entry, request.metadata)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{request.target_path.name}.",
        suffix=".tmp",
        dir=str(request.target_path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.replace(tmp_name, request.target_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return MarkdownWriteResult(True, "wrote", backup_path)
