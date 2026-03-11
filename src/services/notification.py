from utils.db_handler import get_db_connection


def create_notification(user_id: int, message: str, type: str):
    """
    Store notification for frontend.
    """

    query = """
        INSERT INTO notifications (user_id, message, type, read)
        VALUES (%s, %s, %s, %s);
    """

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(query, (user_id, message, type, False))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print(f"Failed to create notification: {e}")
