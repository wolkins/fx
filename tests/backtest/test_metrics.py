import pytest

from fx.backtest.metrics import (
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_total_pnl,
    calculate_total_return,
    calculate_win_rate,
)
from fx.backtest.result import BacktestTrade


def _trade(pnl: float) -> BacktestTrade:
    return BacktestTrade(
        instrument="USD_JPY", side="buy", units=1000,
        entry_price=150.0, exit_price=150.0 + pnl / 1000, pnl=pnl,
    )


def test_total_pnl_mixed() -> None:
    trades = [_trade(100), _trade(-50), _trade(200)]
    assert calculate_total_pnl(trades) == pytest.approx(250.0)


def test_total_pnl_empty() -> None:
    assert calculate_total_pnl([]) == 0.0


def test_total_return() -> None:
    assert calculate_total_return(1_000_000.0, 1_050_000.0) == pytest.approx(0.05)


def test_total_return_zero_balance() -> None:
    assert calculate_total_return(0.0, 100.0) == 0.0


def test_max_drawdown_basic() -> None:
    curve = [100.0, 110.0, 105.0, 90.0, 95.0, 120.0]
    dd = calculate_max_drawdown(curve)
    assert dd == pytest.approx((110.0 - 90.0) / 110.0)


def test_max_drawdown_no_drawdown() -> None:
    curve = [100.0, 110.0, 120.0, 130.0]
    assert calculate_max_drawdown(curve) == 0.0


def test_max_drawdown_single_point() -> None:
    assert calculate_max_drawdown([100.0]) == 0.0


def test_max_drawdown_empty() -> None:
    assert calculate_max_drawdown([]) == 0.0


def test_win_rate_mixed() -> None:
    trades = [_trade(100), _trade(-50), _trade(200)]
    assert calculate_win_rate(trades) == pytest.approx(2 / 3)


def test_win_rate_all_win() -> None:
    trades = [_trade(100), _trade(200)]
    assert calculate_win_rate(trades) == 1.0


def test_win_rate_all_loss() -> None:
    trades = [_trade(-100), _trade(-200)]
    assert calculate_win_rate(trades) == 0.0


def test_win_rate_empty() -> None:
    assert calculate_win_rate([]) == 0.0


def test_profit_factor_mixed() -> None:
    trades = [_trade(300), _trade(-100)]
    assert calculate_profit_factor(trades) == pytest.approx(3.0)


def test_profit_factor_no_losses() -> None:
    trades = [_trade(100), _trade(200)]
    assert calculate_profit_factor(trades) == float("inf")


def test_profit_factor_no_wins() -> None:
    trades = [_trade(-100), _trade(-200)]
    assert calculate_profit_factor(trades) == 0.0


def test_profit_factor_empty() -> None:
    assert calculate_profit_factor([]) == 0.0


def test_profit_factor_zero_trades() -> None:
    trades = [_trade(0)]
    assert calculate_profit_factor(trades) == 0.0
