from datetime import datetime, timezone

import pytest

from fx.broker.base import BrokerCapabilities, Tick


def test_tick_spread() -> None:
    tick = Tick(
        instrument="USD_JPY",
        bid=150.000,
        ask=150.020,
        timestamp=datetime.now(tz=timezone.utc),
    )
    assert tick.spread == pytest.approx(0.020)


def test_capabilities_defaults() -> None:
    caps = BrokerCapabilities()
    assert caps.supports_rest_api is False
    assert caps.supports_stop_order is False
    assert caps.min_trade_units == 1
    assert caps.max_leverage == 25


def test_capabilities_custom() -> None:
    caps = BrokerCapabilities(
        supports_rest_api=True,
        supports_stop_order=True,
        min_trade_units=1000,
        max_leverage=50,
        spread_source="oanda",
    )
    assert caps.supports_rest_api is True
    assert caps.supports_stop_order is True
    assert caps.min_trade_units == 1000
