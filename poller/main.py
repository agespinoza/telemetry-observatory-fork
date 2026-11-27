"""Scheduled poller for the native macOS sensor."""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

api = os.getenv("API_URL", "http://api:8000").rstrip("/")
sensor = os.getenv("SENSOR_URL", "http://host.docker.internal:8765/sample")
audit_path = Path(os.getenv("AUDIT_PATH", "/audits/poller.jsonl"))


def audit(action, status, detail=None):
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "service": "poller", "action": action, "status": status, "detail": detail or {}}, separators=(",", ":")) + "\n")


def poll_once(session=requests):
    policy = session.get(api + "/api/settings", timeout=5).json()
    interval = max(2, min(3600, int(policy["frequency_seconds"])))
    response = session.get(sensor, headers={"X-Sensor-Token": os.environ["SENSOR_TOKEN"]}, timeout=8)
    response.raise_for_status()
    result = session.post(api + "/api/samples", headers={"Authorization": "Bearer " + os.environ["ADMIN_TOKEN"]}, json=response.json(), timeout=8)
    result.raise_for_status()
    audit("sample.poll", "ok")
    return interval


def main():
    audit("startup", "ok")
    while True:
        started = time.monotonic()
        try:
            interval = poll_once()
        except (requests.RequestException, KeyError, ValueError) as exc:
            audit("sample.poll", "error", {"type": type(exc).__name__, "message": str(exc)[:160]})
            interval = 10
        time.sleep(max(1, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
