"""Native host agent that applies the dashboard port and restarts the Compose services.
Containers cannot safely run `docker compose` themselves, so the API asks this agent."""
import json
import os
import secrets
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from policy import validate_port

ROOT = Path(__file__).parent
ENV_PATH = ROOT / ".env"
restart_lock = threading.Lock()


def read_env(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def set_env_value(path, key, value):
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = [f"{key}={value}" if line.split("=", 1)[0].strip() == key else line for line in lines]
    if f"{key}={value}" not in updated:
        updated.append(f"{key}={value}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write("\n".join(updated) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def restart_services(runner=subprocess.run):
    try:
        result = runner(["docker", "compose", "up", "-d", "--force-recreate"], cwd=ROOT, check=False, capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def run_restart():
    try:
        restart_services()
    finally:
        restart_lock.release()


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/restart":
            return self.reply(404, {"error": "not found"})
        expected = read_env(ENV_PATH).get("ADMIN_TOKEN", "") if ENV_PATH.exists() else ""
        supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if len(expected) < 24 or not secrets.compare_digest(supplied, expected):
            return self.reply(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= 1024:
                return self.reply(413, {"error": "body too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            port = validate_port(body["dashboard_port"]) if body.get("dashboard_port") is not None else None
        except (ValueError, AttributeError) as exc:
            return self.reply(400, {"error": str(exc)})
        if not restart_lock.acquire(blocking=False):
            return self.reply(409, {"error": "restart already in progress"})
        try:
            if port is not None:
                set_env_value(ENV_PATH, "DASHBOARD_PORT", str(port))
            self.reply(202, {"status": "restarting"})
        except BaseException:
            restart_lock.release()
            raise
        threading.Thread(target=run_restart, daemon=True).start()

    def log_message(self, format, *args):
        pass


def main():
    server = ThreadingHTTPServer((os.getenv("CONTROL_BIND", "127.0.0.1"), int(os.getenv("CONTROL_PORT", "8766"))), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
