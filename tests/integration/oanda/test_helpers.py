"""Network-free unit tests for the OANDA practice test helpers.

These intentionally carry no oanda_practice marker: they use PaperBroker and run as
part of the default suite.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fx.broker.base import Order, OrderSide, OrderType, Tick
from fx.broker.paper import PaperBroker
from tests.integration.oanda.helpers import assert_instrument_flat


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _broker_with_tick(instrument: str = "USD_JPY") -> PaperBroker:
    broker = PaperBroker()
    broker.inject_tick(Tick(instrument=instrument, bid=150.0, ask=150.02, timestamp=_now()))
    return broker


async def test_assert_instrument_flat_passes_when_empty() -> None:
    broker = _broker_with_tick("USD_JPY")
    await assert_instrument_flat(broker, "USD_JPY")


async def test_assert_instrument_flat_fails_when_position_exists() -> None:
    broker = _broker_with_tick("USD_JPY")
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    with pytest.raises(pytest.fail.Exception, match="existing position"):
        await assert_instrument_flat(broker, "USD_JPY")


async def test_assert_instrument_flat_ignores_other_instrument() -> None:
    broker = _broker_with_tick("USD_JPY")
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    # A position on USD_JPY must not block an EUR_USD smoke test.
    await assert_instrument_flat(broker, "EUR_USD")
