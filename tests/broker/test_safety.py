from datetime import datetime, timezone

import pytest

from fx.broker.base import (
    BrokerEnvironment,
    Order,
    OrderSide,
    OrderType,
    Tick,
)
from fx.broker.oanda import OandaAdapter
from fx.broker.paper import PaperBroker
from fx.broker.safety import (
    LiveTradingDisabledError,
    OrderValidationError,
    SafetyGuard,
)


@pytest.fixture
def paper_guard() -> SafetyGuard:
    b = PaperBroker()
    b.inject_tick(
        Tick(instrument="USD_JPY", bid=150.0, ask=150.02, timestamp=datetime.now(tz=timezone.utc))
    )
    return SafetyGuard(b, enable_live_trading=False)


@pytest.fixture
def live_guard_disabled() -> SafetyGuard:
    return SafetyGuard(
        OandaAdapter(account_id="test", api_token="test", environment=BrokerEnvironment.LIVE),
        enable_live_trading=False,
    )


@pytest.fixture
def live_guard_enabled() -> SafetyGuard:
    return SafetyGuard(
        OandaAdapter(account_id="test", api_token="test", environment=BrokerEnvironment.LIVE),
        enable_live_trading=True,
    )


def _make_order(
    *,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    units: int = 1000,
    order_type: OrderType = OrderType.MARKET,
) -> Order:
    return Order(
        id="",
        instrument="USD_JPY",
        side=OrderSide.BUY,
        order_type=order_type,
        units=units,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


# --- inner access ---


def test_no_inner_property(paper_guard: SafetyGuard) -> None:
    assert not hasattr(paper_guard, "inner")


def test_unsafe_inner_for_tests(paper_guard: SafetyGuard) -> None:
    inner = paper_guard._unsafe_inner_for_tests()
    assert isinstance(inner, PaperBroker)


# --- practice always allowed ---


async def test_paper_always_allowed(paper_guard: SafetyGuard) -> None:
    assert paper_guard.is_live_allowed is True
    result = await paper_guard.place_order(_make_order())
    assert result.filled_price is not None


# --- live blocked ---


async def test_live_place_order_blocked(live_guard_disabled: SafetyGuard) -> None:
    with pytest.raises(LiveTradingDisabledError):
        await live_guard_disabled.place_order(_make_order())


async def test_live_cancel_blocked(live_guard_disabled: SafetyGuard) -> None:
    with pytest.raises(LiveTradingDisabledError):
        await live_guard_disabled.cancel_order("123")


async def test_live_close_position_blocked(live_guard_disabled: SafetyGuard) -> None:
    with pytest.raises(LiveTradingDisabledError):
        await live_guard_disabled.close_position("USD_JPY")


# --- live enabled but SL/TP required ---


async def test_live_market_no_sl_rejected(live_guard_enabled: SafetyGuard) -> None:
    with pytest.raises(OrderValidationError, match="stop_loss"):
        await live_guard_enabled.place_order(
            _make_order(take_profit=151.0)
        )


async def test_live_market_no_tp_rejected(live_guard_enabled: SafetyGuard) -> None:
    with pytest.raises(OrderValidationError, match="take_profit"):
        await live_guard_enabled.place_order(
            _make_order(stop_loss=149.0)
        )


async def test_live_limit_no_sl_allowed(live_guard_enabled: SafetyGuard) -> None:
    # Limit orders don't require SL/TP at the SafetyGuard level
    # (will fail at OANDA because not connected, but validation passes)
    order = _make_order(order_type=OrderType.LIMIT)
    order.price = 149.50
    # No LiveTradingDisabledError or OrderValidationError should be raised
    # The actual call will fail with RuntimeError("Not connected") which is expected
    with pytest.raises(RuntimeError, match="Not connected"):
        await live_guard_enabled.place_order(order)


# --- units validation ---


async def test_zero_units_rejected(paper_guard: SafetyGuard) -> None:
    with pytest.raises(OrderValidationError, match="units"):
        await paper_guard.place_order(_make_order(units=0))


async def test_negative_units_rejected(paper_guard: SafetyGuard) -> None:
    with pytest.raises(OrderValidationError, match="units"):
        await paper_guard.place_order(_make_order(units=-100))


# --- delegate read operations ---


async def test_guard_delegates_read_operations(paper_guard: SafetyGuard) -> None:
    tick = await paper_guard.get_tick("USD_JPY")
    assert tick.bid == 150.0

    balance = await paper_guard.get_account_balance()
    assert balance == 1_000_000.0

    positions = await paper_guard.get_positions()
    assert positions == []

    orders = await paper_guard.get_open_orders()
    assert orders == []


async def test_guard_properties(paper_guard: SafetyGuard) -> None:
    assert paper_guard.name == "paper"
    assert paper_guard.environment == BrokerEnvironment.PRACTICE
    assert paper_guard.capabilities.supports_market_order is True
