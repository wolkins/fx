import json
from pathlib import Path

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import (
    AuditLogWriteError,
    InMemoryTradeLogger,
    JSONLinesTradeLogger,
)
from fx.broker.base import Order, OrderIntent, OrderSide, OrderStatus, OrderType


def _make_order(**kwargs: object) -> Order:
    defaults: dict[str, object] = {
        "id": "test-1",
        "instrument": "USD_JPY",
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "units": 1000,
        "client_order_id": "strat-001",
    }
    defaults.update(kwargs)
    return Order(**defaults)  # type: ignore[arg-type]


def test_in_memory_log_and_get() -> None:
    logger = InMemoryTradeLogger()
    logger.log_order_submitted(_make_order(), strategy_id="test-strat")
    events = logger.get_events()
    assert len(events) == 1
    assert events[0].event_type == AuditEventType.ORDER_SUBMITTED
    assert events[0].strategy_id == "test-strat"


def test_in_memory_filter_by_type() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order()
    logger.log_order_submitted(order)
    logger.log_risk_accepted(order)
    assert len(logger.get_events(AuditEventType.ORDER_SUBMITTED)) == 1
    assert len(logger.get_events(AuditEventType.ORDER_ACCEPTED_BY_RISK)) == 1
    assert len(logger.get_events(AuditEventType.ORDER_FILLED)) == 0


def test_log_risk_rejected_with_risk_state() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order()
    risk_state = {
        "account_balance": 1_000_000.0,
        "daily_pnl": -15_000.0,
        "open_positions": 2,
        "config": {"max_position_size": 100_000},
    }
    logger.log_risk_rejected(
        order,
        reason_code="MAX_POSITION_SIZE_EXCEEDED",
        message="Too large",
        strategy_id="s1",
        risk_state=risk_state,
    )
    events = logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)
    assert len(events) == 1
    assert events[0].reason_code == "MAX_POSITION_SIZE_EXCEEDED"
    assert events[0].payload["risk_state"]["account_balance"] == 1_000_000.0
    assert events[0].payload["order"]["units"] == 1000


def test_log_order_filled() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order(
        status=OrderStatus.FILLED,
        filled_price=150.02,
        fill_transaction_id="txn-42",
        broker_order_id="oanda-1",
    )
    logger.log_order_result(order)
    events = logger.get_events(AuditEventType.ORDER_FILLED)
    assert len(events) == 1
    assert events[0].payload["filled_price"] == 150.02


def test_log_order_rejected_by_broker() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order(
        status=OrderStatus.REJECTED,
        reject_transaction_id="txn-99",
        broker_data={"reject_reason": "INSUFFICIENT_MARGIN", "errorCode": "ERR_001"},
    )
    logger.log_order_result(order)
    events = logger.get_events(AuditEventType.ORDER_REJECTED_BY_BROKER)
    assert len(events) == 1
    assert events[0].reason_code == "INSUFFICIENT_MARGIN"


def test_log_order_cancelled() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order(
        status=OrderStatus.CANCELLED,
        broker_data={"cancel_reason": "CLIENT_REQUEST"},
    )
    logger.log_order_result(order)
    events = logger.get_events(AuditEventType.ORDER_CANCELLED)
    assert len(events) == 1


def test_log_sl_triggered() -> None:
    logger = InMemoryTradeLogger()
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    events = logger.get_events(AuditEventType.POSITION_SL_TRIGGERED)
    assert len(events) == 1
    assert events[0].payload["pnl"] == -520.0


def test_log_tp_triggered() -> None:
    logger = InMemoryTradeLogger()
    logger.log_tp_triggered("USD_JPY", "buy", 1000, 151.00, 980.0)
    events = logger.get_events(AuditEventType.POSITION_TP_TRIGGERED)
    assert len(events) == 1


def test_log_trade_closed() -> None:
    logger = InMemoryTradeLogger()
    logger.log_trade_closed("USD_JPY", "buy", 1000, 150.50, 480.0, "manual")
    events = logger.get_events(AuditEventType.TRADE_CLOSED)
    assert len(events) == 1
    assert events[0].reason_code == "manual"


def test_jsonlines_writes_to_file(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file)

    order = _make_order()
    logger.log_order_submitted(order, strategy_id="test")
    logger.log_risk_accepted(order)

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["event_type"] == "ORDER_SUBMITTED"
    assert first["instrument"] == "USD_JPY"


def test_jsonlines_one_event_per_line(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file)

    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    logger.log_tp_triggered("EUR_USD", "sell", 500, 1.0850, 250.0)

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "event_type" in parsed
        assert "timestamp" in parsed


def test_jsonlines_flush(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file)
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    # File should be readable immediately after log (flushed)
    content = log_file.read_text(encoding="utf-8")
    assert "POSITION_SL_TRIGGERED" in content


def test_jsonlines_fsync(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file, fsync=True)
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    content = log_file.read_text(encoding="utf-8")
    assert "POSITION_SL_TRIGGERED" in content


def test_jsonlines_fail_on_error_raises(tmp_path: Path) -> None:
    log_file = tmp_path / "nonexistent_dir" / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file, fail_on_error=True)
    with pytest.raises(AuditLogWriteError):
        logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)


def test_jsonlines_no_fail_on_error_silent(tmp_path: Path) -> None:
    log_file = tmp_path / "nonexistent_dir" / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file, fail_on_error=False)
    # Should not raise
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)


def test_jsonlines_get_events(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file)

    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    logger.log_tp_triggered("EUR_USD", "sell", 500, 1.0850, 250.0)

    all_events = logger.get_events()
    assert len(all_events) == 2
    sl_events = logger.get_events(AuditEventType.POSITION_SL_TRIGGERED)
    assert len(sl_events) == 1


def test_order_payload_includes_intent() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order(intent=OrderIntent.CLOSE, stop_loss=149.50, take_profit=151.00)
    logger.log_order_submitted(order)
    events = logger.get_events()
    payload = events[0].payload
    assert payload["intent"] == "close"
    assert payload["stop_loss"] == 149.50
    assert payload["take_profit"] == 151.00
