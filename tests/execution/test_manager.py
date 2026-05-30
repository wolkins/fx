from datetime import datetime, timezone

import pytest

from fx.audit.events import AuditEventType
from fx.audit.logger import InMemoryTradeLogger
from fx.broker.base import (
    Order,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Tick,
    TradeClose,
)
from fx.broker.paper import PaperBroker
from fx.execution.executor import OrderExecutor
from fx.execution.manager import TradeManager
from fx.execution.policy import PositionPolicy
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
    assert results[0].order.filled_price == 150.02
    assert results[0].trade_close is None
    assert len(logger.get_events(AuditEventType.ORDER_FILLED)) == 1


async def test_sell_signal(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, _, manager = system
    signal = Signal(action=SignalAction.SELL, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].order.filled_price == 150.0
    assert results[0].order.side == OrderSide.SELL


async def test_hold_signal(system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager]) -> None:
    _, logger, manager = system
    signal = Signal(action=SignalAction.HOLD, instrument="USD_JPY", strategy_id="test", reason="no_signal")
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert results == []
    assert len(logger.get_events(AuditEventType.SIGNAL_HOLD)) == 1


async def test_reverse_to_buy_returns_trade_close(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, logger, manager = system
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    ))
    positions = await broker.get_positions()

    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 2

    close_result = results[0]
    assert close_result.order.intent == OrderIntent.CLOSE
    assert close_result.trade_close is not None
    assert close_result.trade_close.entry_price == 150.0
    assert close_result.trade_close.pnl == pytest.approx(-10.0)

    open_result = results[1]
    assert open_result.order.intent == OrderIntent.OPEN
    assert open_result.order.side == OrderSide.BUY
    assert open_result.trade_close is None


async def test_reverse_to_sell_returns_trade_close(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, _, manager = system
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
    assert results[0].trade_close is not None
    assert results[0].trade_close.entry_price == 150.02

    final = await broker.get_positions()
    assert len(final) == 1
    assert final[0].side == OrderSide.SELL


async def test_reverse_without_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, _, manager = system
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.OPEN


async def test_close_buy_with_real_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, _, manager = system
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    positions = await broker.get_positions()

    signal = Signal(action=SignalAction.CLOSE_BUY, instrument="USD_JPY", strategy_id="test")
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 1
    assert results[0].trade_close is not None
    assert results[0].trade_close.entry_price == 150.02

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
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    positions = await broker.get_positions()

    close_signal = Signal(action=SignalAction.CLOSE_BUY, instrument="USD_JPY", strategy_id="test")
    results = await manager.process_signal(close_signal, positions, 1_000_000.0, daily_pnl=-25_000.0)
    assert len(results) == 1
    assert results[0].order.status == OrderStatus.FILLED

    open_signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test2", units=1000)
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
    assert results[0].order.client_order_id == "ema_cross:sig-001:open:USD_JPY"


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


async def test_projected_position_size_blocks(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, logger, manager = system
    existing = [Position(instrument="USD_JPY", side=OrderSide.BUY, units=90_000, avg_price=150.0)]
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=20_000)
    results = await manager.process_signal(signal, existing, 1_000_000.0)
    assert results == []


# --- PositionPolicy ---


def _manager_with_policy(
    broker: PaperBroker, logger: InMemoryTradeLogger, policy: PositionPolicy
) -> TradeManager:
    risk = RiskManager(RiskConfig(), logger)
    executor = OrderExecutor(broker, logger)
    return TradeManager(risk, executor, logger, position_policy=policy)


async def test_reject_opposite_open_buy_against_sell(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, logger, manager = system
    existing = [Position(instrument="USD_JPY", side=OrderSide.SELL, units=1000, avg_price=150.0)]
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, existing, 1_000_000.0)
    assert results == []
    rejected = logger.get_events(AuditEventType.POSITION_POLICY_REJECTED)
    assert len(rejected) == 1
    assert rejected[0].payload["reason"] == "opposite_position_exists"
    assert rejected[0].payload["existing_side"] == "sell"
    assert len(logger.get_events(AuditEventType.ORDER_FILLED)) == 0


async def test_reject_opposite_open_sell_against_buy(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, logger, manager = system
    existing = [Position(instrument="USD_JPY", side=OrderSide.BUY, units=1000, avg_price=150.0)]
    signal = Signal(action=SignalAction.SELL, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, existing, 1_000_000.0)
    assert results == []
    assert len(logger.get_events(AuditEventType.POSITION_POLICY_REJECTED)) == 1


async def test_reject_opposite_open_allows_same_side(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    """Adding to a same-side position is not an opposite open and must be allowed."""
    _, _, manager = system
    existing = [Position(instrument="USD_JPY", side=OrderSide.BUY, units=1000, avg_price=150.0)]
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, existing, 1_000_000.0)
    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.OPEN


async def test_reject_opposite_open_with_no_position(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    _, _, manager = system
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, [], 1_000_000.0)
    assert len(results) == 1
    assert results[0].order.side == OrderSide.BUY


async def test_allow_netting_opens_against_opposite(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, logger, _ = system
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    ))
    positions = await broker.get_positions()
    manager = _manager_with_policy(broker, logger, PositionPolicy.ALLOW_NETTING)

    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.OPEN
    assert results[0].order.side == OrderSide.BUY
    assert len(logger.get_events(AuditEventType.POSITION_POLICY_REJECTED)) == 0


async def test_auto_reverse_split_decomposes(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    broker, logger, _ = system
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    ))
    positions = await broker.get_positions()
    manager = _manager_with_policy(broker, logger, PositionPolicy.AUTO_REVERSE_SPLIT)

    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="test", units=1000)
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 2
    assert results[0].order.intent == OrderIntent.CLOSE
    assert results[0].trade_close is not None
    assert results[1].order.intent == OrderIntent.OPEN
    assert results[1].order.side == OrderSide.BUY

    final = await broker.get_positions()
    assert len(final) == 1
    assert final[0].side == OrderSide.BUY
    assert len(logger.get_events(AuditEventType.REVERSE_SPLIT)) == 1


