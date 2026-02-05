import psycopg2
from psycopg2 import OperationalError, DatabaseError
from utils.config_loader import Config



class DatabaseInitializationError(Exception):
    """Raised when database initialization fails."""


def get_db_connection():
    """
    Create and return a PostgreSQL database connection
    using centralized configuration.
    """
    try:
        return psycopg2.connect(Config.DATABASE_URL)
    except OperationalError as err:
        raise DatabaseInitializationError(
            f"Unable to connect to database. Check DATABASE_URL. Details: {err}"
        )


def create_tables(cursor):
    """
    Create all required database tables.
    This function is idempotent and safe to re-run.
    """
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id SERIAL PRIMARY KEY,
                meeting_id VARCHAR(255) UNIQUE NOT NULL,
                title VARCHAR(255) NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                organizer_email VARCHAR(255) NOT NULL,
                meet_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meeting_participants (
                id SERIAL PRIMARY KEY,
                meeting_id INTEGER REFERENCES meetings(id) ON DELETE CASCADE,
                participant_name VARCHAR(255),
                participant_email VARCHAR(255) NOT NULL
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id SERIAL PRIMARY KEY,
                action_type VARCHAR(50) NOT NULL,
                meeting_id INTEGER,
                performed_by VARCHAR(255),
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    except DatabaseError as err:
        raise DatabaseInitializationError(
            f"Failed while executing table creation SQL. Details: {err}"
        )


def initialize_database():
    """
    Orchestrates database initialization in a safe transaction.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        create_tables(cur)

        conn.commit()
        cur.close()

        print("✅ Database schema initialized successfully")

    except DatabaseInitializationError:
        if conn:
            conn.rollback()
        raise  # re-raise to fail fast

    except Exception as err:
        if conn:
            conn.rollback()
        raise DatabaseInitializationError(
            f"Unexpected error during DB initialization: {err}"
        )

    finally:
        if conn:
            conn.close()


def main():
    """
    Script entry point.
    """
    initialize_database()


if __name__ == "__main__":
    main()
