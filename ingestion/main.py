import os
import time
from fastapi import FastAPI 
from pydantic import BaseModel

from pubsub import publish

app = FastAPI(title = "Sentinel Ingestion")

class TelemetryEvent(BaseModel):
  environment_id: str
  source: str
  message: str
  severity: str = "info"

@app.post("/telemetry")
async def ingest(event: TelemetryEvent):
  publish(
    "telemetry",
    {
      "environment_id": event.environment_id,
      "source": event.source,
      "message": event.message,
      "severity": event.severity,
      "recieved_at": time.time(),
    },
  )
  return {"status": "accepted"}

@app.get("/health")
async def health():
  return {"status": "ok"}

  