import json
import os
import smtplib
import time
from email.message import EmailMessage

import redis

from src.utils.config_loader import Config


def _get_redis_client():
    return redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True
    )


def _send_email_smtp(to_addr: str, subject: str, body: str):
    """Send a plain-text email via Gmail SMTP."""
    msg = EmailMessage()
    msg["From"] = Config.SENDER_EMAIL
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(Config.SENDER_EMAIL, Config.SENDER_PASSWORD)
        server.send_message(msg)


def queue_email(to_addr: str, subject: str, body: str, metadata: dict = None):
    """Push an email job onto the Redis queue."""
    client = _get_redis_client()
    job = {
        "to": to_addr,
        "subject": subject,
        "body": body,
        "metadata": metadata or {},
    }
    client.lpush("email_queue", json.dumps(job))


def process_email_queue():
    """
    Blocking worker loop — pops jobs from Redis and sends them.
    Run this in a separate process (e.g. via Celery or a background thread).
    """
    client = _get_redis_client()

    while True:
        # rpop returns None when the queue is empty
        job_data = client.rpop("email_queue")

        if not job_data:
            time.sleep(1)
            continue

        email_job = json.loads(job_data)

        try:
            _send_email_smtp(
                to_addr=email_job["to"],
                subject=email_job["subject"],
                body=email_job["body"],
            )
        except Exception as e:
            print(f"Email sending failed: {e} — re-queuing")
            # Push failed job back to the end of the queue for retry
            client.lpush("email_queue", job_data)
            time.sleep(5)
