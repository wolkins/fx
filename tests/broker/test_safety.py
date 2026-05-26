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
from fx.broker.safety import LiveTradingDisabledError, SafetyGuard


@pytest.fixture
def paper_guard() -> SafetyGuard:
    b = PaperBroker()
    b.inject_tick(
        Tick(instrument="USD_JPY", bid=150.0, ask=150.02, timestamp=datetime.now(tz=timezone.utc))
    )
    return SafetyGuard(b, enable_live_trading=False)


def _make_order() -> Order:
    return Order(
        id="",
        instrument="USD_JPY",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        units=1000,
    )


async def test_paper_always_allowed(paper_guard: SafetyGuard) -> None:
    assert paper_guard.is_live_allowed is True
    result = await paper_guard.place_order(_make_order())
    assert result.filled_price is not None


async def test_live_blocked_by_default() -> None:
    live_broker = OandaAdapter(
        account_id="test",
        api_token="test",
        environment=BrokerEnvironment.LIVE,
    )
    guard = SafetyGuard(live_broker, enable_live_trading=False)
    assert guard.is_live_allowed is False

    with pytest.raises(LiveTradingDisabledError):
        await guard.place_order(_make_order())


async def test_live_cancel_blocked() -> None:
    live_broker = OandaAdapter(
        account_id="test",
        api_token="test",
        environment=BrokerEnvironment.LIVE,
    )
    guard = SafetyGuard(live_broker, enable_live_trading=False)
    with pytest.raises(LiveTradingDisabledError):
        await guard.cancel_order("123")


async def test_live_allowed_when_enabled() -> None:
    live_broker = OandaAdapter(
        account_id="test",
        api_token="test",
        environment=BrokerEnvironment.LIVE,
    )
    guard = SafetyGuard(live_broker, enable_live_trading=True)
    assert guard.is_live_allowed is True


async def test_close_position_blocked_on_live() -> None:
    live_broker = OandaAdapter(
        account_id="test",
        api_token="test",
        environment=BrokerEnvironment.LIVE,
    )
    guard = SafetyGuard(live_broker, enable_live_trading=False)

    with pytest.raises(LiveTradingDisabledError):
        await guard.close_position("USD_JPY")


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
