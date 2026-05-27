import time

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import Order, OrderSide, OrderType, Position
from fx.risk.config import RiskConfig
from fx.risk.manager import RiskManager


def _make_order(
    instrument: str = "USD_JPY",
    side: OrderSide = OrderSide.BUY,
    units: int = 1000,
    order_type: OrderType = OrderType.MARKET,
) -> Order:
    return Order(
        id="",
        instrument=instrument,
        side=side,
        order_type=order_type,
        units=units,
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


def test_order_allowed(manager: RiskManager, logger: InMemoryTradeLogger) -> None:
    order = _make_order()
    decision = manager.evaluate(order, [], 1_000_000.0)
    assert decision.allowed is True
    assert len(logger.get_events(AuditEventType.ORDER_SUBMITTED)) == 1
    assert len(logger.get_events(AuditEventType.ORDER_ACCEPTED_BY_RISK)) == 1


def test_max_position_size_exceeded(manager: RiskManager, logger: InMemoryTradeLogger) -> None:
    order = _make_order(units=200_000)
    decision = manager.evaluate(order, [], 1_000_000.0)
    assert decision.allowed is False
    assert decision.code == "MAX_POSITION_SIZE_EXCEEDED"
    assert len(logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)) == 1


def test_max_open_positions_exceeded(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(max_open_positions=2)
    mgr = RiskManager(config, logger)

    positions = [
        _make_position("USD_JPY"),
        _make_position("EUR_USD"),
    ]
    order = _make_order(instrument="GBP_USD")
    decision = mgr.evaluate(order, positions, 1_000_000.0)
    assert decision.allowed is False
    assert decision.code == "MAX_OPEN_POSITIONS_EXCEEDED"


def test_existing_instrument_allowed_despite_max_positions(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(max_open_positions=2)
    mgr = RiskManager(config, logger)

    positions = [
        _make_position("USD_JPY"),
        _make_position("EUR_USD"),
    ]
    order = _make_order(instrument="USD_JPY")
    decision = mgr.evaluate(order, positions, 1_000_000.0)
    assert decision.allowed is True


def test_max_daily_loss_exceeded(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(max_daily_loss=0.02)
    mgr = RiskManager(config, logger)

    # 2% of 1M = 20,000. daily_pnl = -25,000 → loss_ratio = 0.025
    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=-25_000.0)
    assert decision.allowed is False
    assert decision.code == "MAX_DAILY_LOSS_EXCEEDED"


def test_daily_loss_within_limit(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(max_daily_loss=0.02)
    mgr = RiskManager(config, logger)

    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=-10_000.0)
    assert decision.allowed is True


def test_positive_pnl_always_allowed(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(max_daily_loss=0.02)
    mgr = RiskManager(config, logger)

    decision = mgr.evaluate(_make_order(), [], 1_000_000.0, daily_pnl=50_000.0)
    assert decision.allowed is True


def test_zero_balance_rejected(manager: RiskManager) -> None:
    decision = manager.evaluate(_make_order(), [], 0.0)
    assert decision.allowed is False
    assert decision.code == "ZERO_BALANCE"


def test_duplicate_order_rejected(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(duplicate_window_seconds=5.0)
    mgr = RiskManager(config, logger)

    order1 = _make_order()
    order2 = _make_order()

    d1 = mgr.evaluate(order1, [], 1_000_000.0)
    assert d1.allowed is True

    d2 = mgr.evaluate(order2, [], 1_000_000.0)
    assert d2.allowed is False
    assert d2.code == "DUPLICATE_ORDER"


def test_different_orders_not_duplicate(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(duplicate_window_seconds=5.0)
    mgr = RiskManager(config, logger)

    d1 = mgr.evaluate(_make_order(instrument="USD_JPY"), [], 1_000_000.0)
    assert d1.allowed is True

    d2 = mgr.evaluate(_make_order(instrument="EUR_USD"), [], 1_000_000.0)
    assert d2.allowed is True


def test_duplicate_expired(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(duplicate_window_seconds=0.1)
    mgr = RiskManager(config, logger)

    d1 = mgr.evaluate(_make_order(), [], 1_000_000.0)
    assert d1.allowed is True

    time.sleep(0.15)

    d2 = mgr.evaluate(_make_order(), [], 1_000_000.0)
    assert d2.allowed is True


def test_strategy_id_in_audit(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig()
    mgr = RiskManager(config, logger)

    mgr.evaluate(_make_order(), [], 1_000_000.0, strategy_id="ma_cross")
    submitted = logger.get_events(AuditEventType.ORDER_SUBMITTED)
    assert submitted[0].strategy_id == "ma_cross"
    accepted = logger.get_events(AuditEventType.ORDER_ACCEPTED_BY_RISK)
    assert accepted[0].strategy_id == "ma_cross"


def test_risk_decision_details(logger: InMemoryTradeLogger) -> None:
    config = RiskConfig(max_position_size=500)
    mgr = RiskManager(config, logger)

    decision = mgr.evaluate(_make_order(units=1000), [], 1_000_000.0)
    assert not decision.allowed
    assert decision.details["order_units"] == 1000
    assert decision.details["max_position_size"] == 500
