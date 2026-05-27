from __future__ import annotations


def ema(prices: list[float], period: int) -> list[float]:
    if not prices or period <= 0:
        return []
    result: list[float] = [prices[0]]
    k = 2.0 / (period + 1)
    for i in range(1, len(prices)):
        result.append(prices[i] * k + result[-1] * (1 - k))
    return result


def rsi(prices: list[float], period: int = 14) -> list[float]:
    if len(prices) < 2 or period <= 0:
        return []
    result: list[float] = []
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    if len(gains) < period:
        return []

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for _ in range(period):
        result.append(0.0)

    if avg_loss == 0:
        result.append(100.0)
    else:
        result.append(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            result.append(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    return result


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    if len(highs) < 2 or len(highs) != len(lows) or len(highs) != len(closes) or period <= 0:
        return []
    true_ranges: list[float] = [highs[0] - lows[0]]
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return []

    result: list[float] = []
    for _ in range(period - 1):
        result.append(0.0)
    result.append(sum(true_ranges[:period]) / period)

    for i in range(period, len(true_ranges)):
        result.append((result[-1] * (period - 1) + true_ranges[i]) / period)
    return result
