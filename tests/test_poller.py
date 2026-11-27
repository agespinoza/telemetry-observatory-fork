import os

from poller.main import poll_once


class Response:
    def __init__(self, value):
        self.value = value

    def json(self):
        return self.value

    def raise_for_status(self):
        pass


def test_poller_uses_current_frequency_and_passes_sample(monkeypatch, tmp_path):
    import poller.main as poller
    monkeypatch.setattr(poller, 'audit_path', tmp_path / 'poller.jsonl')
    monkeypatch.setenv('SENSOR_TOKEN', 'sensor-secret')
    monkeypatch.setenv('ADMIN_TOKEN', 'admin-secret')

    class Session:
        def get(self, url, **kwargs):
            if url.endswith('/api/settings'):
                return Response({'frequency_seconds': 15})
            assert kwargs['headers']['X-Sensor-Token'] == 'sensor-secret'
            return Response({'host': 'mac', 'gpu_percent': 37})

        def post(self, url, **kwargs):
            assert kwargs['json'] == {'host': 'mac', 'gpu_percent': 37}
            assert kwargs['headers']['Authorization'] == 'Bearer admin-secret'
            return Response({'status': 'stored'})

    assert poll_once(Session()) == 15
    assert 'sample.poll' in (tmp_path / 'poller.jsonl').read_text()
