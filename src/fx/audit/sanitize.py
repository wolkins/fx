from __future__ import annotations

from typing import Any

_REDACTED = "***REDACTED***"
_SENSITIVE_KEYS = frozenset({
    "authorization",
    "token",
    "api_key",
    "apikey",
    "password",
    "secret",
    "account_id",
    "accountid",
})


def sanitize_broker_data(data: dict[str, Any]) -> dict[str, Any]:
    result = _sanitize(data)
    assert isinstance(result, dict)
    return result


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _REDACTED if k.lower() in _SENSITIVE_KEYS else _sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value
