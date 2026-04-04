import redis
import json
import os

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=6379,
    decode_responses=True
)

class TempLifecycleStore:

    def create(self, meeting_id):
        redis_client.set(
            f"meeting:{meeting_id}",
            json.dumps({"status": "PENDING"})
        )

    def get(self, meeting_id):
        data = redis_client.get(f"meeting:{meeting_id}")
        return json.loads(data) if data else None

    def update(self, meeting_id, new_status):
        redis_client.set(
            f"meeting:{meeting_id}",
            json.dumps({"status": new_status})
        )

store = TempLifecycleStore()
