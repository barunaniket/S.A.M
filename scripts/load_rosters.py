"""
load_rosters.py
---------------
Idempotent loader for the synthetic demo rosters.

Reads:
  data/students.csv  (email, full_name, batch, srn, phone)
  data/faculty.csv   (email, full_name, department, office_location, phone)
  data/timetable.csv (faculty_email, day_of_week, start_time, end_time,
                       subject, room, batch)              [optional]

Writes:
  - users rows (UPSERT by email; preserves any existing telegram_chat_id /
    OAuth tokens so re-running after live onboarding is safe)
  - user_groups rows (one per distinct student batch) + user_group_members
    (membership refreshed each run)
  - timetable_entries (replaced for any faculty in the CSV)

Usage:

    python scripts/load_rosters.py                      # students + faculty
    python scripts/load_rosters.py --timetables         # also load timetable.csv

Re-running with the same CSVs is a no-op (other than touching `updated_at`).
Edit a CSV and re-run to apply changes.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import DictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STUDENTS = REPO_ROOT / "data" / "students.csv"
DEFAULT_FACULTY = REPO_ROOT / "data" / "faculty.csv"
DEFAULT_TIMETABLE = REPO_ROOT / "data" / "timetable.csv"

DEFAULT_ORG_ID = 1


# ---------------------------------------------------------------------------
# CSV readers
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Roster file not found: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            for row in reader
        ]


# ---------------------------------------------------------------------------
# Org bootstrap (matches seed_demo.ensure_org)
# ---------------------------------------------------------------------------

def ensure_org(cur, org_id: int) -> None:
    cur.execute("SELECT id FROM organizations WHERE id = %s;", (org_id,))
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO organizations (id, name, invite_code, domain_whitelist)
        VALUES (%s, 'S.A.M Demo Org', 'DEMO-ORG', '@example.edu')
        ON CONFLICT (id) DO NOTHING;
        """,
        (org_id,),
    )


# ---------------------------------------------------------------------------
# User upsert
# ---------------------------------------------------------------------------

def _safe_phone(cur, email: str, phone: Optional[str]) -> Optional[str]:
    """
    Phones must be globally unique (idx_users_phone). For synthetic CSV
    rosters, that's a footgun — every accidental collision crashes the
    whole loader. So: keep the phone iff no OTHER user already owns it.
    """
    if not phone:
        return None
    cur.execute(
        "SELECT email FROM users WHERE phone_number = %s LIMIT 1;",
        (phone,),
    )
    row = cur.fetchone()
    if not row:
        return phone
    if row["email"].lower() == (email or "").lower():
        return phone
    return None


def upsert_student(cur, org_id: int, row: Dict[str, str]) -> int:
    phone = _safe_phone(cur, row["email"], row.get("phone") or None)
    cur.execute(
        """
        INSERT INTO users (org_id, email, full_name, role, phone_number,
                           department, batch)
        VALUES (%s, %s, %s, 'STUDENT', %s, 'CSE', %s)
        ON CONFLICT (email) DO UPDATE
            SET full_name    = EXCLUDED.full_name,
                role         = 'STUDENT',
                phone_number = EXCLUDED.phone_number,
                batch        = EXCLUDED.batch,
                updated_at   = NOW()
        RETURNING id;
        """,
        (org_id, row["email"], row["full_name"], phone, row["batch"]),
    )
    return cur.fetchone()["id"]


def upsert_faculty(cur, org_id: int, row: Dict[str, str]) -> Tuple[int, str]:
    role = "SUPER_ADMIN" if row["email"].lower() == "spoc@example.edu" \
        else ("BOOKING_AUTHORITY" if (row.get("department") or "").lower() == "admin"
              and row["email"].lower() != "spoc@example.edu"
              else "FACULTY")
    phone = _safe_phone(cur, row["email"], row.get("phone") or None)
    cur.execute(
        """
        INSERT INTO users (org_id, email, full_name, role, phone_number,
                           department, office_location)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (email) DO UPDATE
            SET full_name        = EXCLUDED.full_name,
                role             = EXCLUDED.role,
                phone_number     = EXCLUDED.phone_number,
                department       = EXCLUDED.department,
                office_location  = EXCLUDED.office_location,
                updated_at       = NOW()
        RETURNING id;
        """,
        (org_id, row["email"], row["full_name"], role, phone,
         row.get("department") or None,
         row.get("office_location") or None),
    )
    return cur.fetchone()["id"], role


# ---------------------------------------------------------------------------
# user_groups (one per batch)
# ---------------------------------------------------------------------------

