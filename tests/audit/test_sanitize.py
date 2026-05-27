from fx.audit.sanitize import sanitize_broker_data


def test_redacts_sensitive_keys() -> None:
    data = {
        "token": "secret-abc",
        "account_id": "123-456",
        "authorization": "Bearer xyz",
        "api_key": "key-789",
        "errorCode": "ERR_001",
        "errorMessage": "fail",
    }
    result = sanitize_broker_data(data)
    assert result["token"] == "***REDACTED***"
    assert result["account_id"] == "***REDACTED***"
    assert result["authorization"] == "***REDACTED***"
    assert result["api_key"] == "***REDACTED***"
    assert result["errorCode"] == "ERR_001"
    assert result["errorMessage"] == "fail"


def test_nested_sanitization() -> None:
    data = {
        "outer": {
            "token": "secret",
            "relatedTransactionIDs": ["100", "101"],
        },
        "lastTransactionID": "200",
    }
    result = sanitize_broker_data(data)
    assert result["outer"]["token"] == "***REDACTED***"
    assert result["outer"]["relatedTransactionIDs"] == ["100", "101"]
    assert result["lastTransactionID"] == "200"


def test_list_sanitization() -> None:
    data = {
        "items": [{"password": "secret", "value": "ok"}],
    }
    result = sanitize_broker_data(data)
    assert result["items"][0]["password"] == "***REDACTED***"
    assert result["items"][0]["value"] == "ok"


def test_case_insensitive() -> None:
    data = {"Token": "secret", "ACCOUNT_ID": "id", "ApiKey": "key"}
    result = sanitize_broker_data(data)
    assert result["Token"] == "***REDACTED***"
    assert result["ACCOUNT_ID"] == "***REDACTED***"
    assert result["ApiKey"] == "***REDACTED***"


def test_preserves_oanda_tracking_fields() -> None:
    data = {
        "lastTransactionID": "500",
        "relatedTransactionIDs": ["498", "499", "500"],
        "errorCode": "INVALID_UNITS",
        "errorMessage": "units too small",
        "reject_reason": "MARGIN_CHECK_FAILED",
        "reject_transaction_id": "499",
        "orderReissueTransaction": {"id": "501"},
        "orderReissueRejectTransaction": {"id": "502"},
    }
    result = sanitize_broker_data(data)
    assert result == data
