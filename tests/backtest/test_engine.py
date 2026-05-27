from datetime import datetime, timedelta, timezone

import pytest

from fx.audit.events import AuditEventType
from fx.backtest.data import BacktestCandle
from fx.backtest.engine import BacktestEngine
from fx.risk.config import RiskConfig
from fx.signal.model import Signal, SignalAction
from fx.strategy.base import Strategy
from fx.strategy.ema_cross import EmaCrossStrategy


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _candles(prices: list[float], instrument: str = "USD_JPY") -> list[BacktestCandle]:
    base = _now() - timedelta(minutes=len(prices))
    return [
        BacktestCandle(
            timestamp=base + timedelta(minutes=i),
            instrument=instrument,
            open=p, high=p + 0.1, low=p - 0.1, close=p,
        )
        for i, p in enumerate(prices)
    ]


class AlwaysBuyStrategy(Strategy):
    @property
    def strategy_id(self) -> str:
        return "always_buy"

    def on_bar(self, prices: list[float], timestamp: float | None = None) -> Signal:
        if len(prices) < 2:
            return Signal(
                action=SignalAction.HOLD, instrument="USD_JPY",
                strategy_id=self.strategy_id, reason="warmup",
            )
        return Signal(
            action=SignalAction.BUY, instrument="USD_JPY",
            strategy_id=self.strategy_id, units=1000,
        )


class BuyThenCloseStrategy(Strategy):
    def __init__(self) -> None:
        self._bought = False

    @property
    def strategy_id(self) -> str:
        return "buy_then_close"

    def on_bar(self, prices: list[float], timestamp: float | None = None) -> Signal:
        if len(prices) < 2:
            return Signal(
                action=SignalAction.HOLD, instrument="USD_JPY",
                strategy_id=self.strategy_id,
            )
        if not self._bought:
            self._bought = True
            return Signal(
                action=SignalAction.BUY, instrument="USD_JPY",
                strategy_id=self.strategy_id, units=1000,
                stop_loss=148.0, take_profit=153.0,
            )
        return Signal(
            action=SignalAction.HOLD, instrument="USD_JPY",
            strategy_id=self.strategy_id,
        )


class BuyThenReverseStrategy(Strategy):
    def __init__(self) -> None:
        self._step = 0

    @property
    def strategy_id(self) -> str:
        return "buy_then_reverse"

    def on_bar(self, prices: list[float], timestamp: float | None = None) -> Signal:
        self._step += 1
        if self._step == 3:
            return Signal(
                action=SignalAction.BUY, instrument="USD_JPY",
                strategy_id=self.strategy_id, units=1000,
            )
        if self._step == 6:
            return Signal(
                action=SignalAction.REVERSE_TO_SELL, instrument="USD_JPY",
                strategy_id=self.strategy_id, units=1000,
            )
        return Signal(
            action=SignalAction.HOLD, instrument="USD_JPY",
            strategy_id=self.strategy_id,
        )


# --- basic tests ---


async def test_backtest_generates_orders() -> None:
    engine = BacktestEngine(AlwaysBuyStrategy(), initial_balance=1_000_000.0)
    candles = _candles([150.0, 150.5, 151.0, 150.8, 151.2])
    result = await engine.run(candles)
    assert result.initial_balance == 1_000_000.0
    assert len(result.equity_curve) == len(candles)
    assert len(result.audit_events) > 0


async def test_backtest_close_on_finish() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), close_on_finish=True)
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    assert result.trade_count >= 1


async def test_backtest_no_close_on_finish() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), close_on_finish=False)
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    close_trades = [t for t in result.trades if t.reason == "close_position"]
    assert len(close_trades) == 0


async def test_backtest_hold_only() -> None:
    engine = BacktestEngine(
        EmaCrossStrategy(fast_period=3, slow_period=5),
        initial_balance=1_000_000.0,
    )
    candles = _candles([150.0, 150.0, 150.0])
    result = await engine.run(candles)
    assert result.trade_count == 0
    assert result.final_balance == 1_000_000.0
    assert result.total_pnl == 0.0


