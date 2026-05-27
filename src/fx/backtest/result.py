from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fx.audit.events import AuditEvent
from fx.broker.base import Order


@dataclass
class BacktestTrade:
    instrument: str
    side: str
    units: int
    entry_price: float
    exit_price: float
    pnl: float
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    reason: str = ""
    strategy_id: str = ""
    signal_id: str = ""


@dataclass
class BacktestResult:
    initial_balance: float
    final_balance: float
    total_pnl: float
    total_return: float
    max_drawdown: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    profit_factor: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
