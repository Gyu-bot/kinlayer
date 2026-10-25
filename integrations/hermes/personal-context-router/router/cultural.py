from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping


CULTURAL_ITEM_FIELDS = (
    "item_title",
    "item_aliases",
    "medium",
    "season_or_version",
    "edition_or_dlc",
    "platform",
    "experience_state",
    "reaction",
    "reaction_reason",
    "comparison_target",
    "mentioned_characters_or_roles",
    "resolution_status",
    "resolution_source",
    "resolution_confidence",
)

_TEXT_FIELDS = {
    "item_title",
    "medium",
    "season_or_version",
    "edition_or_dlc",
    "platform",
    "experience_state",
    "reaction",
    "reaction_reason",
    "comparison_target",
    "resolution_status",
    "resolution_source",
}

_LIST_FIELDS = {
    "item_aliases",
    "mentioned_characters_or_roles",
}

CANONICAL_RESOLUTION_STATUSES = {
    "explicit_current",
    "resolved_prior_user",
    "not_applicable",
}

SUPPORTED_CULTURAL_MEDIA = {
    "game",
    "youtube_content",
    "film",
    "drama",
    "story_media",
    "book",
    "web_novel",
    "manga",
    "anime",
    "music",
}

_CULTURAL_MEDIUM_ALIASES = {
    "video_game": "game",
    "game_demo": "game",
    "demo": "game",
    "dlc": "game",
    "expansion": "game",
    "platform_edition": "game",
    "movie": "film",
    "tv_series": "drama",
    "series": "drama",
    "youtube": "youtube_content",
    "webnovel": "web_novel",
}


def canonical_cultural_medium(value: Any) -> str:
    normalized = re.sub(r"[\s-]+", "_", str(value or "").strip().casefold())
    return _CULTURAL_MEDIUM_ALIASES.get(normalized, normalized)


def supported_cultural_medium(value: Any) -> bool:
    return canonical_cultural_medium(value) in SUPPORTED_CULTURAL_MEDIA


def normalize_cultural_item(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}

    item: dict[str, Any] = {}
    for field in CULTURAL_ITEM_FIELDS:
        value = raw.get(field)
        if field in _TEXT_FIELDS:
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if field == "medium" and text:
                text = canonical_cultural_medium(text)
            if text:
                item[field] = text
            continue
        if field in _LIST_FIELDS:
            if not isinstance(value, list):
                continue
            items: list[str] = []
            seen: set[str] = set()
            for candidate in value:
                text = re.sub(r"\s+", " ", str(candidate or "")).strip()
                key = text.casefold()
                if not text or key in seen:
                    continue
                seen.add(key)
                items.append(text)
                if len(items) >= 8:
                    break
            if items:
                item[field] = items
            continue
        if field == "resolution_confidence":
            try:
                confidence = float(value)
            except (TypeError, ValueError):
                continue
            item[field] = max(0.0, min(1.0, confidence))
    return item


def normalized_medium(value: Any) -> str:
    return canonical_cultural_medium(value)


def cultural_item_label(item: Mapping[str, Any]) -> str:
    parts = [str(item.get("item_title") or "").strip()]
    for field in ("season_or_version", "edition_or_dlc", "platform"):
        value = str(item.get(field) or "").strip()
        if value and value.casefold() not in {part.casefold() for part in parts if part}:
            parts.append(value)
    return " — ".join(part for part in parts if part)


def cultural_item_key(item: Mapping[str, Any]) -> str:
    values = [
        str(item.get("item_title") or ""),
        str(item.get("medium") or ""),
        str(item.get("season_or_version") or ""),
        str(item.get("edition_or_dlc") or ""),
        str(item.get("platform") or ""),
    ]
    return "|".join(re.sub(r"\s+", " ", value).strip().casefold() for value in values)


def canonical_resolution(item: Mapping[str, Any], min_confidence: float) -> bool:
    status = str(item.get("resolution_status") or "").strip().casefold()
    source = str(item.get("resolution_source") or "").strip().casefold()
    if status not in CANONICAL_RESOLUTION_STATUSES:
        return False
    if status == "not_applicable":
        return source in {"current_user_message", "none"}
    if status == "explicit_current" and source != "current_user_message":
        return False
    if status == "resolved_prior_user" and source != "prior_user_message":
        return False
    try:
        confidence = float(item.get("resolution_confidence"))
    except (TypeError, ValueError):
        return False
    return confidence >= min_confidence


def _lookup_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _structured_lookup_values(record: Mapping[str, Any]) -> list[str]:
    item = record.get("cultural_item")
    item = item if isinstance(item, Mapping) else {}
    values: list[Any] = [
        item.get("item_title"),
        item.get("medium"),
        item.get("season_or_version"),
        item.get("edition_or_dlc"),
        item.get("platform"),
        item.get("comparison_target"),
    ]
    for field in ("item_aliases", "mentioned_characters_or_roles"):
        field_values = item.get(field)
        if isinstance(field_values, list):
            values.extend(field_values)
    subjects = record.get("subjects")
    if isinstance(subjects, list):
        values.extend(subjects)
    return [normalized for value in values if (normalized := _lookup_text(value))]


def lookup_cultural_evidence(
    ledger_path: str | Path,
    query: str,
    max_records: int = 3,
) -> list[dict[str, Any]]:
    """Bounded structured lookup for a specific/recent cultural item.

    Only structured identity fields and subjects participate. Summary/derived text is
    intentionally excluded so this cannot become a broad semantic scan of the ledger.
    """
    normalized_query = _lookup_text(query)
    if not normalized_query:
        return []
    try:
        limit = max(1, min(3, int(max_records)))
    except (TypeError, ValueError):
        limit = 3

    query_terms = {
        term for term in re.split(r"[^\w]+", normalized_query, flags=re.UNICODE) if len(term) >= 2
    }
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    path = Path(ledger_path).expanduser()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []

    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("domain") != "cultural_taste":
            continue
        values = _structured_lookup_values(record)
        if not values:
            continue
        exact = sum(value == normalized_query for value in values)
        phrase = sum(
            normalized_query in value or value in normalized_query
            for value in values
            if len(value) >= 2
        )
        term_hits = sum(
            1 for term in query_terms if any(term in value for value in values)
        )
        score = exact * 100 + phrase * 20 + term_hits * 5
        if score:
            ranked.append((score, line_number, record))

    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [record for _, _, record in ranked[:limit]]
