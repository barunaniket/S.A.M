import json
import time 
import redis
from utils.config_loader import get_env
from utils.email_sender import send_email

# Redis connection (shared)

def get_redis_client():
    """
    Create and return a Redis client.
    """
    return redis.Redis(
        host=get_env("REDIS_HOST", "redis"),
        port=int(get_env("REDIS_PORT", 6379)),
        decode_responses=True  # return bytes not strings
    )

# queue email into redis server

def queue_email(to_addr: str, subject: str, body: str, metadata: dict):
    # this function pushes email into redis queue

    redis_client = get_redis_client()

    email_job = {
        "to":to_addr,
        "subject":subject,
        "body":body,
        "metadata":metadata
    }

    redis_client.lpush("email_queue",json.dumps(email_job))


# backend processing of emails

def process_email_queue():
    redis_client = get_redis_client()
    while True:
        job_data = redis_client("email_queue")
        if not job_data:
            time.sleep(1)
            continue
        # converting json format to dict format
        email_job = json.loads(job_data)
        try:
            # sending email
            send_email(
                to_addr=email_job["to"],
                subject=email_job["subject"],
                body=email_job["body"]
            )
        except Exception as e:
            # Retry logic (push back into queue)
            print(f"Email sending failed: {e}")
            redis_client.lpush("email_queue", job_data)
            time.sleep(5)
        

