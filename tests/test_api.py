from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import main


def test_admin_rejects_invalid_token(monkeypatch, tmp_path):
    monkeypatch.setenv('ADMIN_TOKEN', 'a' * 32)
    monkeypatch.setattr(main, 'audit_path', tmp_path / 'api.jsonl')
    with pytest.raises(HTTPException) as error:
        main.require_admin('Bearer wrong')
    assert error.value.status_code == 401
    assert 'denied' in (tmp_path / 'api.jsonl').read_text()


def test_retention_update_recalculates_existing_expiry(monkeypatch, tmp_path):
    monkeypatch.setenv('ADMIN_TOKEN', 'a' * 32)
    monkeypatch.setattr(main, 'audit_path', tmp_path / 'api.jsonl')
    at = datetime(2026, 1, 1)

    class Settings:
        def update_one(self, query, change, upsert=False):
            assert change['$set']['retention_days'] == 2
            assert upsert

    class Samples:
        expiry = None

        def find(self, query, fields):
            return [{'_id': 1, 'sampled_at': at}]

        def update_one(self, query, change):
            self.expiry = change['$set']['expires_at']

    fake = Samples()
    monkeypatch.setattr(main, 'settings', Settings())
    monkeypatch.setattr(main, 'samples', fake)
    result = main.put_settings({'frequency_seconds': 3, 'retention_days': 2}, 'Bearer ' + 'a' * 32)
    assert result['frequency_seconds'] == 3
    assert fake.expiry == datetime(2026, 1, 3, tzinfo=timezone.utc)
