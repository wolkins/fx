from __future__ import annotations

from dataclasses import dataclass

from fx.broker.base import Order, TradeClose


@dataclass
class ExecutionResult:
    order: Order
    trade_close: TradeClose | None = None
