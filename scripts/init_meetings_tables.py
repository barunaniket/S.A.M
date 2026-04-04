import psycopg2
from psycopg2 import OperationalError, DatabaseError
from utils.config_loader import Config


class DatabaseInitializationError(Exception):
    pass


def get_db_connection():
    try:
        return psycopg2.connect(Config.DATABASE_URL)
    except OperationalError as err:
        raise DatabaseInitializationError(
            f"Database connection failed: {err}"
        )


def create_tables(cursor):
    try:
        # ============================
        # DROP OLD TABLES (DEV ONLY)
        # ============================
        cursor.execute("""
            DROP TABLE IF EXISTS audit_logs CASCADE;
            DROP TABLE IF EXISTS meetings CASCADE;
            DROP TABLE IF EXISTS availability CASCADE;
            DROP TABLE IF EXISTS users CASCADE;
            DROP TABLE IF EXISTS organizations CASCADE;
            DROP TABLE IF EXISTS faculty CASCADE;
        """)

        # ============================
        # ORGANIZATIONS
        # ============================
        cursor.execute("""
            CREATE TABLE organizations (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                invite_code VARCHAR(20) UNIQUE NOT NULL,
                domain_whitelist VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # ============================
        # USERS
        # ============================
        cursor.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                email VARCHAR(150) UNIQUE NOT NULL,
                full_name VARCHAR(100) NOT NULL,
                role VARCHAR(20) CHECK (role IN ('ADMIN', 'FACULTY')) NOT NULL,
                google_refresh_token TEXT,
                is_onboarded BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # ============================
        # AVAILABILITY
        # ============================
        cursor.execute("""
            CREATE TABLE availability (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                day_of_week VARCHAR(3) NOT NULL,
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                CHECK (start_time < end_time)
            );
        """)

        # ============================
        # MEETINGS
        # ============================
        cursor.execute("""
            CREATE TABLE meetings (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                student_email VARCHAR(150) NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                status VARCHAR(20) CHECK (status IN ('PENDING','CONFIRMED','CANCELLED')) DEFAULT 'PENDING',
                reason TEXT,
                ai_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK (start_time < end_time)
            );
        """)

        # ============================
        # AUDIT LOGS
        # ============================
        cursor.execute("""
            CREATE TABLE audit_logs (
                id SERIAL PRIMARY KEY,
                org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action VARCHAR(50) NOT NULL,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # ============================
        # PERFORMANCE INDEXES
        # ============================
        cursor.execute("""
            CREATE INDEX idx_users_org ON users(org_id);
            CREATE INDEX idx_meetings_org ON meetings(org_id);
            CREATE INDEX idx_meetings_user ON meetings(user_id);
            CREATE INDEX idx_meetings_time ON meetings(start_time);
            CREATE INDEX idx_availability_org_user ON availability(org_id, user_id);
            CREATE INDEX idx_audit_org ON audit_logs(org_id);
        """)

        # ============================
        # ENABLE ROW LEVEL SECURITY
        # ============================
        cursor.execute("""
            ALTER TABLE users ENABLE ROW LEVEL SECURITY;
            ALTER TABLE availability ENABLE ROW LEVEL SECURITY;
            ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
            ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

            ALTER TABLE users FORCE ROW LEVEL SECURITY;
            ALTER TABLE availability FORCE ROW LEVEL SECURITY;
            ALTER TABLE meetings FORCE ROW LEVEL SECURITY;
            ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
        """)

        # ============================
        # RLS POLICIES
        # ============================
        cursor.execute("""
            CREATE POLICY org_isolation_users
            ON users
            USING (org_id = current_setting('app.org_id')::int)
            WITH CHECK (org_id = current_setting('app.org_id')::int);

            CREATE POLICY org_isolation_availability
            ON availability
            USING (org_id = current_setting('app.org_id')::int)
            WITH CHECK (org_id = current_setting('app.org_id')::int);

            CREATE POLICY org_isolation_meetings
            ON meetings
            USING (org_id = current_setting('app.org_id')::int)
            WITH CHECK (org_id = current_setting('app.org_id')::int);

            CREATE POLICY org_isolation_audit
            ON audit_logs
            USING (org_id = current_setting('app.org_id')::int)
            WITH CHECK (org_id = current_setting('app.org_id')::int);
        """)

    except DatabaseError as err:
        raise DatabaseInitializationError(f"Schema creation failed: {err}")


def initialize_database():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        create_tables(cur)

        conn.commit()
        cur.close()
        print("✅ Multi-tenant schema initialized successfully")

    except Exception as err:
        if conn:
            conn.rollback()
        raise DatabaseInitializationError(err)

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    initialize_database()
