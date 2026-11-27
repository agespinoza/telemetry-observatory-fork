"""Test plan for the restart logic (host_control.py and /api/restart).

1. set_env_value replaces an existing key, appends a missing key, preserves other lines.
2. validate_port rejects bool/str/float/out-of-range values and accepts the bounds.
3. restart_services runs `docker compose up -d --force-recreate` in the project root and maps exit codes / OS errors to True/False.
4. HTTP: wrong or short token -> 401, unknown path -> 404, invalid port -> 400 with .env untouched,
   oversized body -> 413, valid request -> 202 + .env updated + restart triggered,
   concurrent restart -> 409.
5. API: /api/restart requires the admin token, forwards the saved port to the agent, and maps an
   unreachable agent to 503; /api/settings reports restart_required when saved and active ports differ.
"""
import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import host_control
from api import main

TOKEN = 'a' * 32


def test_set_env_value_replaces_and_appends(tmp_path):
    env = tmp_path / '.env'
    env.write_text('ADMIN_TOKEN=x\nDASHBOARD_PORT=8080\nOTHER=1\n')
    host_control.set_env_value(env, 'DASHBOARD_PORT', '9090')
    host_control.set_env_value(env, 'NEW', '2')
    assert env.read_text() == 'ADMIN_TOKEN=x\nDASHBOARD_PORT=9090\nOTHER=1\nNEW=2\n'
    assert (env.stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize('value', [True, '8080', 80.5, 1023, 65536, None])
def test_validate_port_rejects(value):
    with pytest.raises(ValueError):
        host_control.validate_port(value)


@pytest.mark.parametrize('value', [1024, 65535])
def test_validate_port_bounds(value):
    assert host_control.validate_port(value) == value


def test_restart_services_command_and_result():
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw))
        return SimpleNamespace(returncode=0)

    assert host_control.restart_services(runner) is True
    assert calls[0][0] == ['docker', 'compose', 'up', '-d', '--force-recreate']
    assert calls[0][1]['cwd'] == host_control.ROOT
    assert host_control.restart_services(lambda c, **k: SimpleNamespace(returncode=1)) is False

    def missing(c, **k):
        raise FileNotFoundError

    def timeout(c, **k):
        raise subprocess.TimeoutExpired(c, 1)

    assert host_control.restart_services(missing) is False
    assert host_control.restart_services(timeout) is False


@pytest.fixture
def agent(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text(f'ADMIN_TOKEN={TOKEN}\nDASHBOARD_PORT=8080\n')
    monkeypatch.setattr(host_control, 'ENV_PATH', env)
    started = threading.Event()
    release = threading.Event()

    def fake_restart():
        started.set()
        release.wait(5)
        return True

    monkeypatch.setattr(host_control, 'restart_services', fake_restart)
    server = ThreadingHTTPServer(('127.0.0.1', 0), host_control.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    yield SimpleNamespace(url=url, env=env, started=started, release=release)
    release.set()
    server.shutdown()
    server.server_close()
    thread.join(2)


def post(url, path='/restart', body=None, token=TOKEN, raw=None):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    data = raw if raw is not None else json.dumps(body or {}).encode()
    req = urllib.request.Request(url + path, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.mark.parametrize('token', [None, 'wrong', 'a' * 10])
def test_agent_rejects_bad_token(agent, token):
    assert post(agent.url, token=token) == 401
    assert not agent.started.is_set()


def test_agent_unknown_path_and_invalid_input(agent):
    assert post(agent.url, '/nope') == 404
    assert post(agent.url, body={'dashboard_port': 80}) == 400
    assert post(agent.url, body={'dashboard_port': '9090'}) == 400
    assert post(agent.url, raw=b'{bad') == 400
    assert post(agent.url, raw=b'x' * 2000) == 413
    assert 'DASHBOARD_PORT=8080' in agent.env.read_text()
    assert not agent.started.is_set()


def test_agent_applies_port_and_restarts_once(agent):
    assert post(agent.url, body={'dashboard_port': 9090}) == 202
    assert agent.started.wait(2)
    assert 'DASHBOARD_PORT=9090' in agent.env.read_text()
    assert post(agent.url) == 409
    agent.release.set()


def test_agent_restart_without_port_keeps_env(agent):
    assert post(agent.url) == 202
    assert agent.started.wait(2)
    assert 'DASHBOARD_PORT=8080' in agent.env.read_text()
    agent.release.set()


class FakeSettings:
    def __init__(self, doc=None):
        self.doc = doc

    def find_one(self, query):
        return self.doc


def test_api_reports_restart_required(monkeypatch):
    monkeypatch.setenv('DASHBOARD_PORT', '8080')
    monkeypatch.setattr(main, 'settings', FakeSettings({'dashboard_port': 9090}))
    cfg = main.get_settings()
    assert (cfg['dashboard_port'], cfg['active_dashboard_port'], cfg['restart_required']) == (9090, 8080, True)
    monkeypatch.setattr(main, 'settings', FakeSettings())
    assert main.get_settings()['restart_required'] is False


def test_api_restart_requires_token(monkeypatch, tmp_path):
    monkeypatch.setenv('ADMIN_TOKEN', TOKEN)
    monkeypatch.setattr(main, 'audit_path', tmp_path / 'api.jsonl')
    with pytest.raises(HTTPException) as error:
        main.restart('Bearer wrong')
    assert error.value.status_code == 401


def test_api_restart_forwards_saved_port(monkeypatch, tmp_path, agent):
    monkeypatch.setenv('ADMIN_TOKEN', TOKEN)
    monkeypatch.setenv('DASHBOARD_PORT', '8080')
    monkeypatch.setenv('CONTROL_URL', agent.url)
    monkeypatch.setattr(main, 'audit_path', tmp_path / 'api.jsonl')
    monkeypatch.setattr(main, 'settings', FakeSettings({'dashboard_port': 9191}))
    assert main.restart('Bearer ' + TOKEN) == {'status': 'restarting', 'dashboard_port': 9191}
    assert agent.started.wait(2)
    assert 'DASHBOARD_PORT=9191' in agent.env.read_text()
    agent.release.set()


def test_api_restart_agent_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('ADMIN_TOKEN', TOKEN)
    monkeypatch.setenv('CONTROL_URL', 'http://127.0.0.1:1')
    monkeypatch.setattr(main, 'audit_path', tmp_path / 'api.jsonl')
    monkeypatch.setattr(main, 'settings', FakeSettings())
    with pytest.raises(HTTPException) as error:
        main.restart('Bearer ' + TOKEN)
    assert error.value.status_code == 503
    assert 'services.restart' in (tmp_path / 'api.jsonl').read_text()
