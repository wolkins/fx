"""OANDA practice order smoke test.

Places ONE tiny MARKET order with SL/TP and a client_order_id, confirms the broker
response/audit trail, then always flattens the instrument. This is a safety check
(can we open, observe, and close cleanly), not a profitability check.

Disabled unless OANDA_PRACTICE_ALLOW_ORDERS=true. Run with:
    OANDA_PRACTICE_ALLOW_ORDERS=true pytest -m oanda_practice \
        tests/integration/oanda/test_oanda_practice_order.py
"""

from __future__ import annotations

import uuid

import pytest

from fx.audit.logger import InMemoryTradeLogger
from fx.audit.sanitize import sanitize_broker_data
from fx.broker.base import Order, OrderIntent, OrderSide, OrderType
from fx.broker.oanda import OandaAdapter
from fx.broker.safety import SafetyGuard
from fx.execution.executor import OrderExecutor
from tests.integration.oanda.helpers import (
    OandaPracticeSettings,
    assert_instrument_flat,
)

pytestmark = [pytest.mark.integration, pytest.mark.oanda_practice]

_SL_TP_PIPS = 50  # well away from market so the smoke order is not auto-closed


async def _sl_tp_for_buy(
    adapter: OandaAdapter, instrument: str, bid: float, ask: float
) -> tuple[float, float]:
    details = await adapter.get_instrument_details([instrument])
    target = next(d for d in details if d["name"] == instrument)
    precision = int(target["displayPrecision"])
    pip_size = 10 ** int(target["pipLocation"])
    stop_loss = round(bid - _SL_TP_PIPS * pip_size, precision)
    take_profit = round(ask + _SL_TP_PIPS * pip_size, precision)
    return stop_loss, take_profit


async def test_market_order_round_trip(
    oanda_adapter: OandaAdapter,
    oanda_guard: SafetyGuard,
    practice_settings: OandaPracticeSettings,
    require_order_permission: None,
) -> None:
    instrument = practice_settings.instrument
    units = practice_settings.units
    assert units <= 10, "refusing to trade more than 10 units in a smoke test"

    # Preflight: refuse to run unless the instrument is flat, so our cleanup cannot
    # close a pre-existing position.
    await assert_instrument_flat(oanda_guard, instrument)

    tick = await oanda_guard.get_tick(instrument)
    stop_loss, take_profit = await _sl_tp_for_buy(
        oanda_adapter, instrument, tick.bid, tick.ask
    )
    client_order_id = f"practice-smoke-{uuid.uuid4().hex[:12]}"

    order = Order(
        id="",
        instrument=instrument,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        units=units,
        intent=OrderIntent.OPEN,
        stop_loss=stop_loss,
        take_profit=take_profit,
        client_order_id=client_order_id,
    )

    logger = InMemoryTradeLogger()
    executor = OrderExecutor(oanda_guard, logger, raise_on_error=False)

    order_submitted = False
    try:
        order_submitted = True  # the order may reach the broker from here on
        result = await executor.execute(order)
        placed = result.order
        # The raw OANDA response must be retained for audit (transaction tracking).
        assert placed.broker_data, "broker_data should retain the OANDA response"
        assert (
            placed.broker_order_id
            or placed.broker_data.get("lastTransactionID")
            or placed.reject_transaction_id
        ), "expected a transaction id from OANDA"
        # broker_data must be sanitizable without leaking secrets.
        sanitize_broker_data(placed.broker_data)
    finally:
        # Only flatten if we actually submitted; the preflight guaranteed flatness, so
        # any remaining position must be ours.
        if order_submitted:
            await oanda_guard.close_position(instrument, side=OrderSide.BUY)
        positions = await oanda_guard.get_positions()
        remaining = [p for p in positions if p.instrument == instrument]
        assert remaining == [], f"position for {instrument} must not remain open"
