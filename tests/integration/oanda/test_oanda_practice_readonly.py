"""Read-only OANDA practice smoke tests. No orders are placed here.

Run with: pytest -m oanda_practice tests/integration/oanda/test_oanda_practice_readonly.py
Requires OANDA_ENV=practice, OANDA_API_TOKEN, OANDA_ACCOUNT_ID.
"""

from __future__ import annotations

import pytest

from fx.broker.oanda import OandaAdapter
from tests.integration.oanda.helpers import OandaPracticeSettings

pytestmark = [pytest.mark.integration, pytest.mark.oanda_practice]


async def test_account_summary(oanda_adapter: OandaAdapter) -> None:
    summary = await oanda_adapter.get_account_summary()
    # Structural checks only — never assert/log the secret account id value.
    assert "currency" in summary
    assert "balance" in summary
    float(summary["balance"])


async def test_instrument_details_contains_target(
    oanda_adapter: OandaAdapter, practice_settings: OandaPracticeSettings
) -> None:
    details = await oanda_adapter.get_instrument_details([practice_settings.instrument])
    assert len(details) >= 1
    names = {d["name"] for d in details}
    assert practice_settings.instrument in names


async def test_pricing_has_bid_ask(
    oanda_adapter: OandaAdapter, practice_settings: OandaPracticeSettings
) -> None:
    price = await oanda_adapter.get_pricing(practice_settings.instrument)
    assert price.get("instrument") == practice_settings.instrument
    assert price.get("bids")
    assert price.get("asks")


async def test_get_tick_maps_pricing(
    oanda_adapter: OandaAdapter, practice_settings: OandaPracticeSettings
) -> None:
    tick = await oanda_adapter.get_tick(practice_settings.instrument)
    assert tick.instrument == practice_settings.instrument
    assert tick.bid > 0
    assert tick.ask > 0
    assert tick.ask >= tick.bid


async def test_candles_returned(
    oanda_adapter: OandaAdapter, practice_settings: OandaPracticeSettings
) -> None:
    candles = await oanda_adapter.get_candles(practice_settings.instrument, "M1", 5)
    assert len(candles) >= 1
    assert "mid" in candles[0] or "bid" in candles[0] or "ask" in candles[0]


async def test_instrument_spec_reflectable_fields(
    oanda_adapter: OandaAdapter, practice_settings: OandaPracticeSettings
) -> None:
    """The instrument definition exposes the fields InstrumentSpec needs:
    pip location, display precision, and trade-unit precision."""
    details = await oanda_adapter.get_instrument_details([practice_settings.instrument])
    target = next(d for d in details if d["name"] == practice_settings.instrument)
    assert "pipLocation" in target
    assert "displayPrecision" in target
    assert "tradeUnitsPrecision" in target
    pip_size = 10 ** int(target["pipLocation"])
    assert pip_size > 0
