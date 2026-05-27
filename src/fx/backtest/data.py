from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BacktestCandle:
    timestamp: datetime
    instrument: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
