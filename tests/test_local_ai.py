import io
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import host_sensor


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def fake_ollama(monkeypatch, ps):
    calls = []

    def urlopen(url, timeout):
        calls.append(url)
        return Response(json.dumps({'version': '0.40.19'} if url.endswith('/api/version') else ps).encode())

    monkeypatch.setattr(host_sensor.urllib.request, 'urlopen', urlopen)
    return calls


def test_ollama_status_reports_models_and_gpu_share(monkeypatch):
    calls = fake_ollama(monkeypatch, {'models': [
        {'name': 'qwen3.5:9b', 'size': 1000, 'size_vram': 1000, 'expires_at': '2026-01-01T00:05:00Z', 'details': {'parameter_size': '9B', 'quantization_level': 'Q4_K_M'}},
        {'name': 'phi4:14b', 'size': 1000, 'size_vram': 250},
        {'name': 'broken', 'size': 'x', 'size_vram': None},
        'not a model',
    ]})
    result = host_sensor.ollama_status(base='http://ollama:11434/')
    assert calls == ['http://ollama:11434/api/version', 'http://ollama:11434/api/ps']
    assert result['reachable'] is True and result['version'] == '0.40.19'
    assert [m['gpu_percent'] for m in result['models']] == [100, 25.0, None]
    assert result['models'][0]['parameter_size'] == '9B' and result['models'][0]['quantization'] == 'Q4_K_M'
    assert result['models'][1]['parameter_size'] is None


def test_ollama_status_unreachable_is_audited(monkeypatch, tmp_path):
    monkeypatch.setattr(host_sensor, 'audit_path', tmp_path / 'sensor.jsonl')

    def urlopen(url, timeout):
        raise ConnectionRefusedError()

    monkeypatch.setattr(host_sensor.urllib.request, 'urlopen', urlopen)
    assert host_sensor.ollama_status() == {'reachable': False, 'version': None, 'models': []}
    assert json.loads((tmp_path / 'sensor.jsonl').read_text())['action'] == 'ollama.read'


def test_local_ai_selects_runtime_processes(monkeypatch):
    monkeypatch.setattr(host_sensor, 'ollama_status', lambda: {'reachable': True, 'version': None, 'models': []})
    monkeypatch.setattr(host_sensor, 'token_usage', lambda: None)
    apps = [{'pid': 1, 'name': 'Safari', 'cpu_percent': 90, 'memory_bytes': 1},
            {'pid': 2, 'name': 'ollama', 'cpu_percent': 1, 'memory_bytes': 1},
            {'pid': 3, 'name': 'Ollama Runner', 'cpu_percent': 60, 'memory_bytes': 1},
            {'pid': 4, 'name': 'LM Studio', 'cpu_percent': 5, 'memory_bytes': 1}]
    result = host_sensor.local_ai(apps)
    assert [p['pid'] for p in result['processes']] == [3, 4, 2]
    assert result['tokens'] is None


def test_token_usage_complex_scenario(tmp_path):
    """Test token_usage with mixed local/remote invocations and edge cases."""
    # Prepare JSONL content
    lines = [
        '{"timestamp": "2026-01-01T12:00:00+00:00", "record_type": "invocation", "execution_location": "local", "model": "a", "total_tokens": 100}',
        '{"timestamp": "2026-01-01T18:00:00Z", "record_type": "invocation", "execution_location": "local", "model": "b", "total_tokens": 50}',
        '{"timestamp": "2026-01-01T19:00:00+00:00", "record_type": "invocation", "execution_location": "remote", "model": "c", "total_tokens": 50}',
        '{"timestamp": "2026-01-01T20:00:00+00:00", "record_type": "invocation", "execution_location": "remote", "total_tokens": null}',
        '{"timestamp": "2026-01-01T21:00:00+00:00", "record_type": "task_start"}',
        '',  # blank line
        'not json',  # invalid JSON line
        '{"timestamp": "2025-12-30T12:00:00+00:00", "record_type": "invocation", "execution_location": "local", "model": "old", "total_tokens": 999}',
    ]
    
    jsonl_path = tmp_path / "telemetry.jsonl"
    with open(jsonl_path, 'w') as f:
        f.write('\n'.join(lines))

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    result = host_sensor.token_usage(path=str(jsonl_path), hours=24, now=now)

    assert result is not None
    assert result["local"]["invocations"] == 2
    assert result["remote"]["invocations"] == 2
    assert result["unknown"]["invocations"] == 0
    assert result["local"]["tokens"] == 150
    assert result["remote"]["tokens"] == 50
    assert result["local_share"] == 75.0
    assert result["last_local_model"] == "b"


