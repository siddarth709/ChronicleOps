import os
import json
import redis

VALKEY_HOST = os.environ.get("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.environ.get("VALKEY_PORT", 6379))
VALKEY_PASSWORD = os.environ.get("VALKEY_PASSWORD") or None

_client = redis.Redis(
  host = VALKEY_HOST, port = VALKEY_PORT, password = VALKEY_PASSWORD, decode_responses = True
)

CHANNEL = "sentinel:events"

def publish(event_type: str, payload: dict) -> None:
    message = json.dumps({"type": event_type, **payload}, default=str)
    try:
        _client.publish(CHANNEL, message)
    except redis.RedisError:
        pass