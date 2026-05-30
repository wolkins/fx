"""Network-free OANDA integration tests using FakeOandaTransport.

These run as part of the default suite (no oanda_practice marker, no credentials, no
network). They exercise OandaAdapter fill/reject/close/transaction tracking, its
SafetyGuard integration, and a TradeManager reverse flow.
"""

from __future__ import annotations

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.audit.sanitize import sanitize_broker_data
from fx.broker.base import (
    BrokerEnvironment,
    Order,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from fx.broker.oanda import OandaAdapter
from fx.broker.safety import OrderValidationError, SafetyGuard
from fx.execution.executor import OrderExecutor
from fx.execution.manager import TradeManager
from fx.risk.config import RiskConfig
from fx.risk.manager import RiskManager
from fx.signal.model import Signal, SignalAction
from tests.broker.fakes.fake_oanda import (
    FakeOandaTransport,
    order_reject_body,
)


async def _adapter(fake: FakeOandaTransport) -> OandaAdapter:
    adapter = OandaAdapter(
        account_id="acc", api_token="tok",
        environment=BrokerEnvironment.PRACTICE, transport=fake,
    )
    await adapter.connect()
    return adapter


def _open_order(
    *,
    side: OrderSide = OrderSide.BUY,
    units: int = 1000,
    stop_loss: float | None = 149.0,
    take_profit: float | None = 151.0,
    client_order_id: str | None = "coid-1",
) -> Order:
    return Order(
        id="", instrument="USD_JPY", side=side, order_type=OrderType.MARKET,
        units=units, intent=OrderIntent.OPEN,
        stop_loss=stop_loss, take_profit=take_profit, client_order_id=client_order_id,
    )


# --- read-only ---


async def test_get_account_summary() -> None:
    fake = FakeOandaTransport(account_currency="JPY", balance=1_000_000.0)
    adapter = await _adapter(fake)
    summary = await adapter.get_account_summary()
    assert summary["currency"] == "JPY"
    assert float(summary["balance"]) == 1_000_000.0


async def test_get_instrument_details_jpy_and_non_jpy() -> None:
    fake = FakeOandaTransport()
    adapter = await _adapter(fake)

    usd_jpy = (await adapter.get_instrument_details(["USD_JPY"]))[0]
    assert usd_jpy["pipLocation"] == -2
    assert usd_jpy["displayPrecision"] == 3
    assert usd_jpy["tradeUnitsPrecision"] == 0

    eur_usd = (await adapter.get_instrument_details(["EUR_USD"]))[0]
    assert eur_usd["pipLocation"] == -4
    assert eur_usd["displayPrecision"] == 5


async def test_get_pricing_and_tick() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    adapter = await _adapter(fake)

    price = await adapter.get_pricing("USD_JPY")
    assert price["instrument"] == "USD_JPY"
    assert price["bids"][0]["price"] == "150.0"

    tick = await adapter.get_tick("USD_JPY")
    assert tick.bid == 150.0
    assert tick.ask == 150.02


async def test_get_candles() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    adapter = await _adapter(fake)
    candles = await adapter.get_candles("USD_JPY", "M1", 5)
    assert len(candles) >= 1
    assert "mid" in candles[0]


# --- place_order fill ---


async def test_market_buy_fill_transaction_tracking() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    adapter = await _adapter(fake)

    result = await adapter.place_order(_open_order(side=OrderSide.BUY))

    assert result.status == OrderStatus.FILLED
    assert result.filled_price == 150.02  # buy fills at ask
    assert result.broker_order_id
    assert result.fill_transaction_id
    assert result.create_transaction_id
    assert result.broker_data.get("lastTransactionID")
    assert result.broker_data.get("relatedTransactionIDs")
    assert result.broker_data.get("clientExtensions", {}).get("id") == "coid-1"

    # client_order_id was sent to OANDA as clientExtensions.
    last = fake.requests[-1]
    assert last["method"] == "POST"
    assert last["json"]["order"]["clientExtensions"]["id"] == "coid-1"


async def test_market_sell_fill_units_signed() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    adapter = await _adapter(fake)

    result = await adapter.place_order(_open_order(side=OrderSide.SELL))

    assert result.status == OrderStatus.FILLED
    assert result.filled_price == 150.0  # sell fills at bid
    assert fake.requests[-1]["json"]["order"]["units"].startswith("-")


# --- reject ---


async def test_order_reject_audited_via_executor() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    fake.next_order_reject = order_reject_body("STOP_LOSS_ON_FILL_LOSS")
    adapter = await _adapter(fake)

    logger = InMemoryTradeLogger()
    executor = OrderExecutor(adapter, logger, raise_on_error=False)

    result = await executor.execute(_open_order())

    assert result.order.status == OrderStatus.REJECTED
    assert result.order.broker_data.get("reject_reason") == "STOP_LOSS_ON_FILL_LOSS"
    assert result.order.broker_data.get("errorCode") == "STOP_LOSS_ON_FILL_LOSS"
    assert result.order.reject_transaction_id == "999"
    assert len(logger.get_events(AuditEventType.ORDER_REJECTED_BY_BROKER)) == 1
    # broker_data must be sanitizable without raising.
    assert isinstance(sanitize_broker_data(result.order.broker_data), dict)


# --- close ---


async def test_close_long_position_via_executor() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    adapter = await _adapter(fake)

    logger = InMemoryTradeLogger()
    executor = OrderExecutor(adapter, logger, raise_on_error=False)
    close_order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000, intent=OrderIntent.CLOSE,
    )

    result = await executor.execute(close_order)

    tc = result.trade_close
    assert tc is not None
    assert tc.instrument == "USD_JPY"
    assert tc.side == OrderSide.BUY
    assert tc.units == 1000
    assert tc.close_price == 150.0  # long closes at bid
    assert tc.pnl == 1234.0
    assert tc.closed_at is not None
    assert tc.broker_data
    assert len(logger.get_events(AuditEventType.TRADE_CLOSED)) == 1


