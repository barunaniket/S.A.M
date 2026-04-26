import random
import string
from datetime import datetime, timedelta
from src.utils.db_handler import get_db


ORG_COUNT = 5
USERS_PER_ORG = 10
MEETINGS_PER_ORG = 400


def random_string(length=6):
    return ''.join(random.choices(string.ascii_uppercase, k=length))


def seed():
    print("🌱 Seeding multi-tenant database...")

    # Create Organizations
    org_ids = []
    with get_db(1) as cur:  # Temporary org_id for bootstrap (RLS disabled for organizations)
        for i in range(ORG_COUNT):
            invite = f"ORG-{random_string()}"
            cur.execute("""
                INSERT INTO organizations (name, invite_code, domain_whitelist)
                VALUES (%s, %s, %s)
                RETURNING id;
            """, (f"Department {i+1}", invite, "@example.edu"))
            org_ids.append(cur.fetchone()['id'])

    # Create Users per Org
    for org_id in org_ids:
        with get_db(org_id) as cur:
            for i in range(USERS_PER_ORG):
                cur.execute("""
                    INSERT INTO users (org_id, email, full_name, role)
                    VALUES (%s, %s, %s, %s);
                """, (
                    org_id,
                    f"user{i}_{org_id}@example.edu",
                    f"Faculty {i} Org {org_id}",
                    "FACULTY"
                ))

    # Create Meetings
    for org_id in org_ids:
        with get_db(org_id) as cur:
            cur.execute("SELECT id FROM users WHERE org_id = %s;", (org_id,))
            user_ids = [u['id'] for u in cur.fetchall()]

            for _ in range(MEETINGS_PER_ORG):
                user_id = random.choice(user_ids)
                start_time = datetime.utcnow() + timedelta(days=random.randint(-30, 30))
                end_time = start_time + timedelta(minutes=30)

                cur.execute("""
                    INSERT INTO meetings (org_id, user_id, student_email,
                                          start_time, end_time, status, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (
                    org_id,
                    user_id,
                    f"student{random.randint(1,1000)}@mail.com",
                    start_time,
                    end_time,
                    random.choice(["PENDING", "CONFIRMED", "CANCELLED"]),
                    "Discussion about coursework"
                ))

    print("✅ Seeding complete!")


if __name__ == "__main__":
    seed()
