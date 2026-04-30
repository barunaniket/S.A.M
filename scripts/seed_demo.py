"""
Seed the database with the demo cast for the 2-day prototype walk-through.

Personas (single org_id=1):
  - SPOC          - Aniket Barun           (you, the presenter)
  - FACULTY       - Dr Priya Sharma        Cabin: Faculty Block, Room 312
  - FACULTY       - Prof Rahul Kumar       Cabin: Faculty Block, Room 308
  - BOOKING_AUTH  - Meera Iyer             Office: Admin Block, Room 5
  - STUDENT       - Arjun Patel            Batch: CSE-3A
  - STUDENT       - Riya Mehta             Batch: CSE-3A   (UNPAIRED — for live onboarding demo)

Each faculty gets a believable Mon/Tue/Wed timetable so the period-aware
"where is Prof X during 4th period?" lookup has data to return.

A user_group "CSE-3A" is created with the two students as members so the
"cancel today's class" broadcast lands somewhere visible.

Run AFTER all migrations (v3 → v10).

    python scripts/seed_demo.py
"""

import os
import sys
from datetime import time
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import DictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


# ---------------------------------------------------------------------------
# Configuration knobs — override via env so you can re-seed without editing.
# ---------------------------------------------------------------------------

ORG_ID = int(os.getenv("DEMO_ORG_ID", "1"))

SPOC_EMAIL    = os.getenv("DEMO_SPOC_EMAIL",  "spoc@example.edu")
SPOC_NAME     = os.getenv("DEMO_SPOC_NAME",   "Aniket Barun")
SPOC_PHONE    = os.getenv("DEMO_SPOC_PHONE",  "+919800000000")

# Set DEMO_SPOC_TG_CHAT_ID and DEMO_RIYA_TG_CHAT_ID via env if you want
# the seed to pre-pair them (skips the live OAuth dance for the SPOC).
SPOC_TG_CHAT  = os.getenv("DEMO_SPOC_TG_CHAT_ID")
RIYA_TG_CHAT  = os.getenv("DEMO_RIYA_TG_CHAT_ID")  # set ONLY if you want Riya pre-paired


# ---------------------------------------------------------------------------
# Cast
# ---------------------------------------------------------------------------

DEMO_USERS = [
    {
        "email":  SPOC_EMAIL,
        "name":   SPOC_NAME,
        "role":   "SUPER_ADMIN",
        "phone":  SPOC_PHONE,
        "dept":   "Admin",
        "batch":  None,
        "office": "SPOC Office, Admin Block",
        "tg_chat_id": int(SPOC_TG_CHAT) if SPOC_TG_CHAT else None,
    },
    {
        "email":  "priya.sharma@example.edu",
        "name":   "Dr Priya Sharma",
        "role":   "FACULTY",
        "phone":  "+919800000001",
        "dept":   "CSE",
        "batch":  None,
        "office": "Faculty Block, Room 312",
        "tg_chat_id": None,
    },
    {
        "email":  "rahul.kumar@example.edu",
        "name":   "Prof Rahul Kumar",
        "role":   "FACULTY",
        "phone":  "+919800000002",
        "dept":   "CSE",
        "batch":  None,
        "office": "Faculty Block, Room 308",
        "tg_chat_id": None,
    },
    {
        "email":  "meera.iyer@example.edu",
        "name":   "Meera Iyer",
        "role":   "BOOKING_AUTHORITY",
        "phone":  "+919800000003",
        "dept":   "Admin",
        "batch":  None,
        "office": "Admin Block, Room 5",
        "tg_chat_id": None,
    },
    {
        "email":  "arjun.patel@example.edu",
        "name":   "Arjun Patel",
        "role":   "STUDENT",
        "phone":  "+919800000004",
        "dept":   "CSE",
        "batch":  "CSE-3A",
        "office": None,
        "tg_chat_id": None,
    },
    {
        "email":  "riya.mehta@example.edu",
        "name":   "Riya Mehta",
        "role":   "STUDENT",
        "phone":  "+919800000005",
        "dept":   "CSE",
        "batch":  "CSE-3A",   # pre-set so the live onboarding skips the batch question
        "office": None,
        "tg_chat_id": int(RIYA_TG_CHAT) if RIYA_TG_CHAT else None,
    },
]


# Bell schedule used by src/utils/periods.py — keep these in sync.
P = {
    1: (time(9, 0),  time(9, 50)),
    2: (time(10, 0), time(10, 50)),
    3: (time(11, 0), time(11, 50)),
    4: (time(12, 0), time(12, 50)),
    5: (time(14, 0), time(14, 50)),
    6: (time(15, 0), time(15, 50)),
    7: (time(16, 0), time(16, 50)),
    8: (time(17, 0), time(17, 50)),
}

# Mon = 0, Tue = 1, Wed = 2, Thu = 3, Fri = 4
TIMETABLE = {
    "priya.sharma@example.edu": [
        # Mon
        (0, P[1], "DSA",          "Room 204", "CSE-3A"),
        (0, P[3], "Algorithms",   "Room 204", "CSE-3A"),
        (0, P[4], "DSA Lab",      "Lab 2",    "CSE-3A"),
        # Tue
        (1, P[2], "DSA",          "Room 204", "CSE-3B"),
        (1, P[5], "Algorithms",   "Room 204", "CSE-3A"),
        # Wed
        (2, P[1], "DSA",          "Room 204", "CSE-3A"),
        (2, P[6], "Office hours", "Faculty Block 312", None),
    ],
    "rahul.kumar@example.edu": [
        # Mon
        (0, P[2], "Compilers",    "Room 207", "CSE-4A"),
        (0, P[5], "Compilers",    "Room 207", "CSE-4B"),
        # Tue
        (1, P[3], "Compilers",    "Room 207", "CSE-4A"),
        (1, P[4], "Compilers Lab","Lab 3",    "CSE-4A"),
        # Wed
        (2, P[2], "Compilers",    "Room 207", "CSE-4B"),
        (2, P[6], "Compilers",    "Room 207", "CSE-4A"),
    ],
}


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def _connect():
    try:
        return psycopg2.connect(Config.DATABASE_URL, cursor_factory=DictCursor)
    except OperationalError as err:
        print(f"❌ Could not connect to DB: {err}")
        sys.exit(1)


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


def upsert_user(cur, org_id: int, u: dict) -> int:
    cur.execute(
        """
        INSERT INTO users (org_id, email, full_name, role, phone_number,
                           department, batch, office_location,
                           telegram_chat_id)
        VALUES (%(org_id)s, %(email)s, %(name)s, %(role)s, %(phone)s,
                %(dept)s, %(batch)s, %(office)s, %(tg_chat_id)s)
        ON CONFLICT (email) DO UPDATE
            SET full_name        = EXCLUDED.full_name,
                role             = EXCLUDED.role,
                phone_number     = EXCLUDED.phone_number,
                department       = EXCLUDED.department,
                batch            = EXCLUDED.batch,
                office_location  = EXCLUDED.office_location,
                telegram_chat_id = COALESCE(EXCLUDED.telegram_chat_id, users.telegram_chat_id),
                updated_at       = NOW()
        RETURNING id;
        """,
        {**u, "org_id": org_id},
    )
    return cur.fetchone()["id"]


def seed_timetable(cur, org_id: int, user_id: int, email: str) -> int:
    entries = TIMETABLE.get(email)
    if not entries:
        return 0
    # Wipe any prior demo entries for this user so re-running the seed is safe.
    cur.execute(
        "DELETE FROM timetable_entries WHERE user_id = %s AND source = 'demo_seed';",
        (user_id,),
    )
    rows = 0
    for day, (start_t, end_t), subject, room, batch in entries:
        cur.execute(
            """
            INSERT INTO timetable_entries
                (org_id, user_id, day_of_week, start_time, end_time,
                 subject, room, batch, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'demo_seed');
            """,
            (org_id, user_id, day, start_t, end_t, subject, room, batch),
        )
        rows += 1
    return rows


def seed_class_group(cur, org_id: int, created_by: int,
                     student_ids: list[int]) -> int:
    cur.execute(
        """
        INSERT INTO user_groups (org_id, name, description, created_by)
        VALUES (%s, 'CSE-3A', 'Demo class group', %s)
        ON CONFLICT (org_id, name) DO UPDATE SET description = EXCLUDED.description
        RETURNING id;
        """,
        (org_id, created_by),
    )
    group_id = cur.fetchone()["id"]
    for sid in student_ids:
        cur.execute(
            """
            INSERT INTO user_group_members (group_id, user_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING;
            """,
            (group_id, sid),
        )
    return group_id


def main() -> None:
    conn = _connect()
    print(f"🌱 Seeding demo cast into org_id={ORG_ID}…")
    try:
        with conn:
            with conn.cursor() as cur:
                ensure_org(cur, ORG_ID)

                user_ids = {}
                for u in DEMO_USERS:
                    uid = upsert_user(cur, ORG_ID, u)
                    user_ids[u["email"]] = uid
                    note = ""
                    if u.get("tg_chat_id"):
                        note = f"  (Telegram pre-paired: {u['tg_chat_id']})"
                    print(f"  ✓ {u['name']:<22} id={uid}  role={u['role']}{note}")

                tt_rows = 0
                for email in TIMETABLE:
                    if email in user_ids:
                        tt_rows += seed_timetable(cur, ORG_ID, user_ids[email], email)
                print(f"  ✓ {tt_rows} timetable entries inserted")

                students = [user_ids[e] for e in
                            ("arjun.patel@example.edu", "riya.mehta@example.edu")
                            if e in user_ids]
                spoc_id = user_ids[SPOC_EMAIL]
                gid = seed_class_group(cur, ORG_ID, spoc_id, students)
                print(f"  ✓ user_group CSE-3A id={gid} with {len(students)} member(s)")

        print("\n✅ Demo seed complete.")
        if not SPOC_TG_CHAT:
            print("\nNote: DEMO_SPOC_TG_CHAT_ID is unset — pair the SPOC's Telegram")
            print("via /app/settings → Telegram → Connect Telegram → /start CODE")
            print("OR re-run with DEMO_SPOC_TG_CHAT_ID=12345 in the env.")
        if not RIYA_TG_CHAT:
            print("Riya is left unpaired by design — onboard her LIVE during the demo.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
