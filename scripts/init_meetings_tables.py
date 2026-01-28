import os
import psycopg2
from psycopg2 import sql, OperationalError
from dotenv import load_dotenv
from pathlib import Path


def load_environment():
    """
    Loads environment variables from .env file located at project root.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        raise FileNotFoundError(".env file not found at project root")
    load_dotenv(dotenv_path=env_path)


def get_db_connection():
    """
    Creates and returns a PostgreSQL database connection.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def create_tables(cursor):
    """
    Executes SQL statements to create required tables.
    """
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


def main():
    """
    Entry point for DB initialization script.
    """
    load_environment()

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        create_tables(cur)

        conn.commit()
        cur.close()

        print("✅ Database tables initialized successfully")

    except OperationalError as db_err:
        if conn:
            conn.rollback()
        raise RuntimeError(f"❌ Database connection failed: {db_err}")

    except Exception as err:
        if conn:
            conn.rollback()
        raise RuntimeError(f"❌ Database initialization error: {err}")

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
