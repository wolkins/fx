from __future__ import annotations

from fx.backtest.result import BacktestTrade


def calculate_total_pnl(trades: list[BacktestTrade]) -> float:
    return sum(t.pnl for t in trades)


def calculate_total_return(initial_balance: float, final_balance: float) -> float:
    if initial_balance <= 0:
        return 0.0
    return (final_balance - initial_balance) / initial_balance


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def calculate_win_rate(trades: list[BacktestTrade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def calculate_profit_factor(trades: list[BacktestTrade]) -> float:
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss
