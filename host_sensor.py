"""Native macOS adapter. Docker Desktop cannot see macOS host counters."""
import json
import os
import secrets
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

audit_path = Path(os.getenv("SENSOR_AUDIT_PATH", str(Path(__file__).parent / "audits/sensor.jsonl")))
audit_lock = threading.Lock()


def audit(action, status, detail=None):
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_lock, audit_path.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "service": "sensor", "action": action, "status": status, "detail": detail or {}}, separators=(",", ":")) + "\n")


def counter(value):
    return value._asdict() if value is not None else {}


def collect():
    disks = []
    seen = set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({"mount": part.mountpoint, "device": part.device, "filesystem": part.fstype, "total": usage.total, "used": usage.used, "free": usage.free, "percent": usage.percent})
        except (OSError, PermissionError):
            pass
    applications = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            info = proc.info
            applications.append({"pid": info["pid"], "name": info["name"] or "unknown", "memory_bytes": info["memory_info"].rss if info["memory_info"] else 0, "cpu_percent": info["cpu_percent"] or 0})
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    applications.sort(key=lambda item: item["memory_bytes"], reverse=True)
    return {"host": socket.gethostname(), "sampled_at": datetime.now(timezone.utc).isoformat(), "cpu_percent": psutil.cpu_percent(interval=0.1), "memory": counter(psutil.virtual_memory()), "swap": counter(psutil.swap_memory()), "disks": disks, "disk_io": counter(psutil.disk_io_counters()), "network_io": counter(psutil.net_io_counters()), "applications": applications[:30]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/sample":
            self.send_error(404)
            return
        expected = os.getenv("SENSOR_TOKEN", "")
        if len(expected) < 24 or not secrets.compare_digest(self.headers.get("X-Sensor-Token", ""), expected):
            audit("sample.read", "denied")
            self.send_error(401)
            return
        try:
            body = json.dumps(collect()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            audit("sample.read", "ok")
        except Exception as exc:
            audit("sample.read", "error", {"type": type(exc).__name__})
            self.send_error(500)

    def log_message(self, format, *args):
        pass


def main():
    if len(os.getenv("SENSOR_TOKEN", "")) < 24:
        raise SystemExit("Set SENSOR_TOKEN to at least 24 characters")
    server = ThreadingHTTPServer((os.getenv("SENSOR_BIND", "0.0.0.0"), int(os.getenv("SENSOR_PORT", "8765"))), Handler)
    audit("startup", "ok", {"port": server.server_port})
    try:
        server.serve_forever()
    finally:
        server.server_close()
        audit("shutdown", "ok")


if __name__ == "__main__":
    main()