async def test_reverse_signal_unaffected_by_default_policy(
    system: tuple[PaperBroker, InMemoryTradeLogger, TradeManager],
) -> None:
    """REVERSE_TO_* always decomposes regardless of REJECT_OPPOSITE_OPEN default."""
    broker, _, manager = system
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    ))
    positions = await broker.get_positions()
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="test", units=1000,
    )
    results = await manager.process_signal(signal, positions, 1_000_000.0)
    assert len(results) == 2


# --- reverse / auto-reverse partial-success control ---


class _CloseFailsBroker(PaperBroker):
    """close_position always reports failure (no TradeClose)."""

    async def close_position(
        self, instrument: str, side: OrderSide | None = None
    ) -> TradeClose | None:
        return None


class _CloseRaisesBroker(PaperBroker):
    """close_position raises, simulating a broker error on the CLOSE leg."""

    async def close_position(
        self, instrument: str, side: OrderSide | None = None
    ) -> TradeClose | None:
        raise RuntimeError("simulated close failure")


class _OpenFailsBroker(PaperBroker):
    """place_order raises for OPEN intents once fail_open is set."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_open = False

    async def place_order(self, order: Order) -> Order:
        if self.fail_open and order.intent == OrderIntent.OPEN:
            raise RuntimeError("simulated open failure")
        return await super().place_order(order)


def _manager_for(
    broker: PaperBroker,
    logger: InMemoryTradeLogger,
    policy: PositionPolicy,
    *,
    raise_on_error: bool = False,
) -> TradeManager:
    risk = RiskManager(RiskConfig(), logger)
    executor = OrderExecutor(broker, logger, raise_on_error=raise_on_error)
    return TradeManager(risk, executor, logger, position_policy=policy)


def _tick_broker(broker: PaperBroker) -> PaperBroker:
    broker.inject_tick(Tick(instrument="USD_JPY", bid=150.0, ask=150.02, timestamp=_now()))
    return broker


async def test_auto_reverse_split_skips_open_when_close_fails() -> None:
    broker = _tick_broker(_CloseFailsBroker())
    logger = InMemoryTradeLogger()
    manager = _manager_for(broker, logger, PositionPolicy.AUTO_REVERSE_SPLIT)
    existing = [Position(instrument="USD_JPY", side=OrderSide.SELL, units=1000, avg_price=150.0)]
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="t", units=1000)

    results = await manager.process_signal(signal, existing, 1_000_000.0)

    # CLOSE was attempted (no trade_close); the dependent OPEN was not placed.
    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.CLOSE
    assert results[0].trade_close is None
    assert len(logger.get_events(AuditEventType.REVERSE_OPEN_SKIPPED)) == 1
    assert logger.get_events(AuditEventType.ORDER_FILLED) == []
    assert await broker.get_positions() == []


async def test_auto_reverse_split_skips_open_when_close_raises() -> None:
    broker = _tick_broker(_CloseRaisesBroker())
    logger = InMemoryTradeLogger()
    manager = _manager_for(broker, logger, PositionPolicy.AUTO_REVERSE_SPLIT)
    existing = [Position(instrument="USD_JPY", side=OrderSide.SELL, units=1000, avg_price=150.0)]
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="t", units=1000)

    results = await manager.process_signal(signal, existing, 1_000_000.0)

    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.CLOSE
    assert results[0].trade_close is None
    skipped = logger.get_events(AuditEventType.REVERSE_OPEN_SKIPPED)
    assert len(skipped) == 1
    assert skipped[0].reason_code == "close_leg_failed"


async def test_reverse_to_buy_skips_open_when_close_fails() -> None:
    broker = _tick_broker(_CloseFailsBroker())
    logger = InMemoryTradeLogger()
    manager = _manager_for(broker, logger, PositionPolicy.REJECT_OPPOSITE_OPEN)
    existing = [Position(instrument="USD_JPY", side=OrderSide.SELL, units=1000, avg_price=150.0)]
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY, instrument="USD_JPY",
        strategy_id="t", units=1000,
    )

    results = await manager.process_signal(signal, existing, 1_000_000.0)

    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.CLOSE
    assert len(logger.get_events(AuditEventType.REVERSE_OPEN_SKIPPED)) == 1


async def test_auto_reverse_split_logs_open_failed_on_open_error() -> None:
    broker = _OpenFailsBroker()
    _tick_broker(broker)
    # Establish a real SELL position so the CLOSE leg succeeds.
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1000,
    ))
    positions = await broker.get_positions()
    broker.fail_open = True

    logger = InMemoryTradeLogger()
    manager = _manager_for(broker, logger, PositionPolicy.AUTO_REVERSE_SPLIT)
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="t", units=1000)

    results = await manager.process_signal(signal, positions, 1_000_000.0)

    # CLOSE succeeded; OPEN was attempted but failed.
    assert len(results) == 2
    assert results[0].order.intent == OrderIntent.CLOSE
    assert results[0].trade_close is not None
    assert results[1].order.intent == OrderIntent.OPEN
    assert results[1].order.status != OrderStatus.FILLED
    failed = logger.get_events(AuditEventType.REVERSE_OPEN_FAILED)
    assert len(failed) == 1
    assert failed[0].reason_code == "open_execution_failed"
    # The position is now flat (the original SELL was closed, no new BUY opened).
    assert await broker.get_positions() == []


async def test_auto_reverse_split_logs_open_failed_on_risk_rejection() -> None:
    broker = _tick_broker(PaperBroker())
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1000,
    ))
    positions = await broker.get_positions()

    logger = InMemoryTradeLogger()
    manager = _manager_for(broker, logger, PositionPolicy.AUTO_REVERSE_SPLIT)
    # Oversized OPEN leg is rejected by RiskManager; CLOSE bypasses risk.
    signal = Signal(
        action=SignalAction.BUY, instrument="USD_JPY", strategy_id="t", units=200_000
    )

    results = await manager.process_signal(signal, positions, 1_000_000.0)

    assert len(results) == 1
    assert results[0].order.intent == OrderIntent.CLOSE
    assert results[0].trade_close is not None
    assert len(logger.get_events(AuditEventType.ORDER_REJECTED_BY_RISK)) == 1
    failed = logger.get_events(AuditEventType.REVERSE_OPEN_FAILED)
    assert len(failed) == 1
    assert failed[0].reason_code == "risk_rejected"
    assert await broker.get_positions() == []


async def test_auto_reverse_split_happy_path_no_skip_or_fail_events() -> None:
    broker = _tick_broker(PaperBroker())
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    ))
    positions = await broker.get_positions()

    logger = InMemoryTradeLogger()
    manager = _manager_for(broker, logger, PositionPolicy.AUTO_REVERSE_SPLIT)
    signal = Signal(action=SignalAction.BUY, instrument="USD_JPY", strategy_id="t", units=1000)

    results = await manager.process_signal(signal, positions, 1_000_000.0)

    assert len(results) == 2
    assert logger.get_events(AuditEventType.REVERSE_OPEN_SKIPPED) == []
    assert logger.get_events(AuditEventType.REVERSE_OPEN_FAILED) == []
    final = await broker.get_positions()
    assert len(final) == 1
    assert final[0].side == OrderSide.BUY
