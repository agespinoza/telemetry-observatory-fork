from datetime import datetime, timedelta, timezone

import pytest

from policy import expiry_for, validate_policy


def test_policy_bounds_and_types():
    assert validate_policy({"frequency_seconds": 2, "retention_days": 365}).retention_days == 365
    for bad in ({"frequency_seconds": True, "retention_days": 7}, {"frequency_seconds": 1, "retention_days": 7}, {"frequency_seconds": 10, "retention_days": 366}, {"frequency_seconds": "10", "retention_days": 7}):
        with pytest.raises(ValueError):
            validate_policy(bad)


def test_expiry_requires_utc():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert expiry_for(now, 7) == now + timedelta(days=7)
    with pytest.raises(ValueError):
        expiry_for(now.replace(tzinfo=None), 7)
