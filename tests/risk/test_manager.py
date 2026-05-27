import time

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import Order, OrderIntent, OrderSide, OrderType, Position
from fx.risk.config import RiskConfig
from fx.risk.manager import RiskManager


def _make_order(
    instrument: str = "USD_JPY",
    side: OrderSide = OrderSide.BUY,
    units: int = 1000,
    order_type: OrderType = OrderType.MARKET,
    intent: OrderIntent = OrderIntent.OPEN,
    client_order_id: str | None = None,
) -> Order:
    return Order(
        id="",
        instrument=instrument,
        side=side,
        order_type=order_type,
        units=units,
        intent=intent,
        client_order_id=client_order_id,
    )


def _make_position(
    instrument: str = "USD_JPY",
    side: OrderSide = OrderSide.BUY,
    units: int = 1000,
) -> Position:
    return Position(instrument=instrument, side=side, units=units, avg_price=150.0)


@pytest.fixture
def logger() -> InMemoryTradeLogger:
    return InMemoryTradeLogger()


@pytest.fixture
def manager(logger: InMemoryTradeLogger) -> RiskManager:
    return RiskManager(RiskConfig(), logger)


# --- basic allowed/rejected ---


def test_order_allowed(manager: RiskManager, logger: InMemoryTradeLogger) -> None:
    decision = manager.evaluate(_make_order(), [], 1_000_000.0)
    assert decision.allowed is True
    assert len(logger.get_events(AuditEventType.ORDER_SUBMITTED)) == 1
    assert len(logger.get_events(AuditEventType.ORDER_ACCEPTED_BY_RISK)) == 1


def test_max_position_size_exceeded(manager: RiskManager, logger: InMemoryTradeLogger) -> None:
    decision = manager.evaluate(_make_order(units=200_000), [], 1_000_000.0)
    assert decision.allowed is False
    assert decision.code == "MAX_POSITION_SIZE_EXCEEDED"
    assert decision.severity == "warning"
    assert len(logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)) == 1


def test_max_open_positions_exceeded(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_open_positions=2), logger)
    positions = [_make_position("USD_JPY"), _make_position("EUR_USD")]
    decision = mgr.evaluate(_make_order(instrument="GBP_USD"), positions, 1_000_000.0)
    assert decision.allowed is False
    assert decision.code == "MAX_OPEN_POSITIONS_EXCEEDED"


def test_existing_instrument_allowed_despite_max_positions(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_open_positions=2), logger)
    positions = [_make_position("USD_JPY"), _make_position("EUR_USD")]
    decision = mgr.evaluate(_make_order(instrument="USD_JPY"), positions, 1_000_000.0)
    assert decision.allowed is True


# --- daily loss: ratio-based ---


def test_max_daily_loss_ratio_exceeded(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_ratio=0.02), logger)
    # 2% of 1M = 20,000. daily_pnl = -25,000 → loss = 25,000 >= 20,000
    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=-25_000.0)
    assert decision.allowed is False
    assert decision.code == "MAX_DAILY_LOSS_EXCEEDED"
    assert decision.severity == "critical"


def test_daily_loss_within_ratio_limit(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_ratio=0.02), logger)
    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=-10_000.0)
    assert decision.allowed is True


# --- daily loss: fixed amount ---


def test_max_daily_loss_amount_exceeded(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_amount=15_000.0), logger)
    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=-16_000.0)
    assert decision.allowed is False
    assert decision.code == "MAX_DAILY_LOSS_EXCEEDED"
    assert decision.details["loss_limit"] == 15_000.0


def test_max_daily_loss_amount_within_limit(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_amount=15_000.0), logger)
    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=-10_000.0)
    assert decision.allowed is True


def test_positive_pnl_always_allowed(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_ratio=0.02), logger)
    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=50_000.0)
    assert decision.allowed is True


def test_zero_balance_rejected(manager: RiskManager) -> None:
    decision = manager.evaluate(_make_order(), [], 0.0)
    assert decision.allowed is False
    assert decision.code == "ZERO_BALANCE"
    assert decision.severity == "critical"


# --- CLOSE/REDUCE bypass daily loss ---


def test_close_order_allowed_despite_daily_loss(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_ratio=0.02), logger)
    order = _make_order(intent=OrderIntent.CLOSE)
    decision = mgr.evaluate(order, [], 1_000_000.0, daily_pnl=-25_000.0)
    assert decision.allowed is True


def test_reduce_order_allowed_despite_daily_loss(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_ratio=0.02), logger)
    order = _make_order(intent=OrderIntent.REDUCE)
    decision = mgr.evaluate(order, [], 1_000_000.0, daily_pnl=-25_000.0)
    assert decision.allowed is True


def test_open_order_blocked_when_daily_loss_exceeded(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_daily_loss_ratio=0.02), logger)
    order = _make_order(intent=OrderIntent.OPEN)
    decision = mgr.evaluate(order, [], 1_000_000.0, daily_pnl=-25_000.0)
    assert decision.allowed is False