async def test_close_short_position_via_executor() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    adapter = await _adapter(fake)

    logger = InMemoryTradeLogger()
    executor = OrderExecutor(adapter, logger, raise_on_error=False)
    close_order = Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1000, intent=OrderIntent.CLOSE,
    )

    result = await executor.execute(close_order)

    tc = result.trade_close
    assert tc is not None
    assert tc.side == OrderSide.SELL
    assert tc.close_price == 150.02  # short closes at ask
    assert tc.pnl == -56.0


async def test_close_reject_returns_no_trade_close() -> None:
    from tests.broker.fakes.fake_oanda import close_reject_body

    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    fake.next_close_reject = close_reject_body()
    adapter = await _adapter(fake)

    logger = InMemoryTradeLogger()
    executor = OrderExecutor(adapter, logger, raise_on_error=False)
    close_order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000, intent=OrderIntent.CLOSE,
    )

    result = await executor.execute(close_order)

    assert result.trade_close is None
    assert result.order.status == OrderStatus.CANCELLED


# --- SafetyGuard protective mode through the adapter ---


async def _protective_guard(fake: FakeOandaTransport) -> SafetyGuard:
    adapter = await _adapter(fake)
    return SafetyGuard(
        adapter,
        enable_live_trading=False,
        require_protective_orders_for_open=True,
        require_client_order_id_for_open=True,
    )


async def test_protective_guard_blocks_open_without_client_order_id() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    guard = await _protective_guard(fake)
    with pytest.raises(OrderValidationError, match="client_order_id"):
        await guard.place_order(_open_order(client_order_id=None))
    # Order never reached OANDA.
    assert not any(r["method"] == "POST" for r in fake.requests)


async def test_protective_guard_blocks_open_without_stop_loss() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    guard = await _protective_guard(fake)
    with pytest.raises(OrderValidationError, match="stop_loss"):
        await guard.place_order(_open_order(stop_loss=None))


async def test_protective_guard_blocks_open_without_take_profit() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    guard = await _protective_guard(fake)
    with pytest.raises(OrderValidationError, match="take_profit"):
        await guard.place_order(_open_order(take_profit=None))


async def test_protective_guard_allows_full_open_reaches_transport() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    guard = await _protective_guard(fake)
    result = await guard.place_order(_open_order())
    assert result.status == OrderStatus.FILLED
    assert any(r["method"] == "POST" for r in fake.requests)


async def test_protective_guard_does_not_block_close_or_reduce() -> None:
    fake = FakeOandaTransport()
    guard = await _protective_guard(fake)
    # No raise for CLOSE / REDUCE even without SL/TP/client_order_id.
    guard._validate_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000, intent=OrderIntent.CLOSE,
    ))
    guard._validate_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000, intent=OrderIntent.REDUCE,
    ))


# --- TradeManager reverse flow over the fake adapter ---


async def test_reverse_to_buy_close_then_open_over_fake() -> None:
    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    adapter = await _adapter(fake)

    logger = InMemoryTradeLogger()
    risk = RiskManager(RiskConfig(), logger)
    executor = OrderExecutor(adapter, logger, raise_on_error=False)
    manager = TradeManager(risk, executor, logger)

    existing = [Position(instrument="USD_JPY", side=OrderSide.SELL, units=1000, avg_price=150.5)]
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="t", units=1000,
    )

    results = await manager.process_signal(signal, existing, 1_000_000.0)

    assert len(results) == 2
    assert results[0].order.intent == OrderIntent.CLOSE
    assert results[0].trade_close is not None
    assert results[1].order.intent == OrderIntent.OPEN
    assert results[1].order.status == OrderStatus.FILLED
    assert len(logger.get_events(AuditEventType.REVERSE_SPLIT)) == 1
    assert logger.get_events(AuditEventType.REVERSE_OPEN_SKIPPED) == []
    assert logger.get_events(AuditEventType.REVERSE_OPEN_FAILED) == []


async def test_reverse_skips_open_when_close_rejected_over_fake() -> None:
    from tests.broker.fakes.fake_oanda import close_reject_body

    fake = FakeOandaTransport()
    fake.set_price("USD_JPY", 150.0, 150.02)
    fake.next_close_reject = close_reject_body()
    adapter = await _adapter(fake)

    logger = InMemoryTradeLogger()
    risk = RiskManager(RiskConfig(), logger)
    executor = OrderExecutor(adapter, logger, raise_on_error=False)
    manager = TradeManager(risk, executor, logger)

    existing = [Position(instrument="USD_JPY", side=OrderSide.SELL, units=1000, avg_price=150.5)]
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="t", units=1000,
    )

    results = await manager.process_signal(signal, existing, 1_000_000.0)

    # CLOSE attempted (no trade_close); OPEN skipped, so no buy order POSTed.
    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.CLOSE
    assert len(logger.get_events(AuditEventType.REVERSE_OPEN_SKIPPED)) == 1
    assert not any(r["method"] == "POST" for r in fake.requests)
