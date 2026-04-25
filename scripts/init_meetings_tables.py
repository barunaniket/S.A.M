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
            DROP TABLE IF EXISTS lightweight_meetings CASCADE;
            DROP TABLE IF EXISTS whatsapp_audit CASCADE;
            DROP TABLE IF EXISTS user_group_members CASCADE;
            DROP TABLE IF EXISTS user_groups CASCADE;
            DROP TABLE IF EXISTS pending_uploads CASCADE;
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
                role VARCHAR(20) CHECK (role IN ('ADMIN', 'FACULTY', 'STUDENT')) NOT NULL,
                phone_number VARCHAR(20),
                department VARCHAR(100),
                google_refresh_token TEXT,
                is_onboarded BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX idx_users_phone ON users(phone_number) WHERE phone_number IS NOT NULL;
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
        # PENDING UPLOADS (faculty file ingestion)
        # ============================
        cursor.execute("""
            CREATE TABLE pending_uploads (
                id          SERIAL PRIMARY KEY,
                org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                uploaded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                file_path   TEXT NOT NULL,
                parse_kind  VARCHAR(20) NOT NULL,
                parsed      JSONB NOT NULL,
                status      VARCHAR(20) NOT NULL DEFAULT 'PARSED'
                            CHECK (status IN ('PARSED','EXECUTED','DISCARDED')),
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at  TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours')
            );
            CREATE INDEX idx_pending_uploads_org ON pending_uploads(org_id);
            CREATE INDEX idx_pending_uploads_user ON pending_uploads(uploaded_by);
        """)

        # ============================
        # USER GROUPS (faculty-defined cohorts)
        # ============================
        cursor.execute("""
            CREATE TABLE user_groups (
                id          SERIAL PRIMARY KEY,
                org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                name        VARCHAR(100) NOT NULL,
                description TEXT,
                created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (org_id, name)
            );
            CREATE TABLE user_group_members (
                group_id  INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
                user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id)
            );
            CREATE INDEX idx_user_groups_org ON user_groups(org_id);
            CREATE INDEX idx_user_group_members_user ON user_group_members(user_id);
        """)

        # ============================
        # WHATSAPP AUDIT TRAIL
        # ============================
        cursor.execute("""
            CREATE TABLE whatsapp_audit (
                id          SERIAL PRIMARY KEY,
                org_id      INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
                user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
                phone       VARCHAR(20),
                direction   VARCHAR(10) NOT NULL CHECK (direction IN ('inbound','outbound')),
                msg_type    VARCHAR(20),
                body        TEXT,
                intent      VARCHAR(40),
                metadata    JSONB,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_wa_audit_org   ON whatsapp_audit(org_id);
            CREATE INDEX idx_wa_audit_phone ON whatsapp_audit(phone);
            CREATE INDEX idx_wa_audit_time  ON whatsapp_audit(created_at);
        """)

        # ============================
        # LIGHTWEIGHT MEETINGS (upload-driven, no Google Calendar)
        # ============================
        cursor.execute("""
            CREATE TABLE lightweight_meetings (
                id            SERIAL PRIMARY KEY,
                org_id        INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                organizer_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                title         TEXT NOT NULL,
                start_time    TIMESTAMP NOT NULL,
                end_time      TIMESTAMP NOT NULL,
                location      TEXT,
                agenda        TEXT,
                attendees     JSONB NOT NULL DEFAULT '[]'::jsonb,
                ics_path      TEXT,
                status        VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED'
                               CHECK (status IN ('SCHEDULED','CANCELLED','COMPLETED')),
                upload_id     INTEGER REFERENCES pending_uploads(id) ON DELETE SET NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK (start_time < end_time)
            );
            CREATE INDEX idx_lite_meetings_org   ON lightweight_meetings(org_id);
            CREATE INDEX idx_lite_meetings_start ON lightweight_meetings(start_time);
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
