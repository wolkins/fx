from datetime import datetime, timezone

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import OrderIntent, OrderSide, OrderStatus, Position, Tick
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
    signal = Signal(action=SignalAction.HOLD, instrument="USD_JPY", strategy_id="test", reason="no_signal")
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert results == []
    hold_events = logger.get_events(AuditEventType.SIGNAL_HOLD)
    assert len(hold_events) == 1
    assert hold_events[0].payload["reason"] == "no_signal"


async def test_reverse_to_buy_with_real_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, logger, manager = system
    from fx.broker.base import Order, OrderType
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    ))
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].side == OrderSide.SELL

    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 2
    assert results[0].intent == OrderIntent.CLOSE
    assert results[0].side == OrderSide.SELL
    assert results[0].status == OrderStatus.FILLED
    assert results[1].intent == OrderIntent.OPEN
    assert results[1].side == OrderSide.BUY
    assert results[1].status == OrderStatus.FILLED

    final_positions = await broker.get_positions()
    assert len(final_positions) == 1
    assert final_positions[0].side == OrderSide.BUY
    assert final_positions[0].units == 1000
    assert len(logger.get_events(AuditEventType.REVERSE_SPLIT)) == 1
    closed_events = logger.get_events(AuditEventType.TRADE_CLOSED)
    assert len(closed_events) == 1
    assert closed_events[0].payload["close_price"] == 150.02
    # SELL at 150.00, close at ask 150.02 → pnl = (150.00 - 150.02) * 500 = -10
    assert closed_events[0].payload["pnl"] == pytest.approx(-10.0)


async def test_reverse_to_sell_with_real_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, _, manager = system
    from fx.broker.base import Order, OrderType
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=800,
    ))
    positions = await broker.get_positions()

    signal = Signal(
        action=SignalAction.REVERSE_TO_SELL, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 2
    assert results[0].intent == OrderIntent.CLOSE
    assert results[0].side == OrderSide.BUY
    assert results[1].intent == OrderIntent.OPEN
    assert results[1].side == OrderSide.SELL

    final_positions = await broker.get_positions()
    assert len(final_positions) == 1
    assert final_positions[0].side == OrderSide.SELL


async def test_reverse_without_existing_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, _, manager = system
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].intent == OrderIntent.OPEN
    assert results[0].side == OrderSide.BUY


async def test_close_buy_with_real_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, _, manager = system
    from fx.broker.base import Order, OrderType
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    positions = await broker.get_positions()

    signal = Signal(action=SignalAction.CLOSE_BUY, instrument="USD_JPY", strategy_id="test")
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 1
    assert results[0].intent == OrderIntent.CLOSE
    assert results[0].side == OrderSide.BUY
    assert results[0].status == OrderStatus.FILLED

    final = await broker.get_positions()
    assert len(final) == 0


async def test_close_sell_with_real_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, _, manager = system
    from fx.broker.base import Order, OrderType
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    ))
    positions = await broker.get_positions()

    signal = Signal(action=SignalAction.CLOSE_SELL, instrument="USD_JPY", strategy_id="test")
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 1
    assert results[0].side == OrderSide.SELL
    assert results[0].status == OrderStatus.FILLED

    final = await broker.get_positions()
    assert len(final) == 0


async def test_risk_rejection_blocks_open(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, logger, manager = system
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=200_000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert results == []
    assert len(logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)) == 1


async def test_daily_loss_blocks_open_allows_close(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, _, manager = system
    from fx.broker.base import Order, OrderType
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    positions = await broker.get_positions()

    close_signal = Signal(
        action=SignalAction.CLOSE_BUY, instrument="USD_JPY", strategy_id="test",
    )
    results = await manager.process_signal(close_signal, positions, 1_000_000.0, daily_pnl=-25_000.0)
    assert len(results) == 1
    assert results[0].status == OrderStatus.FILLED

    open_signal = Signal(
        action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test2", units=1000,
    )
    results = await manager.process_signal(open_signal, [], 1_000_000.0, daily_pnl=-25_000.0)
    assert results == []


async def test_deterministic_client_order_id(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, _, manager = system
    signal = Signal(
        action=SignalAction.BUY, instrument="USD_JPY",
        strategy_id="ema_cross", units=1000, id="sig-001",
    )
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert results[0].client_order_id == "ema_cross:sig-001:open:USD_JPY"


async def test_signal_id_in_audit_payload(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, logger, manager = system
    signal = Signal(
        action=SignalAction.BUY, instrument="USD_JPY",
        strategy_id="test", units=1000, id="sig-xyz",
    )
    await manager.process_signal(signal, [], 1_000_000.0)
    generated = logger.get_events(AuditEventType.SIGNAL_GENERATED)
    assert generated[0].payload["signal_id"] == "sig-xyz"
    intent = logger.get_events(AuditEventType.ORDER_INTENT_CREATED)
    assert intent[0].payload["signal_id"] == "sig-xyz"


async def test_projected_position_size_blocks(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, logger, manager = system
    existing = [Position(instrument="USD_JPY", side=OrderSide.BUY, units=90_000, avg_price=150.0)]
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=20_000)
    results = await manager.process_signal(signal, existing, 1_000_000.0)
    assert results == []
    rejected = logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)
    assert rejected[0].payload["risk_state"]["config"]["max_position_size"] == 100_000
