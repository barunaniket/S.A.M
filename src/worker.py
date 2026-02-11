import os
from celery import Celery

# Get Redis URL from .env (Docker injects this)
redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Initialize Celery
celery_app = Celery(
    "sam_worker",
    broker=redis_url,
    backend=redis_url
)

# Optional: Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)

@celery_app.task(name="test_task")
def test_task(word: str):
    return f"Celery received: {word}"