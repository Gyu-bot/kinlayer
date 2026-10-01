#!/usr/bin/env python3
"""Apply a private, guarded schema-conversion manifest. Dry-run by default."""
import argparse
import json
from pathlib import Path

from sqlalchemy import text

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.services.memory_migration import MemoryDataMigration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with create_session_maker(Settings())() as session:
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("SET LOCAL statement_timeout = '120s'"))
        version = session.scalar(text("SELECT version_num FROM alembic_version"))
        if version != "20261001_0012":
            raise SystemExit("Run the additive 0012 schema migration before converting records.")
        result = MemoryDataMigration(session).run(json.loads(args.manifest.read_text()), apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