def test_close_bypasses_max_position_size(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_position_size=500), logger)
    order = _make_order(units=1000, intent=OrderIntent.CLOSE)
    decision = mgr.evaluate(order, [], 1_000_000.0)
    assert decision.allowed is True


# --- duplicate guard ---


def test_duplicate_order_rejected(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(duplicate_window_seconds=5.0), logger)
    d1 = mgr.evaluate(_make_order(), [], 1_000_000.0)
    assert d1.allowed is True
    d2 = mgr.evaluate(_make_order(), [], 1_000_000.0)
    assert d2.allowed is False
    assert d2.code == "DUPLICATE_ORDER"


def test_different_orders_not_duplicate(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(duplicate_window_seconds=5.0), logger)
    d1 = mgr.evaluate(_make_order(instrument="USD_JPY"), [], 1_000_000.0)
    assert d1.allowed is True
    d2 = mgr.evaluate(_make_order(instrument="EUR_USD"), [], 1_000_000.0)
    assert d2.allowed is True


def test_duplicate_expired(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(duplicate_window_seconds=0.1), logger)
    d1 = mgr.evaluate(_make_order(), [], 1_000_000.0)
    assert d1.allowed is True
    time.sleep(0.15)
    d2 = mgr.evaluate(_make_order(), [], 1_000_000.0)
    assert d2.allowed is True


def test_duplicate_guard_uses_client_order_id(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(duplicate_window_seconds=5.0), logger)
    d1 = mgr.evaluate(
        _make_order(client_order_id="sig-001"), [], 1_000_000.0
    )
    assert d1.allowed is True
    # Same instrument/side/units but different client_order_id → not duplicate
    d2 = mgr.evaluate(
        _make_order(client_order_id="sig-002"), [], 1_000_000.0
    )
    assert d2.allowed is True


def test_duplicate_guard_same_client_order_id(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(duplicate_window_seconds=5.0), logger)
    d1 = mgr.evaluate(
        _make_order(client_order_id="sig-001"), [], 1_000_000.0
    )
    assert d1.allowed is True
    d2 = mgr.evaluate(
        _make_order(client_order_id="sig-001"), [], 1_000_000.0
    )
    assert d2.allowed is False
    assert d2.code == "DUPLICATE_ORDER"


def test_close_not_blocked_by_duplicate_guard(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(duplicate_window_seconds=5.0), logger)
    d1 = mgr.evaluate(_make_order(intent=OrderIntent.OPEN), [], 1_000_000.0)
    assert d1.allowed is True
    # Same order but intent=CLOSE → always allowed, bypasses duplicate guard
    d2 = mgr.evaluate(_make_order(intent=OrderIntent.CLOSE), [], 1_000_000.0)
    assert d2.allowed is True


# --- audit log content ---


def test_strategy_id_in_audit(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(), logger)
    mgr.evaluate(_make_order(), [], 1_000_000.0, strategy_id="ma_cross")
    submitted = logger.get_events(AuditEventType.ORDER_SUBMITTED)
    assert submitted[0].strategy_id == "ma_cross"
    accepted = logger.get_events(AuditEventType.ORDER_ACCEPTED_BY_RISK)
    assert accepted[0].strategy_id == "ma_cross"


def test_risk_decision_details(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_position_size=500), logger)
    decision = mgr.evaluate(_make_order(units=1000), [], 1_000_000.0)
    assert not decision.allowed
    assert decision.details["order_units"] == 1000
    assert decision.details["max_position_size"] == 500


def test_risk_decision_has_severity_and_created_at(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(), logger)
    decision = mgr.evaluate(_make_order(), [], 1_000_000.0)
    assert decision.severity == "info"
    assert decision.created_at is not None


def test_rejection_log_includes_risk_state(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_position_size=500), logger)
    positions = [_make_position("EUR_USD")]
    mgr.evaluate(_make_order(units=1000), positions, 1_000_000.0, daily_pnl=-5_000.0)
    rejected = logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)
    assert len(rejected) == 1
    payload = rejected[0].payload
    assert "risk_state" in payload
    rs = payload["risk_state"]
    assert rs["account_balance"] == 1_000_000.0
    assert rs["daily_pnl"] == -5_000.0
    assert rs["open_positions"] == 1
    assert rs["config"]["max_position_size"] == 500


def test_rejection_log_includes_order_details(logger: InMemoryTradeLogger) -> None:
    mgr = RiskManager(RiskConfig(max_position_size=500), logger)
    mgr.evaluate(
        _make_order(units=1000, client_order_id="sig-x"),
        [], 1_000_000.0,
    )
    rejected = logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)
    payload = rejected[0].payload
    assert "order" in payload
    assert payload["order"]["units"] == 1000
    assert payload["order"]["client_order_id"] == "sig-x"
