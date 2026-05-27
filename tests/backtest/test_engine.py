from datetime import datetime, timedelta, timezone

import pytest

from fx.audit.events import AuditEventType
from fx.backtest.data import BacktestCandle
from fx.backtest.engine import BacktestEngine
from fx.risk.config import RiskConfig
from fx.signal.model import Signal, SignalAction
from fx.strategy.base import Strategy
from fx.strategy.ema_cross import EmaCrossStrategy


def _ts(day: int = 1, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2025, 1, day, hour, minute, tzinfo=timezone.utc)


def _candles(
    prices: list[float],
    instrument: str = "USD_JPY",
    start: datetime | None = None,
) -> list[BacktestCandle]:
    base = start or (_ts() - timedelta(minutes=len(prices)))
    return [
        BacktestCandle(
            timestamp=base + timedelta(minutes=i),
            instrument=instrument,
            open=p, high=p + 0.1, low=p - 0.1, close=p,
        )
        for i, p in enumerate(prices)
    ]


def _ohlc_candles(
    data: list[tuple[float, float, float, float]],
    instrument: str = "USD_JPY",
    start: datetime | None = None,
) -> list[BacktestCandle]:
    base = start or _ts()
    return [
        BacktestCandle(
            timestamp=base + timedelta(minutes=i),
            instrument=instrument,
            open=o, high=h, low=lo, close=c,
        )
        for i, (o, h, lo, c) in enumerate(data)
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


def _assert_pnl_integrity(result: object) -> None:
    from fx.backtest.result import BacktestResult
    assert isinstance(result, BacktestResult)
    balance_pnl = result.final_balance - result.initial_balance
    trades_pnl = sum(t.pnl for t in result.trades)
    assert result.total_pnl == pytest.approx(balance_pnl, abs=0.01)
    assert result.total_pnl == pytest.approx(trades_pnl, abs=0.01)
    assert balance_pnl == pytest.approx(trades_pnl, abs=0.01)


# --- basic tests ---


async def test_backtest_generates_orders() -> None:
    engine = BacktestEngine(AlwaysBuyStrategy(), initial_balance=1_000_000.0)
    result = await engine.run(_candles([150.0, 150.5, 151.0, 150.8, 151.2]))
    assert result.initial_balance == 1_000_000.0
    assert len(result.equity_curve) == 5
    assert len(result.audit_events) > 0


async def test_backtest_close_on_finish() -> None:
    result = await BacktestEngine(BuyThenCloseStrategy(), close_on_finish=True).run(
        _candles([150.0, 150.5, 151.0])
    )
    assert result.trade_count >= 1
    _assert_pnl_integrity(result)


async def test_backtest_no_close_on_finish() -> None:
    result = await BacktestEngine(BuyThenCloseStrategy(), close_on_finish=False).run(
        _candles([150.0, 150.5, 151.0])
    )
    close_trades = [t for t in result.trades if t.reason == "close_position"]
    assert len(close_trades) == 0


async def test_backtest_hold_only() -> None:
    result = await BacktestEngine(
        EmaCrossStrategy(fast_period=3, slow_period=5), initial_balance=1_000_000.0,
    ).run(_candles([150.0, 150.0, 150.0]))
    assert result.trade_count == 0
    assert result.final_balance == 1_000_000.0
    assert result.total_pnl == 0.0


async def test_backtest_audit_events() -> None:
    result = await BacktestEngine(BuyThenCloseStrategy()).run(_candles([150.0, 150.5, 151.0]))
    event_types = {e.event_type for e in result.audit_events}
    assert AuditEventType.ORDER_SENT_TO_BROKER in event_types
    assert AuditEventType.ORDER_FILLED in event_types


async def test_backtest_orders_preserved() -> None:
    result = await BacktestEngine(BuyThenCloseStrategy()).run(_candles([150.0, 150.5, 151.0]))
    assert len(result.orders) >= 1


# --- total_pnl / trades / balance integrity ---


async def test_total_pnl_matches_balance_change() -> None:
    result = await BacktestEngine(
        BuyThenCloseStrategy(), initial_balance=1_000_000.0
    ).run(_candles([150.0, 150.5, 151.0, 151.5]))
    _assert_pnl_integrity(result)


async def test_reverse_pnl_integrity() -> None:
    result = await BacktestEngine(
        BuyThenReverseStrategy(), initial_balance=1_000_000.0
    ).run(_candles([150.0, 150.2, 150.4, 150.6, 150.8, 151.0, 150.5, 150.0]))
    _assert_pnl_integrity(result)


async def test_reverse_creates_close_trade() -> None:
    result = await BacktestEngine(
        BuyThenReverseStrategy(), initial_balance=1_000_000.0
    ).run(_candles([150.0, 150.2, 150.4, 150.6, 150.8, 151.0, 150.5, 150.0]))
    close_trades = [t for t in result.trades if t.reason == "close_position"]
    assert len(close_trades) >= 1


# --- entry_price ---


async def test_entry_price_is_not_zero() -> None:
    result = await BacktestEngine(BuyThenCloseStrategy()).run(_candles([150.0, 150.5, 151.0]))
    for trade in result.trades:
        assert trade.entry_price != 0.0


# --- daily_pnl reset ---


async def test_daily_pnl_resets_on_new_day() -> None:
    config = RiskConfig(max_daily_loss_ratio=0.001)

    class BuyOncePerDay(Strategy):
        def __init__(self) -> None:
            self._count = 0

        @property
        def strategy_id(self) -> str:
            return "buy_once"

        def on_bar(self, prices: list[float], timestamp: float | None = None) -> Signal:
            self._count += 1
            if self._count in (2, 6):
                return Signal(
                    action=SignalAction.BUY, instrument="USD_JPY",
                    strategy_id=self.strategy_id, units=1000,
                )
            return Signal(
                action=SignalAction.HOLD, instrument="USD_JPY",
                strategy_id=self.strategy_id,
            )

    day1 = [
        BacktestCandle(timestamp=_ts(1, 0, i), instrument="USD_JPY",
                       open=150.0, high=150.1, low=149.9, close=150.0)
        for i in range(4)
    ]
    day2 = [
        BacktestCandle(timestamp=_ts(2, 0, i), instrument="USD_JPY",
                       open=150.0, high=150.1, low=149.9, close=150.0)
        for i in range(4)
    ]
    candles = day1 + day2
    engine = BacktestEngine(BuyOncePerDay(), initial_balance=1_000_000.0, risk_config=config)
    result = await engine.run(candles)

    submitted = [
        e for e in result.audit_events if e.event_type == AuditEventType.ORDER_SUBMITTED
    ]
    assert len(submitted) >= 2


# --- SL/TP close_only mode ---


async def test_sl_close_only_not_triggered_by_low() -> None:
    """close_only: SL not triggered even if low reaches SL, because close doesn't."""
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False, sl_tp_mode="close_only"
    ).run(_ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 150.3, 148.5, 150.1),
    ]))
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) == 0