async def test_backtest_audit_events() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy())
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    event_types = {e.event_type for e in result.audit_events}
    assert AuditEventType.ORDER_SENT_TO_BROKER in event_types
    assert AuditEventType.ORDER_FILLED in event_types


async def test_backtest_orders_preserved() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy())
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    assert len(result.orders) >= 1


# --- total_pnl integrity ---


async def test_total_pnl_matches_balance_change() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), initial_balance=1_000_000.0)
    candles = _candles([150.0, 150.5, 151.0, 151.5])
    result = await engine.run(candles)
    balance_pnl = result.final_balance - result.initial_balance
    assert result.total_pnl == pytest.approx(balance_pnl, abs=0.01)


async def test_reverse_pnl_matches_balance_change() -> None:
    engine = BacktestEngine(BuyThenReverseStrategy(), initial_balance=1_000_000.0)
    candles = _candles([150.0, 150.2, 150.4, 150.6, 150.8, 151.0, 150.5, 150.0])
    result = await engine.run(candles)
    balance_pnl = result.final_balance - result.initial_balance
    assert result.total_pnl == pytest.approx(balance_pnl, abs=0.01)


async def test_reverse_creates_close_trade() -> None:
    engine = BacktestEngine(BuyThenReverseStrategy(), initial_balance=1_000_000.0)
    candles = _candles([150.0, 150.2, 150.4, 150.6, 150.8, 151.0, 150.5, 150.0])
    result = await engine.run(candles)
    close_trades = [t for t in result.trades if t.reason == "close_position"]
    assert len(close_trades) >= 1


# --- entry_price ---


async def test_entry_price_is_not_zero() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), initial_balance=1_000_000.0)
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    for trade in result.trades:
        assert trade.entry_price != 0.0


# --- SL/TP audit ---


async def test_sl_trigger_creates_audit_event() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), close_on_finish=False)
    prices = [150.0, 150.5, 147.0]
    candles = _candles(prices)
    result = await engine.run(candles)
    sl_events = [
        e for e in result.audit_events
        if e.event_type == AuditEventType.POSITION_SL_TRIGGERED
    ]
    assert len(sl_events) >= 1
    closed_events = [
        e for e in result.audit_events
        if e.event_type == AuditEventType.TRADE_CLOSED
    ]
    assert len(closed_events) >= 1


async def test_sl_trade_has_entry_price() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), close_on_finish=False)
    prices = [150.0, 150.5, 147.0]
    candles = _candles(prices)
    result = await engine.run(candles)
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) >= 1
    for t in sl_trades:
        assert t.entry_price != 0.0


# --- EMA cross integration ---


async def test_ema_cross_uptrend() -> None:
    engine = BacktestEngine(
        EmaCrossStrategy(fast_period=3, slow_period=5, default_units=1000),
        initial_balance=1_000_000.0,
    )
    prices = [145.0 + i * 0.5 for i in range(20)]
    candles = _candles(prices)
    result = await engine.run(candles)
    assert len(result.equity_curve) == 20
    balance_pnl = result.final_balance - result.initial_balance
    assert result.total_pnl == pytest.approx(balance_pnl, abs=0.01)


async def test_ema_cross_volatile() -> None:
    engine = BacktestEngine(
        EmaCrossStrategy(fast_period=3, slow_period=5, default_units=1000),
        initial_balance=1_000_000.0,
    )
    prices = []
    for i in range(30):
        if i % 6 < 3:
            prices.append(150.0 + i * 0.3)
        else:
            prices.append(150.0 + (30 - i) * 0.3)
    candles = _candles(prices)
    result = await engine.run(candles)
    assert len(result.equity_curve) == 30
    balance_pnl = result.final_balance - result.initial_balance
    assert result.total_pnl == pytest.approx(balance_pnl, abs=0.01)


# --- risk management in backtest ---


async def test_backtest_max_daily_loss() -> None:
    config = RiskConfig(max_daily_loss_ratio=0.001)
    engine = BacktestEngine(
        AlwaysBuyStrategy(),
        initial_balance=1_000_000.0,
        risk_config=config,
    )
    prices = [150.0 + i * 0.1 for i in range(10)]
    candles = _candles(prices)
    result = await engine.run(candles)
    assert len(result.equity_curve) == 10
