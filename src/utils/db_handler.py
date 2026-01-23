import psycopg2
from psycopg2.extras import RealDictCursor
from utils.config_loader import Config

def get_db_connection():
    conn = psycopg2.connect(Config.DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    """
    Creates the Faculty table (Removed google_calendar_email).
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS faculty (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(100) UNIQUE NOT NULL,
        phone VARCHAR(20),
        department VARCHAR(50),
        role VARCHAR(50),
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(create_table_query)
        conn.commit()
        print("Database initialized: Faculty table ready.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error initializing DB: {e}")

def get_all_faculty():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM faculty WHERE is_active = TRUE;")
        faculty_list = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(row) for row in faculty_list]
    except Exception as e:
        print(f"Error fetching faculty: {e}")
        return []

def add_faculty_member(name, email, phone, dept, role):
    """
    Adds a faculty member (5 arguments only).
    """
    insert_query = """
    INSERT INTO faculty (name, email, phone, department, role)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id;
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(insert_query, (name, email, phone, dept, role))
        new_id = cur.fetchone()['id']
        conn.commit()
        print(f"Added faculty member ID: {new_id}")
        cur.close()
        conn.close()
        return new_id
    except Exception as e:
        print(f"Error adding faculty: {e}")
        return None

def update_faculty_member(faculty_id, **kwargs):
    allowed_keys = {'name', 'email', 'phone', 'department', 'role', 'is_active'}
    updates = {k: v for k, v in kwargs.items() if k in allowed_keys}
    
    if not updates:
        print("No valid fields to update.")
        return False

    set_clause = ", ".join([f"{key} = %s" for key in updates.keys()])
    values = list(updates.values())
    values.append(faculty_id)

    query = f"UPDATE faculty SET {set_clause} WHERE id = %s;"

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, tuple(values))
        conn.commit()
        success = True if cur.rowcount > 0 else False
        cur.close()
        conn.close()
        return success
    except Exception as e:
        print(f"Error updating faculty: {e}")
        return False

def clear_faculty_table():
    sql_query = "TRUNCATE TABLE faculty RESTART IDENTITY CASCADE;"
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql_query)
        conn.commit()
        print("Success: Faculty table cleared and IDs reset.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error clearing table: {e}")