async def test_sl_close_only_triggered_by_close() -> None:
    """close_only: SL triggered when close reaches SL."""
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False, sl_tp_mode="close_only"
    ).run(_ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 150.3, 147.0, 147.5),
    ]))
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) == 1


# --- SL/TP ohlc_conservative mode ---


async def test_ohlc_sl_triggered_by_low() -> None:
    """ohlc_conservative: SL triggered when low reaches SL."""
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False, sl_tp_mode="ohlc_conservative"
    ).run(_ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 150.3, 147.5, 149.0),
    ]))
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) == 1
    assert sl_trades[0].exit_price == 148.0
    _assert_pnl_integrity(result)


async def test_ohlc_tp_triggered_by_high() -> None:
    """ohlc_conservative: TP triggered when high reaches TP (BUY)."""
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False, sl_tp_mode="ohlc_conservative"
    ).run(_ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 153.5, 150.0, 152.0),
    ]))
    tp_trades = [t for t in result.trades if t.reason == "take_profit"]
    assert len(tp_trades) == 1
    assert tp_trades[0].exit_price == 153.0
    _assert_pnl_integrity(result)


async def test_ohlc_both_sl_tp_hit_sl_wins() -> None:
    """ohlc_conservative: SL wins when both SL and TP hit in same candle."""
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False, sl_tp_mode="ohlc_conservative"
    ).run(_ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 154.0, 147.0, 150.5),
    ]))
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    tp_trades = [t for t in result.trades if t.reason == "take_profit"]
    assert len(sl_trades) == 1
    assert len(tp_trades) == 0
    _assert_pnl_integrity(result)


