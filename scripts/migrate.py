"""
Migration runner with a `schema_migrations` ledger.

Replaces the run-each-script-by-hand-in-the-right-order workflow documented in
CLAUDE.md. Maintains a `schema_migrations` table and, on each run, executes only
the migrations not yet recorded — in dependency order — then records them.

    python scripts/migrate.py             # apply pending migrations
    python scripts/migrate.py --status    # list applied / pending, apply nothing
    python scripts/migrate.py --mark-applied   # record all as applied without
                                               # running (for an existing DB that
                                               # was already migrated by hand)

Each migrate_*.py remains runnable standalone and is idempotent
(CREATE ... IF NOT EXISTS), so running through this ledger on a hand-migrated DB
is safe — it just back-fills the ledger. Scripts are executed exactly as
`python scripts/<name>.py` would be (via runpy), so this works whether a script
exposes main() or only an `if __name__ == "__main__"` block.

NOTE: reset_db.py and the seed/load scripts are intentionally excluded — they
are not schema migrations.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.config_loader import Config

# Ordered migration chain — must match the sequence in CLAUDE.md. The version
# id recorded in the ledger is each file's stem (e.g. "migrate_v13_spec").
MIGRATIONS = [
    "init_meetings_tables.py",
    "migrate_v3_features.py",
    "migrate_phone_and_student.py",
    "migrate_v4_foundations.py",
    "migrate_v5_timetable.py",
    "migrate_v6_academic_calendar.py",
    "migrate_v7_tasks.py",
    "migrate_v8_booking_briefing.py",
    "migrate_v9_telegram.py",
    "migrate_v10_demo.py",
    "migrate_v11_mcq.py",
    "migrate_v12_mvp.py",
    "migrate_v13_spec.py",
]

LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _connect():
    try:
        conn = psycopg2.connect(Config.DATABASE_URL)
        conn.autocommit = True
        return conn
    except OperationalError as err:
        print(f"❌ Could not connect to DB: {err}")
        sys.exit(1)


def _ensure_ledger(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(LEDGER_SQL)
        cur.execute("SELECT version FROM schema_migrations;")
        return {r[0] for r in cur.fetchall()}


def _record(conn, version: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO schema_migrations (version) VALUES (%s) "
            "ON CONFLICT (version) DO NOTHING;",
            (version,),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply pending DB migrations.")
    parser.add_argument("--status", action="store_true",
                        help="Show applied/pending and exit without applying.")
    parser.add_argument("--mark-applied", action="store_true",
                        help="Record all migrations as applied without running "
                             "them (use on a DB already migrated by hand).")
    args = parser.parse_args()

    conn = _connect()
    try:
        applied = _ensure_ledger(conn)
        pending = [m for m in MIGRATIONS if Path(m).stem not in applied]

        if args.status:
            print(f"Applied ({len(applied)}): {sorted(applied)}")
            print(f"Pending ({len(pending)}): {[Path(m).stem for m in pending]}")
            return 0

        if args.mark_applied:
            for script in pending:
                _record(conn, Path(script).stem)
            print(f"✅ Marked {len(pending)} migration(s) as applied "
                  "(none executed).")
            return 0

        if not pending:
            print("✅ Database is up to date — no pending migrations.")
            return 0

        for script in pending:
            version = Path(script).stem
            path = ROOT / "scripts" / script
            print(f"▶ applying {version} …")
            try:
                runpy.run_path(str(path), run_name="__main__")
            except SystemExit as exc:
                if exc.code not in (0, None):
                    print(f"❌ {version} exited with code {exc.code}; "
                          "stopping (no ledger entry written).")
                    return 1
            _record(conn, version)
            print(f"✓ recorded {version}")

        print(f"✅ Applied {len(pending)} migration(s).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