def test_token_usage_missing_file(tmp_path):
    """Test token_usage returns None when file is missing."""
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    result = host_sensor.token_usage(path=str(tmp_path / "nonexistent.jsonl"), hours=24, now=now)
    assert result is None


def test_token_usage_only_task_start(tmp_path):
    """Test token_usage with only task_start records."""
    lines = [
        '{"timestamp": "2026-01-01T12:00:00+00:00", "record_type": "task_start"}',
        '',
        'not json',
    ]
    
    jsonl_path = tmp_path / "telemetry.jsonl"
    with open(jsonl_path, 'w') as f:
        f.write('\n'.join(lines))

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    result = host_sensor.token_usage(path=str(jsonl_path), hours=24, now=now)

    assert result is not None
    assert result["local"]["invocations"] == 0
    assert result["remote"]["invocations"] == 0
    assert result["unknown"]["invocations"] == 0
    assert result["local_share"] is None
    assert result["last_local_at"] is None
    assert result["last_local_model"] is None


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is required for dashboard tests')
def test_dashboard_local_ai_state_and_observations():
    dashboard = Path(__file__).resolve().parents[1] / 'web' / 'index.html'
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
assert.match(html, /id="ai-panel"/);
const start = html.indexOf('const AI_GPU_BUSY');
const end = html.indexOf('function renderAI(', start);
assert.ok(start >= 0 && end > start);
const context = {
  bytes: n => `${n} B`,
  pct: n => Number(n).toFixed(1) + '%',
};
vm.runInNewContext(html.slice(start, end) + ';this.aiState=aiState;this.aiObservations=aiObservations', context);
const model = (vram) => ({name: 'qwen', size: 100, size_vram: vram, gpu_percent: vram});
const sample = (gpu, models, extra = {}) => ({sampled_at: '2026-01-01T00:00:00Z', gpu_percent: gpu, memory: {total: 1000},
  local_ai: {ollama: {reachable: true, models}, processes: [], tokens: null, ...extra}});
assert.equal(context.aiState(sample(40, [model(100)])), 'on');
assert.equal(context.aiState(sample(2, [model(100)])), 'idle');
assert.equal(context.aiState(sample(2, [])), 'ready');
assert.equal(context.aiState({local_ai: {ollama: {reachable: false, models: []}, processes: []}}), 'off');
assert.equal(context.aiState({local_ai: {ollama: {reachable: false, models: []}, processes: [{cpu_percent: 80}]}}), 'on');
assert.equal(context.aiState({}), 'unknown');
let obs = context.aiObservations([sample(40, [model(60)]), sample(2, [model(60)]), sample(2, [model(60)])]);
let text = obs.map(o => o[0]).join('\n');
assert.match(text, /40% of its weights in CPU memory/);
assert.match(text, /active in 1 of the last 3 samples/);
assert.match(text, /No token-telemetry log/);
const tokens = {local: {invocations: 0, tokens: 0}, remote: {invocations: 4, tokens: 900}, local_share: 0, last_local_at: null};
obs = context.aiObservations([sample(0, [], {tokens})]);
const delegation = obs.find(o => /not being delegated locally/.test(o[0]));
assert.ok(delegation && delegation[1]);
obs = context.aiObservations([{sampled_at: '2026-01-01T00:00:00Z', memory: {}, local_ai: {ollama: {reachable: false, models: []}, processes: [], tokens: null}}]);
assert.match(obs[0][0], /not answering/);
"""
    subprocess.run(['node', '-e', script, str(dashboard)], check=True)
