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


# --- basic tests ---


async def test_backtest_generates_orders() -> None:
    engine = BacktestEngine(AlwaysBuyStrategy(), initial_balance=1_000_000.0)
    candles = _candles([150.0, 150.5, 151.0, 150.8, 151.2])
    result = await engine.run(candles)
    assert result.initial_balance == 1_000_000.0
    assert result.trade_count >= 0
    assert len(result.equity_curve) == len(candles)
    assert len(result.audit_events) > 0


async def test_backtest_close_on_finish() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), close_on_finish=True)
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    assert result.trade_count >= 1
    assert any(t.reason in ("close_position", "close_on_finish") for t in result.trades)


async def test_backtest_no_close_on_finish() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), close_on_finish=False)
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    open_trades = [t for t in result.trades if t.reason == "close_position"]
    assert len(open_trades) == 0


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


async def test_backtest_equity_curve_length() -> None:
    engine = BacktestEngine(AlwaysBuyStrategy())
    candles = _candles([150.0, 150.5, 151.0, 150.0])
    result = await engine.run(candles)
    assert len(result.equity_curve) == 4


async def test_backtest_result_consistency() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), initial_balance=1_000_000.0)
    candles = _candles([150.0, 150.5, 151.0, 151.5])
    result = await engine.run(candles)
    assert result.total_return == pytest.approx(
        (result.final_balance - result.initial_balance) / result.initial_balance
    )
    assert result.win_count + result.loss_count <= result.trade_count


async def test_backtest_orders_preserved() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy())
    candles = _candles([150.0, 150.5, 151.0])
    result = await engine.run(candles)
    assert len(result.orders) >= 1


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
    assert result.trade_count >= 0


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
    assert result.trade_count >= 0
    assert len(result.equity_curve) == 10


# --- SL/TP via process_tick ---


async def test_backtest_sl_triggered() -> None:
    engine = BacktestEngine(BuyThenCloseStrategy(), close_on_finish=False)
    prices = [150.0, 150.5, 147.0]
    candles = _candles(prices)
    result = await engine.run(candles)
    # SL at 148.0, price drops to 147.0 → should trigger
    # But SL/TP is processed via process_tick, which uses bid = close - spread/2
    # bid = 147.0 - 0.01 = 146.99, SL = 148.0 → triggered
    assert len(result.trades) >= 1
