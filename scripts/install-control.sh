#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
test -x .venv/bin/python || { echo 'Create .venv and install requirements first' >&2; exit 1; }
test -f .env || { echo 'Create .env first' >&2; exit 1; }
ROOT=$(pwd)
CONTROL_PORT=$(sed -n 's/^CONTROL_PORT=//p' .env)
CONTROL_PORT=${CONTROL_PORT:-8766}
case "$CONTROL_PORT" in ''|*[!0-9]*) echo 'CONTROL_PORT must be numeric' >&2; exit 1;; esac
DOCKER_DIR=$(dirname "$(command -v docker)")
mkdir -p audits
PLIST="$ROOT/.control.launchd.plist"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.telemetry-observatory.control</string>
<key>ProgramArguments</key><array><string>$ROOT/.venv/bin/python</string><string>$ROOT/host_control.py</string></array>
<key>WorkingDirectory</key><string>$ROOT</string>
<key>EnvironmentVariables</key><dict><key>CONTROL_PORT</key><string>$CONTROL_PORT</string><key>PATH</key><string>$DOCKER_DIR:/usr/local/bin:/usr/bin:/bin</string></dict>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$ROOT/audits/control-console.log</string>
<key>StandardErrorPath</key><string>$ROOT/audits/control-console.log</string>
</dict></plist>
PLISTEOF
chmod 600 "$PLIST"
launchctl bootout "gui/$(id -u)/com.telemetry-observatory.control" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo 'Host control agent installed and started'
