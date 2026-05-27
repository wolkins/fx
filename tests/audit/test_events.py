from fx.audit.events import AuditEvent, AuditEventType


def test_event_to_dict() -> None:
    event = AuditEvent(
        event_type=AuditEventType.ORDER_SUBMITTED,
        instrument="USD_JPY",
        side="buy",
        units=1000,
        order_type="market",
        client_order_id="strat-001",
    )
    d = event.to_dict()
    assert d["event_type"] == "ORDER_SUBMITTED"
    assert d["instrument"] == "USD_JPY"
    assert d["units"] == 1000
    assert d["client_order_id"] == "strat-001"
    assert "timestamp" in d


def test_event_types() -> None:
    assert AuditEventType.ORDER_SUBMITTED.value == "ORDER_SUBMITTED"
    assert AuditEventType.POSITION_SL_TRIGGERED.value == "POSITION_SL_TRIGGERED"
