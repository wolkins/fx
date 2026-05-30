"""OANDA practice reject / audit smoke tests.

Two layers:
- SafetyGuard rejects bad orders *before* they reach OANDA (no network write).
- OANDA itself rejects an invalid order, and the reject payload is retained in the
  audit trail (sanitized).
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
from tests.integration.oanda.helpers import OandaPracticeSettings

pytestmark = [pytest.mark.integration, pytest.mark.oanda_practice]


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


async def test_oanda_reject_payload_is_audited(
    oanda_adapter: OandaAdapter,
    oanda_guard: SafetyGuard,
    practice_settings: OandaPracticeSettings,
    require_order_permission: None,
) -> None:
    """An order with an invalid stop loss (above market for a BUY) is rejected by
    OANDA; the reject details land in broker_data and the audit log."""
    instrument = practice_settings.instrument
    units = practice_settings.units

    details = await oanda_adapter.get_instrument_details([instrument])
    target = next(d for d in details if d["name"] == instrument)
    precision = int(target["displayPrecision"])
    pip_size = 10 ** int(target["pipLocation"])

    tick = await oanda_guard.get_tick(instrument)
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
    executor = OrderExecutor(oanda_guard, logger, raise_on_error=False)

    try:
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
        # Defensive: ensure nothing accidentally opened.
        await oanda_guard.close_position(instrument, side=OrderSide.BUY)
        positions = await oanda_guard.get_positions()
        assert [p for p in positions if p.instrument == instrument] == []
