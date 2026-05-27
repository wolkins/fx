from fx.strategy.indicators import atr, ema, rsi


def test_ema_basic() -> None:
    prices = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ema(prices, 3)
    assert len(result) == 5
    assert result[0] == 1.0
    assert result[-1] > result[0]


def test_ema_single_price() -> None:
    result = ema([100.0], 5)
    assert result == [100.0]


def test_ema_empty() -> None:
    assert ema([], 3) == []
    assert ema([1.0], 0) == []


def test_ema_period_1() -> None:
    prices = [1.0, 2.0, 3.0]
    result = ema(prices, 1)
    assert result == prices


def test_rsi_basic() -> None:
    prices = list(range(1, 20))
    result = rsi(prices, 14)
    assert len(result) > 0
    assert result[-1] == 100.0


def test_rsi_all_down() -> None:
    prices = list(range(20, 0, -1))
    result = rsi(prices, 14)
    assert result[-1] == 0.0


def test_rsi_insufficient_data() -> None:
    assert rsi([1.0], 14) == []
    assert rsi(list(range(5)), 14) == []


def test_atr_basic() -> None:
    highs = [10.0, 11.0, 12.0, 11.5, 12.5, 13.0, 12.0, 11.0, 12.0, 13.0, 14.0, 13.5, 14.5, 15.0, 14.0]
    lows = [9.0, 10.0, 11.0, 10.5, 11.5, 12.0, 11.0, 10.0, 11.0, 12.0, 13.0, 12.5, 13.5, 14.0, 13.0]
    closes = [9.5, 10.5, 11.5, 11.0, 12.0, 12.5, 11.5, 10.5, 11.5, 12.5, 13.5, 13.0, 14.0, 14.5, 13.5]
    result = atr(highs, lows, closes, 14)
    assert len(result) == 15
    assert all(v >= 0 for v in result)


def test_atr_insufficient_data() -> None:
    assert atr([10.0], [9.0], [9.5], 14) == []
    assert atr([], [], [], 14) == []
