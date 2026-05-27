import json
import logging
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


# --- InMemoryTradeLogger ---


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


# --- log_risk_rejected ---


def test_log_risk_rejected_with_risk_state() -> None:
    logger = InMemoryTradeLogger()
    risk_state = {
        "account_balance": 1_000_000.0,
        "daily_pnl": -15_000.0,
        "open_positions": 2,
        "config": {"max_position_size": 100_000},
    }
    logger.log_risk_rejected(
        _make_order(),
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


# --- log_risk_accepted payload ---


def test_log_risk_accepted_with_risk_state() -> None:
    logger = InMemoryTradeLogger()
    risk_state = {"account_balance": 1_000_000.0, "open_positions": 1}
    logger.log_risk_accepted(_make_order(), strategy_id="s1", risk_state=risk_state)
    events = logger.get_events(AuditEventType.ORDER_ACCEPTED_BY_RISK)
    assert len(events) == 1
    payload = events[0].payload
    assert "order" in payload
    assert payload["order"]["units"] == 1000
    assert payload["risk_state"]["account_balance"] == 1_000_000.0


def test_log_risk_accepted_without_risk_state() -> None:
    logger = InMemoryTradeLogger()
    logger.log_risk_accepted(_make_order())
    events = logger.get_events(AuditEventType.ORDER_ACCEPTED_BY_RISK)
    assert "order" in events[0].payload
    assert "risk_state" not in events[0].payload


# --- log_risk_bypassed ---


def test_log_risk_bypassed_close() -> None:
    logger = InMemoryTradeLogger()
    logger.log_risk_bypassed(_make_order(intent=OrderIntent.CLOSE))
    events = logger.get_events(AuditEventType.RISK_BYPASSED_FOR_CLOSE)
    assert len(events) == 1


def test_log_risk_bypassed_reduce() -> None:
    logger = InMemoryTradeLogger()
    logger.log_risk_bypassed(_make_order(intent=OrderIntent.REDUCE))
    events = logger.get_events(AuditEventType.RISK_BYPASSED_FOR_REDUCE)
    assert len(events) == 1


# --- log_sent_to_broker payload ---


def test_log_sent_to_broker_includes_payload() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order(stop_loss=149.50, take_profit=151.00, price=150.00)
    logger.log_sent_to_broker(order)
    events = logger.get_events(AuditEventType.ORDER_SENT_TO_BROKER)
    assert len(events) == 1
    payload = events[0].payload
    assert payload["stop_loss"] == 149.50
    assert payload["take_profit"] == 151.00
    assert payload["intent"] == "open"
    assert payload["client_order_id"] == "strat-001"


# --- log_order_result ---


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


def test_log_order_rejected_by_broker_includes_broker_data() -> None:
    logger = InMemoryTradeLogger()
    broker_data = {
        "reject_reason": "INSUFFICIENT_MARGIN",
        "errorCode": "ERR_001",
        "errorMessage": "Not enough margin",
        "relatedTransactionIDs": ["100", "101"],
        "lastTransactionID": "101",
    }
    order = _make_order(
        status=OrderStatus.REJECTED,
        reject_transaction_id="txn-99",
        broker_data=broker_data,
    )
    logger.log_order_result(order)
    events = logger.get_events(AuditEventType.ORDER_REJECTED_BY_BROKER)
    assert len(events) == 1
    assert events[0].reason_code == "INSUFFICIENT_MARGIN"
    assert events[0].message == "Not enough margin"
    payload = events[0].payload
    assert payload["reject_transaction_id"] == "txn-99"
    assert payload["broker_data"]["errorCode"] == "ERR_001"
    assert payload["broker_data"]["relatedTransactionIDs"] == ["100", "101"]


def test_log_order_cancelled() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order(
        status=OrderStatus.CANCELLED,
        broker_data={"cancel_reason": "CLIENT_REQUEST"},
    )
    logger.log_order_result(order)
    events = logger.get_events(AuditEventType.ORDER_CANCELLED)
    assert len(events) == 1


# --- SL/TP/trade close ---


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


# --- JSONLinesTradeLogger ---


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


def test_jsonlines_flush(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file)
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    content = log_file.read_text(encoding="utf-8")
    assert "POSITION_SL_TRIGGERED" in content


def test_jsonlines_fsync(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file, fsync=True)
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    content = log_file.read_text(encoding="utf-8")
    assert "POSITION_SL_TRIGGERED" in content


def test_jsonlines_creates_parent_dirs(tmp_path: Path) -> None:
    log_file = tmp_path / "nested" / "deep" / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file)
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    content = log_file.read_text(encoding="utf-8")
    assert "POSITION_SL_TRIGGERED" in content


def test_jsonlines_fail_on_error_raises(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file, fail_on_error=True)
    # Make file unwritable
    log_file.touch()
    log_file.chmod(0o000)
    try:
        with pytest.raises(AuditLogWriteError):
            logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    finally:
        log_file.chmod(0o644)


def test_jsonlines_fail_on_error_no_event_in_memory(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file, fail_on_error=True)
    log_file.touch()
    log_file.chmod(0o000)
    try:
        with pytest.raises(AuditLogWriteError):
            logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
        assert len(logger.get_events()) == 0
    finally:
        log_file.chmod(0o644)


def test_jsonlines_no_fail_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file, fail_on_error=False)
    log_file.touch()
    log_file.chmod(0o000)
    try:
        with caplog.at_level(logging.WARNING):
            logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
        assert "Failed to write audit log" in caplog.text
        assert len(logger.get_events()) == 0
    finally:
        log_file.chmod(0o644)


def test_jsonlines_get_events(tmp_path: Path) -> None:
    log_file = tmp_path / "trades.jsonl"
    logger = JSONLinesTradeLogger(log_file)
    logger.log_sl_triggered("USD_JPY", "buy", 1000, 149.50, -520.0)
    logger.log_tp_triggered("EUR_USD", "sell", 500, 1.0850, 250.0)
    assert len(logger.get_events()) == 2
    assert len(logger.get_events(AuditEventType.POSITION_SL_TRIGGERED)) == 1


# --- payload content ---


def test_order_payload_includes_intent() -> None:
    logger = InMemoryTradeLogger()
    order = _make_order(intent=OrderIntent.CLOSE, stop_loss=149.50, take_profit=151.00)
    logger.log_order_submitted(order)
    payload = logger.get_events()[0].payload
    assert payload["intent"] == "close"
    assert payload["stop_loss"] == 149.50


# --- new event types exist ---


def test_new_event_types() -> None:
    assert AuditEventType.SIGNAL_GENERATED.value == "SIGNAL_GENERATED"
    assert AuditEventType.SIGNAL_HOLD.value == "SIGNAL_HOLD"
    assert AuditEventType.ORDER_INTENT_CREATED.value == "ORDER_INTENT_CREATED"
    assert AuditEventType.RISK_BYPASSED_FOR_CLOSE.value == "RISK_BYPASSED_FOR_CLOSE"
    assert AuditEventType.RISK_BYPASSED_FOR_REDUCE.value == "RISK_BYPASSED_FOR_REDUCE"
    assert AuditEventType.REVERSE_SPLIT.value == "REVERSE_SPLIT"
    assert AuditEventType.ORDER_FAILED.value == "ORDER_FAILED"
