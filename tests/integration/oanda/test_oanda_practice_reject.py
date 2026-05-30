"""OANDA practice reject / audit smoke tests.

Two clearly separated layers:

1. SafetyGuard reject (no network write): bad units, or — under protective mode —
   an OPEN missing client_order_id / stop_loss / take_profit, are rejected before the
   order ever reaches OANDA. Uses the protective ``oanda_guard``.

2. OANDA actual reject: protective mode is intentionally OFF so an invalid order
   (bad stop loss) reaches OANDA and we can confirm the reject payload is audited.
   Uses ``oanda_guard_without_protective_mode_for_reject_test``.
"""

from __future__ import annotations

import uuid

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import Order, OrderIntent, OrderSide, OrderType
from fx.broker.oanda import OandaAdapter
from fx.broker.safety import OrderValidationError, SafetyGuard
from fx.execution.executor import OrderExecutor
from tests.integration.oanda.helpers import (
    OandaPracticeSettings,
    assert_instrument_flat,
)

pytestmark = [pytest.mark.integration, pytest.mark.oanda_practice]


# --- Layer 1: SafetyGuard rejects before reaching OANDA ---


async def test_invalid_units_rejected_before_reaching_oanda(
    oanda_guard: SafetyGuard, practice_settings: OandaPracticeSettings
) -> None:
    """units <= 0 is rejected by SafetyGuard; OANDA is never contacted."""
    order = Order(
        id="",
        instrument=practice_settings.instrument,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        units=0,
        intent=OrderIntent.OPEN,
    )
    with pytest.raises(OrderValidationError):
        await oanda_guard.place_order(order)


async def test_protective_open_without_fields_rejected_before_oanda(
    oanda_guard: SafetyGuard, practice_settings: OandaPracticeSettings
) -> None:
    """Under protective mode, an OPEN without SL/TP/client_order_id is rejected by
    SafetyGuard before reaching OANDA."""
    order = Order(
        id="",
        instrument=practice_settings.instrument,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        units=practice_settings.units,
        intent=OrderIntent.OPEN,
    )
    with pytest.raises(OrderValidationError, match="stop_loss"):
        await oanda_guard.place_order(order)


# --- Layer 2: order intentionally reaches OANDA and is rejected there ---


async def test_oanda_actual_reject_payload_is_audited(
    oanda_adapter: OandaAdapter,
    oanda_guard_without_protective_mode_for_reject_test: SafetyGuard,
    practice_settings: OandaPracticeSettings,
    require_order_permission: None,
) -> None:
    """With protective mode OFF, an order with an invalid stop loss (above market for
    a BUY) reaches OANDA and is rejected; the reject details land in broker_data and
    the audit log."""
    guard = oanda_guard_without_protective_mode_for_reject_test
    instrument = practice_settings.instrument
    units = practice_settings.units

    # Preflight: refuse to run unless the instrument is flat, so any cleanup we do
    # cannot close a pre-existing position.
    await assert_instrument_flat(guard, instrument)

    details = await oanda_adapter.get_instrument_details([instrument])
    target = next(d for d in details if d["name"] == instrument)
    precision = int(target["displayPrecision"])
    pip_size = 10 ** int(target["pipLocation"])

    tick = await guard.get_tick(instrument)
    # Invalid for a BUY: stop loss placed ABOVE the current ask.
    bad_stop_loss = round(tick.ask + 50 * pip_size, precision)
    client_order_id = f"practice-smoke-reject-{uuid.uuid4().hex[:12]}"

    order = Order(
        id="",
        instrument=instrument,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        units=units,
        intent=OrderIntent.OPEN,
        stop_loss=bad_stop_loss,
        client_order_id=client_order_id,
    )

    logger = InMemoryTradeLogger()
    executor = OrderExecutor(guard, logger, raise_on_error=False)

    order_submitted = False
    try:
        order_submitted = True  # the order may reach the broker from here on
        result = await executor.execute(order)
        # Should not have filled; reject info must be retained.
        assert result.order.broker_data, "broker_data must retain the OANDA response"
        assert (
            result.order.broker_data.get("reject_reason")
            or result.order.broker_data.get("errorCode")
            or result.order.broker_data.get("errorMessage")
        ), "expected OANDA reject details in broker_data"

        events = {e.event_type for e in logger.get_events()}
        assert (
            AuditEventType.ORDER_REJECTED_BY_BROKER in events
            or AuditEventType.ORDER_FAILED in events
        ), "expected a reject/failure audit event"
    finally:
        # Defensive: only flatten if we submitted. The preflight guaranteed flatness,
        # so any remaining position must be ours.
        if order_submitted:
            await guard.close_position(instrument, side=OrderSide.BUY)
        positions = await guard.get_positions()
        assert [p for p in positions if p.instrument == instrument] == []