async def test_ohlc_sell_sl_triggered() -> None:
    """ohlc_conservative: SELL position SL triggered by high."""

    class SellStrategy(Strategy):
        _bought = False

        @property
        def strategy_id(self) -> str:
            return "sell_once"

        def on_bar(self, prices: list[float], timestamp: float | None = None) -> Signal:
            if len(prices) < 2:
                return Signal(action=SignalAction.HOLD, instrument="USD_JPY", strategy_id=self.strategy_id)
            if not self._bought:
                self._bought = True
                return Signal(
                    action=SignalAction.SELL, instrument="USD_JPY",
                    strategy_id=self.strategy_id, units=1000,
                    stop_loss=151.5, take_profit=148.0,
                )
            return Signal(action=SignalAction.HOLD, instrument="USD_JPY", strategy_id=self.strategy_id)

    result = await BacktestEngine(
        SellStrategy(), close_on_finish=False, sl_tp_mode="ohlc_conservative"
    ).run(_ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 152.0, 149.5, 150.5),
    ]))
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) == 1
    _assert_pnl_integrity(result)


# --- SL/TP audit ---


async def test_sl_trigger_creates_audit_event() -> None:
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False
    ).run(_candles([150.0, 150.5, 147.0]))
    sl_events = [e for e in result.audit_events if e.event_type == AuditEventType.POSITION_SL_TRIGGERED]
    assert len(sl_events) >= 1
    closed_events = [e for e in result.audit_events if e.event_type == AuditEventType.TRADE_CLOSED]
    assert len(closed_events) >= 1


async def test_sl_trade_has_entry_price() -> None:
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False
    ).run(_candles([150.0, 150.5, 147.0]))
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) >= 1
    for t in sl_trades:
        assert t.entry_price != 0.0


# --- EMA cross integration ---


async def test_ema_cross_uptrend_integrity() -> None:
    result = await BacktestEngine(
        EmaCrossStrategy(fast_period=3, slow_period=5, default_units=1000),
    ).run(_candles([145.0 + i * 0.5 for i in range(20)]))
    assert len(result.equity_curve) == 20
    _assert_pnl_integrity(result)


async def test_ema_cross_volatile_integrity() -> None:
    prices = []
    for i in range(30):
        if i % 6 < 3:
            prices.append(150.0 + i * 0.3)
        else:
            prices.append(150.0 + (30 - i) * 0.3)
    result = await BacktestEngine(
        EmaCrossStrategy(fast_period=3, slow_period=5, default_units=1000),
    ).run(_candles(prices))
    assert len(result.equity_curve) == 30
    _assert_pnl_integrity(result)


# --- risk management ---


async def test_backtest_max_daily_loss() -> None:
    result = await BacktestEngine(
        AlwaysBuyStrategy(), risk_config=RiskConfig(max_daily_loss_ratio=0.001),
    ).run(_candles([150.0 + i * 0.1 for i in range(10)]))
    assert len(result.equity_curve) == 10


# --- sl_tp_mode validation ---


def test_invalid_sl_tp_mode() -> None:
    with pytest.raises(ValueError, match="Invalid sl_tp_mode"):
        BacktestEngine(AlwaysBuyStrategy(), sl_tp_mode="bad_mode")


# --- closed_at timestamp ---


async def test_close_only_sl_closed_at_is_candle_time() -> None:
    start = _ts(5, 10, 0)
    candles = _ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 150.3, 146.0, 147.0),
    ], start=start)
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False, sl_tp_mode="close_only"
    ).run(candles)
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) >= 1
    assert sl_trades[0].closed_at == start + timedelta(minutes=2)


async def test_ohlc_sl_closed_at_is_candle_time() -> None:
    start = _ts(5, 10, 0)
    candles = _ohlc_candles([
        (150.0, 150.5, 149.5, 150.0),
        (150.0, 150.5, 149.5, 150.2),
        (150.2, 150.3, 147.5, 149.0),
    ], start=start)
    result = await BacktestEngine(
        BuyThenCloseStrategy(), close_on_finish=False, sl_tp_mode="ohlc_conservative"
    ).run(candles)
    sl_trades = [t for t in result.trades if t.reason == "stop_loss"]
    assert len(sl_trades) >= 1
    assert sl_trades[0].closed_at == start + timedelta(minutes=2)


# --- MARKET orders in BacktestResult.orders ---


async def test_market_orders_in_backtest_result() -> None:
    result = await BacktestEngine(BuyThenCloseStrategy()).run(
        _candles([150.0, 150.5, 151.0])
    )
    filled_orders = [o for o in result.orders if o.filled_price is not None]
    assert len(filled_orders) >= 1