def refresh_class_groups(cur, org_id: int, created_by: int,
                         students_by_batch: Dict[str, List[int]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for batch, student_ids in students_by_batch.items():
        cur.execute(
            """
            INSERT INTO user_groups (org_id, name, description, created_by)
            VALUES (%s, %s, 'Roster-loaded class group', %s)
            ON CONFLICT (org_id, name) DO UPDATE
                SET description = EXCLUDED.description
            RETURNING id;
            """,
            (org_id, batch, created_by),
        )
        gid = cur.fetchone()["id"]
        out[batch] = gid

        # Refresh membership: drop only this group's members, re-insert.
        cur.execute(
            "DELETE FROM user_group_members WHERE group_id = %s;",
            (gid,),
        )
        for sid in student_ids:
            cur.execute(
                """
                INSERT INTO user_group_members (group_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (gid, sid),
            )
    return out


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------

def load_timetables(cur, org_id: int, faculty_ids: Dict[str, int],
                    timetable_path: Path) -> int:
    rows = _read_csv(timetable_path)
    if not rows:
        return 0

    # Group by faculty so we can replace in one pass per faculty.
    by_faculty: Dict[str, List[Dict[str, str]]] = {}
    for r in rows:
        by_faculty.setdefault(r["faculty_email"].lower(), []).append(r)

    inserted = 0
    for email, entries in by_faculty.items():
        uid = faculty_ids.get(email)
        if not uid:
            print(f"   ! timetable row references unknown faculty {email!r} — skipped")
            continue
        # Wipe any prior roster-loaded entries for this faculty.
        cur.execute(
            "DELETE FROM timetable_entries WHERE user_id = %s AND source = 'roster';",
            (uid,),
        )
        for e in entries:
            cur.execute(
                """
                INSERT INTO timetable_entries
                    (org_id, user_id, day_of_week, start_time, end_time,
                     subject, room, batch, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'roster');
                """,
                (org_id, uid, int(e["day_of_week"]),
                 e["start_time"], e["end_time"],
                 e.get("subject") or None,
                 e.get("room") or None,
                 e.get("batch") or None),
            )
            inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _connect():
    try:
        return psycopg2.connect(Config.DATABASE_URL, cursor_factory=DictCursor)
    except OperationalError as err:
        print(f"❌ Could not connect to DB: {err}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--students", type=Path, default=DEFAULT_STUDENTS)
    parser.add_argument("--faculty",  type=Path, default=DEFAULT_FACULTY)
    parser.add_argument("--timetables", action="store_true",
                        help=f"Also load {DEFAULT_TIMETABLE.name}")
    parser.add_argument("--timetable-file", type=Path, default=DEFAULT_TIMETABLE)
    parser.add_argument("--org-id", type=int, default=DEFAULT_ORG_ID)
    args = parser.parse_args()

    students = _read_csv(args.students)
    faculty = _read_csv(args.faculty)

    print(f"📥 Loading rosters into org_id={args.org_id}…")
    print(f"   students: {len(students)} from {args.students.name}")
    print(f"   faculty:  {len(faculty)} from {args.faculty.name}")

    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                ensure_org(cur, args.org_id)

                faculty_ids: Dict[str, int] = {}
                spoc_id = None
                for row in faculty:
                    uid, role = upsert_faculty(cur, args.org_id, row)
                    faculty_ids[row["email"].lower()] = uid
                    if role == "SUPER_ADMIN":
                        spoc_id = uid
                    print(f"   ✓ faculty: {row['full_name']:<25} id={uid}  role={role}")

                if spoc_id is None:
                    # Fall back to the first faculty as group creator if SPOC missing.
                    spoc_id = next(iter(faculty_ids.values()))

                students_by_batch: Dict[str, List[int]] = {}
                for row in students:
                    sid = upsert_student(cur, args.org_id, row)
                    students_by_batch.setdefault(row["batch"], []).append(sid)
                print(f"   ✓ students: {len(students)} upserted across "
                      f"{len(students_by_batch)} batch(es)")

                groups = refresh_class_groups(cur, args.org_id, spoc_id,
                                              students_by_batch)
                for batch, gid in groups.items():
                    print(f"   ✓ user_group {batch}: id={gid} "
                          f"({len(students_by_batch[batch])} member(s))")

                if args.timetables:
                    rows = load_timetables(cur, args.org_id, faculty_ids,
                                           args.timetable_file)
                    print(f"   ✓ timetable: {rows} entries inserted from "
                          f"{args.timetable_file.name}")

        print("\n✅ Roster load complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
