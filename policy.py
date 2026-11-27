from datetime import datetime, timedelta, timezone
from dataclasses import dataclass


DEFAULT_FREQUENCY_SECONDS = 10
DEFAULT_RETENTION_DAYS = 7

@dataclass(frozen=True)
class Policy:
    frequency_seconds: int
    retention_days: int

def validate_policy(payload: dict) -> Policy:
    """
    Validates a policy payload and returns a Policy instance.
    
    Args:
        payload (dict): Dictionary containing 'frequency_seconds' and 'retention_days'.
        
    Returns:
        Policy: A validated Policy object.
        
    Raises:
        ValueError: If values are bool, non-int, or out of range.
    """
    # Handle frequency_seconds
    if "frequency_seconds" not in payload:
        raise ValueError("Missing required key: 'frequency_seconds'")
    
    freq_val = payload["frequency_seconds"]
    # Explicitly reject booleans (since bool is a subclass of int in Python)
    if isinstance(freq_val, bool):
        raise ValueError("'frequency_seconds' must be an integer, not a boolean.")
    if not isinstance(freq_val, int):
        raise ValueError("'frequency_seconds' must be an integer.")
    if freq_val < 2 or freq_val > 3600:
        raise ValueError("'frequency_seconds' must be between 2 and 3600 (inclusive).")

    # Handle retention_days
    if "retention_days" not in payload:
        raise ValueError("Missing required key: 'retention_days'")
    
    ret_val = payload["retention_days"]
    # Explicitly reject booleans
    if isinstance(ret_val, bool):
        raise ValueError("'retention_days' must be an integer, not a boolean.")
    if not isinstance(ret_val, int):
        raise ValueError("'retention_days' must be an integer.")
    if ret_val < 1 or ret_val > 365:
        raise ValueError("'retention_days' must be between 1 and 365 (inclusive).")

    return Policy(frequency_seconds=freq_val, retention_days=ret_val)

def expiry_for(sampled_at: datetime, retention_days: int) -> datetime:
    """
    Calculates the expiry timestamp based on a sampled time and retention days.
    
    Args:
        sampled_at (datetime): The time the data was sampled. Must be timezone-aware UTC.
        retention_days (int): Number of days to retain the data.
        
    Returns:
        datetime: The expiry timestamp as a timezone-aware UTC datetime.
        
    Raises:
        ValueError: If sampled_at is not timezone-aware or not in UTC.
    """
    # Validate input timezone awareness and UTC status
    if sampled_at.tzinfo is None or sampled_at.utcoffset() is None:
        raise ValueError("sampled_at must be a timezone-aware datetime.")
    
    utc_offset = sampled_at.utcoffset()
    if utc_offset is not None and utc_offset.total_seconds() != 0:
        raise ValueError("sampled_at must be in UTC (offset of zero).")

    return sampled_at + timedelta(days=retention_days)