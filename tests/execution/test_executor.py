from datetime import datetime, timezone

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import Order, OrderIntent, OrderSide, OrderStatus, OrderType, Tick
from fx.broker.paper import PaperBroker
from fx.execution.executor import OrderExecutionError, OrderExecutor, ReduceNotSupportedError


@pytest.fixture
def setup() -> tuple[PaperBroker, InMemoryTradeLogger, OrderExecutor]:
    broker = PaperBroker()
    broker.inject_tick(
        Tick(instrument="USD_JPY", bid=150.0, ask=150.02, timestamp=datetime.now(tz=timezone.utc))
    )
    logger = InMemoryTradeLogger()
    executor = OrderExecutor(broker, logger)
    return broker, logger, executor


async def test_execute_market_order(setup: tuple[PaperBroker, InMemoryTradeLogger, OrderExecutor]) -> None:
    _, logger, executor = setup
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    )
    er = await executor.execute(order)
    assert er.order.filled_price == 150.02
    assert er.trade_close is None
    assert len(logger.get_events(AuditEventType.ORDER_FILLED)) == 1


async def test_execute_close_returns_trade_close(setup: tuple[PaperBroker, InMemoryTradeLogger, OrderExecutor]) -> None:
    broker, logger, executor = setup
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    close = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
        intent=OrderIntent.CLOSE,
    )
    er = await executor.execute(close)
    assert er.order.status == OrderStatus.FILLED
    assert er.trade_close is not None
    assert er.trade_close.close_price == 150.00
    assert er.trade_close.pnl == pytest.approx(-20.0)
    assert er.trade_close.entry_price == 150.02
    assert len(logger.get_events(AuditEventType.TRADE_CLOSED)) == 1


async def test_close_no_position(setup: tuple[PaperBroker, InMemoryTradeLogger, OrderExecutor]) -> None:
    _, logger, executor = setup
    close = Order(
        id="", instrument="EUR_USD", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
        intent=OrderIntent.CLOSE,
    )
    er = await executor.execute(close)
    assert er.order.status == OrderStatus.CANCELLED
    assert er.trade_close is None


async def test_execute_logs_failure(setup: tuple[PaperBroker, InMemoryTradeLogger, OrderExecutor]) -> None:
    _, logger, executor = setup
    order = Order(
        id="", instrument="EUR_USD", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    )
    with pytest.raises(OrderExecutionError):
        await executor.execute(order)
    assert len(logger.get_events(AuditEventType.ORDER_FAILED)) == 1


async def test_raise_on_error_false() -> None:
    broker = PaperBroker()
    logger = InMemoryTradeLogger()
    executor = OrderExecutor(broker, logger, raise_on_error=False)
    order = Order(
        id="", instrument="EUR_USD", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    )
    er = await executor.execute(order)
    assert er.trade_close is None
    assert len(logger.get_events(AuditEventType.ORDER_FAILED)) == 1


async def test_reduce_intent_rejected(setup: tuple[PaperBroker, InMemoryTradeLogger, OrderExecutor]) -> None:
    _, logger, executor = setup
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=500,
        intent=OrderIntent.REDUCE,
    )
    with pytest.raises(ReduceNotSupportedError):
        await executor.execute(order)
    assert order.status == OrderStatus.REJECTED
    failed = logger.get_events(AuditEventType.ORDER_FAILED)
    assert len(failed) == 1


async def test_reduce_no_raise() -> None:
    broker = PaperBroker()
    broker.inject_tick(
        Tick(instrument="USD_JPY", bid=150.0, ask=150.02, timestamp=datetime.now(tz=timezone.utc))
    )
    logger = InMemoryTradeLogger()
    executor = OrderExecutor(broker, logger, raise_on_error=False)
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=500,
        intent=OrderIntent.REDUCE,
    )
    er = await executor.execute(order)
    assert er.order.status == OrderStatus.REJECTED
