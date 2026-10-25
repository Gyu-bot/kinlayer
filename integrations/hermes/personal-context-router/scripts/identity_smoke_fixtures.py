"""Generic synthetic fixtures extracted from the pre-0.15 offline harness; no live data."""
from __future__ import annotations
import importlib.util
import importlib
import argparse
import contextvars
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import stat
import sys
import tempfile
import threading
import time
import types
from contextlib import nullcontext, redirect_stdout
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

PLUGIN_MODULE_NAME = "personal_context_router_plugin"

def load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        PLUGIN_MODULE_NAME,
        PLUGIN_ROOT / "__init__.py",
        submodule_search_locations=[str(PLUGIN_ROOT)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PLUGIN_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(PLUGIN_MODULE_NAME, None)
        raise
    return module

class StaticManifestLoader:
    def __init__(self, bundle):
        self._bundle = bundle

    def load_if_changed(self, config):
        return self._bundle

def relationship_classifier(_message: str) -> dict:
    return {
        "dimensions": {
            "requires_personalization": 0.9,
            "involves_specific_person": 0.9,
            "interprets_interpersonal_context": 0.9,
            "asks_for_strategy_or_wording": 0.9,
            "may_create_durable_user_context": 0.8,
            "generic_technical_or_factual": 0.0,
        },
        "domains": {"relationships": 0.95, "profile": 0.2},
        "tool_needs": {},
        "extraction_reason": "test_classifier",
    }

def test_manifest_bundle(tmp_home: Path):
    from personal_context_router_plugin.router.manifest import ManifestBundle

    knowledge = tmp_home / "knowledge" / "gyurin"
    evidence = knowledge / "evidence"
    relationships = knowledge / "relationships.md"
    cultural_taste = knowledge / "cultural-taste.md"
    candidate_log = evidence / "candidates.jsonl"
    evidence_log = evidence / "relationships.jsonl"
    cultural_evidence_log = evidence / "cultural-taste.jsonl"
    return ManifestBundle(
        router={
            "version": 4,
            "mode": "post_turn_memory_triage",
            "post_turn_policies": {
                "relationship_context": {
                    "when": {"domains.relationships": ">=0.70"},
                    "candidate_target": "relationships",
                    "raw_transcript_storage": "forbid",
                },
                "durable_context_candidate": {
                    "when": {"dimensions.may_create_durable_user_context": ">=0.70"},
                    "write_evidence_ledger": True,
                },
                "taste_fit": {
                    "when": {"domains.cultural_taste": ">=0.70"},
                    "candidate_target": "cultural_taste",
                    "raw_transcript_storage": "forbid",
                },
            },
        },
        domain_map={
            "version": 1,
            "base_dir": str(knowledge),
            "defaults": {
                "evidence_ledger_base_dir": str(evidence),
                "evidence_prompt_default": False,
            },
            "domains": {
                "relationships": {
                    "curated_file": str(relationships),
                    "evidence_ledger": str(evidence_log),
                    "domain_prefix": "rel",
                    "curated_only": True,
                    "activate_when": {"domains.relationships": ">=0.70"},
                    "prompt_sections": ["## Stable Patterns", "## Current Known Context"],
                    "raw_storage": "forbid",
                },
                "cultural_taste": {
                    "curated_file": str(cultural_taste),
                    "evidence_ledger": str(cultural_evidence_log),
                    "domain_prefix": "taste",
                    "curated_only": True,
                    "activate_when": {"domains.cultural_taste": ">=0.70"},
                    "prompt_sections": [
                        "## Games",
                        "## YouTube / Content",
                        "## Film / Drama / Story Media",
                        "## Books / Web Novels / Manga / Anime",
                        "## Music",
                    ],
                    "medium_to_section": {
                        "game": "Games",
                        "youtube_content": "YouTube / Content",
                        "film": "Film / Drama / Story Media",
                        "drama": "Film / Drama / Story Media",
                        "story_media": "Film / Drama / Story Media",
                        "book": "Books / Web Novels / Manga / Anime",
                        "web_novel": "Books / Web Novels / Manga / Anime",
                        "manga": "Books / Web Novels / Manga / Anime",
                        "anime": "Books / Web Novels / Manga / Anime",
                        "music": "Music",
                    },
                    "cultural_item_policy": {
                        "resolution_min_confidence": 0.75,
                        "canonical_evidence_min_confidence": 0.70,
                        "curated_promotion_min_confidence": 0.75,
                        "max_items_per_section": 12,
                    },
                },
            },
        },
        storage_policy={
            "version": 1,
            "evidence": {
                "mode": "domain_jsonl",
                "base_dir": str(evidence),
                "path_guard": str(evidence),
                "append_only": True,
            },
            "post_turn": {
                "default": {
                    "auto_write_domain_file": False,
                    "write_evidence_ledger": True,
                    "write_candidate_log": True,
                    "candidate_path": str(candidate_log),
                }
            },
            "storage_boundaries": {"raw_transcripts": "forbid"},
        },
    )
