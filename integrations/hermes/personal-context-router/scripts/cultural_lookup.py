#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from router.cultural import lookup_cultural_evidence

from router.config import hermes_home
DEFAULT_LEDGER = hermes_home() / "knowledge" / "gyurin" / "evidence" / "cultural-taste.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded structured lookup of cultural-taste item evidence."
    )
    parser.add_argument("query", help="Title, alias, character/role, season/version, DLC, or platform")
    parser.add_argument("--max-records", type=int, default=3)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()

    records = lookup_cultural_evidence(
        args.ledger,
        args.query,
        max_records=args.max_records,
    )
    print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
