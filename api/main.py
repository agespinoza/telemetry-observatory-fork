"""Read and write telemetry; MongoDB TTL enforces sample retention."""
import json
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, MongoClient

from policy import DEFAULT_FREQUENCY_SECONDS, DEFAULT_RETENTION_DAYS, expiry_for, validate_policy

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000)
samples = client.observatory.samples
settings = client.observatory.settings
audit_path = Path(os.getenv("AUDIT_PATH", "/audits/api.jsonl"))
audit_lock = threading.Lock()


def audit(action, status, detail=None):
    record = {"at": datetime.now(timezone.utc).isoformat(), "service": "api", "action": action, "status": status, "detail": detail or {}}
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_lock, audit_path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")


def require_admin(header):
    expected = os.getenv("ADMIN_TOKEN", "")
    supplied = (header or "").removeprefix("Bearer ")
    if len(expected) < 24 or not secrets.compare_digest(supplied, expected):
        audit("authorization", "denied")
        raise HTTPException(401, "Invalid administrator token")


def current_policy():
    doc = settings.find_one({"_id": "global"}) or {}
    return {"frequency_seconds": doc.get("frequency_seconds", DEFAULT_FREQUENCY_SECONDS), "retention_days": doc.get("retention_days", DEFAULT_RETENTION_DAYS)}


class Sample(BaseModel):
    host: str = Field(min_length=1, max_length=128)
    sampled_at: datetime
    cpu_percent: float = Field(ge=0, le=100)
    memory: dict
    swap: dict
    disks: list[dict]
    disk_io: dict
    network_io: dict
    applications: list[dict]


@asynccontextmanager
async def lifespan(app):
    samples.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    samples.create_index([("sampled_at", DESCENDING)])
    audit("startup", "ok")
    yield
    audit("shutdown", "ok")


app = FastAPI(title="Telemetry Observatory", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/api/health")
def health():
    client.admin.command("ping")
    return {"status": "ok"}


@app.get("/api/settings")
def get_settings():
    return current_policy()


@app.put("/api/settings")
def put_settings(value: dict, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    try:
        policy = validate_policy(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    data = {"frequency_seconds": policy.frequency_seconds, "retention_days": policy.retention_days}
    settings.update_one({"_id": "global"}, {"$set": data}, upsert=True)
    # Recalculate existing expiry dates when the retention policy changes.
    for item in samples.find({}, {"_id": 1, "sampled_at": 1}):
        at = item["sampled_at"].replace(tzinfo=timezone.utc)
        samples.update_one({"_id": item["_id"]}, {"$set": {"expires_at": expiry_for(at, policy.retention_days)}})
    audit("settings.update", "ok", data)
    return data


@app.post("/api/samples", status_code=201)
def post_sample(value: Sample, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    at = value.sampled_at.astimezone(timezone.utc)
    if abs((datetime.now(timezone.utc) - at).total_seconds()) > 300:
        raise HTTPException(422, "Sample clock is more than five minutes from server clock")
    item = value.model_dump()
    item["sampled_at"] = at
    item["expires_at"] = expiry_for(at, current_policy()["retention_days"])
    samples.insert_one(item)
    audit("sample.ingest", "ok", {"host": value.host})
    return {"status": "stored"}


@app.get("/api/samples")
def get_samples(limit: int = Query(120, ge=1, le=1000)):
    result = []
    for doc in samples.find({}, {"_id": 0, "expires_at": 0}).sort("sampled_at", DESCENDING).limit(limit):
        doc["sampled_at"] = doc["sampled_at"].replace(tzinfo=timezone.utc).isoformat()
        result.append(doc)
    return result


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    try:
        response = await call_next(request)
        if request.method != "GET" or response.status_code >= 400:
            audit("http.request", str(response.status_code), {"method": request.method, "path": request.url.path})
        return response
    except Exception as exc:
        audit("http.request", "error", {"path": request.url.path, "type": type(exc).__name__})
        raise
