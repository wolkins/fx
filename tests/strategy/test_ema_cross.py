from fx.signal.model import SignalAction
from fx.strategy.ema_cross import EmaCrossStrategy


def test_hold_on_insufficient_data() -> None:
    strat = EmaCrossStrategy(fast_period=3, slow_period=5)
    signal = strat.on_bar([1.0, 2.0, 3.0])
    assert signal.action == SignalAction.HOLD
    assert signal.reason == "insufficient_data"


def test_hold_on_first_bar() -> None:
    strat = EmaCrossStrategy(fast_period=3, slow_period=5)
    prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    signal = strat.on_bar(prices)
    assert signal.action == SignalAction.HOLD
    assert signal.reason == "initializing"


def test_buy_signal_on_golden_cross() -> None:
    strat = EmaCrossStrategy(fast_period=3, slow_period=10)
    downtrend = [100.0 - i for i in range(15)]
    strat.on_bar(downtrend)

    uptrend = downtrend + [90.0 + i * 2 for i in range(10)]
    signal = strat.on_bar(uptrend)
    assert signal.action in (SignalAction.REVERSE_TO_BUY, SignalAction.HOLD)


def test_sell_signal_on_death_cross() -> None:
    strat = EmaCrossStrategy(fast_period=3, slow_period=10)
    uptrend = [80.0 + i for i in range(15)]
    strat.on_bar(uptrend)

    downtrend = uptrend + [94.0 - i * 2 for i in range(10)]
    signal = strat.on_bar(downtrend)
    assert signal.action in (SignalAction.REVERSE_TO_SELL, SignalAction.HOLD)


def test_strategy_id() -> None:
    strat = EmaCrossStrategy(fast_period=12, slow_period=26)
    assert strat.strategy_id == "ema_cross_12_26"


def test_signal_has_units() -> None:
    strat = EmaCrossStrategy(fast_period=3, slow_period=5, default_units=5000)
    prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    strat.on_bar(prices)
    prices2 = prices + [7.0, 8.0, 9.0]
    signal = strat.on_bar(prices2)
    assert signal.units == 5000


def test_signal_has_id() -> None:
    strat = EmaCrossStrategy(fast_period=3, slow_period=5)
    prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    signal = strat.on_bar(prices)
    assert signal.id != ""


def test_reason_on_crossover() -> None:
    strat = EmaCrossStrategy(fast_period=3, slow_period=5)
    prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    strat.on_bar(prices)
    prices2 = prices + [7.0, 8.0, 9.0]
    signal = strat.on_bar(prices2)
    assert signal.reason in ("golden_cross", "death_cross", "no_crossover")
