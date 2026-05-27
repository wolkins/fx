from datetime import datetime, timezone

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import Order, OrderSide, OrderType, Tick
from fx.broker.paper import PaperBroker
from fx.execution.executor import OrderExecutionError, OrderExecutor


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
    result = await executor.execute(order)
    assert result.filled_price == 150.02

    sent = logger.get_events(AuditEventType.ORDER_SENT_TO_BROKER)
    assert len(sent) == 1
    filled = logger.get_events(AuditEventType.ORDER_FILLED)
    assert len(filled) == 1


async def test_execute_logs_failure(setup: tuple[PaperBroker, InMemoryTradeLogger, OrderExecutor]) -> None:
    broker, logger, executor = setup
    order = Order(
        id="", instrument="EUR_USD", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    )
    with pytest.raises(OrderExecutionError):
        await executor.execute(order)

    sent = logger.get_events(AuditEventType.ORDER_SENT_TO_BROKER)
    assert len(sent) == 1
    failed = logger.get_events(AuditEventType.ORDER_FAILED)
    assert len(failed) == 1
