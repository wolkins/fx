from datetime import datetime, timezone

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import OrderIntent, OrderSide, Position, Tick
from fx.broker.paper import PaperBroker
from fx.execution.executor import OrderExecutor
from fx.execution.manager import TradeManager
from fx.risk.config import RiskConfig
from fx.risk.manager import RiskManager
from fx.signal.model import Signal, SignalAction


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@pytest.fixture
def system() -> tuple[PaperBroker, InMemoryTradeLogger, TradeManager]:
    broker = PaperBroker()
    broker.inject_tick(Tick(instrument="USD_JPY", bid=150.0, ask=150.02, timestamp=_now()))
    logger = InMemoryTradeLogger()
    risk = RiskManager(RiskConfig(), logger)
    executor = OrderExecutor(broker, logger)
    manager = TradeManager(risk, executor, logger)
    return broker, logger, manager


async def test_buy_signal(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, logger, manager = system
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].filled_price == 150.02

    assert len(logger.get_events(AuditEventType.SIGNAL_GENERATED)) == 1
    assert len(logger.get_events(AuditEventType.ORDER_INTENT_CREATED)) == 1
    assert len(logger.get_events(AuditEventType.ORDER_FILLED)) == 1


async def test_sell_signal(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, _, manager = system
    signal = Signal(action=SignalAction.SELL, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].filled_price == 150.0
    assert results[0].side == OrderSide.SELL


async def test_hold_signal(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, logger, manager = system
    signal = Signal(action=SignalAction.HOLD, instrument="USD_JPY", strategy_id="test")
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert results == []
    assert len(logger.get_events(AuditEventType.SIGNAL_HOLD)) == 1


async def test_reverse_to_buy_decomposes(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    broker, logger, manager = system
    sell_pos = Position(instrument="USD_JPY", side=OrderSide.SELL, units=500, avg_price=150.0)
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, [sell_pos], 1_000_000.0)
    assert len(results) == 2
    assert results[0].intent == OrderIntent.CLOSE
    assert results[0].side == OrderSide.SELL
    assert results[1].intent == OrderIntent.OPEN
    assert results[1].side == OrderSide.BUY
    assert len(logger.get_events(AuditEventType.REVERSE_SPLIT)) == 1


async def test_reverse_without_existing_position(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, _, manager = system
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].intent == OrderIntent.OPEN
    assert results[0].side == OrderSide.BUY


async def test_close_buy_signal(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, _, manager = system
    signal = Signal(action=SignalAction.CLOSE_BUY, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].intent == OrderIntent.CLOSE


async def test_risk_rejection_blocks_open(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, logger, manager = system
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=200_000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert results == []
    assert len(logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)) == 1


async def test_daily_loss_blocks_open_but_allows_close(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    broker, logger, manager = system

    signal_close = Signal(
        action=SignalAction.CLOSE_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal_close, [], 1_000_000.0, daily_pnl=-25_000.0)
    assert len(results) == 1

    signal_open = Signal(
        action=SignalAction.BUY, instrument="USD_JPY",
        strategy_id="test2", units=1000,
    )
    results = await manager.process_signal(signal_open, [], 1_000_000.0, daily_pnl=-25_000.0)
    assert results == []


async def test_orders_have_client_order_id(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, _, manager = system
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="ema_cross", units=1000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert results[0].client_order_id is not None
    assert results[0].client_order_id.startswith("ema_cross-")
