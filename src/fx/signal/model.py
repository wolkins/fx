from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    CLOSE_BUY = "close_buy"
    CLOSE_SELL = "close_sell"
    REVERSE_TO_BUY = "reverse_to_buy"
    REVERSE_TO_SELL = "reverse_to_sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Signal:
    action: SignalAction
    instrument: str
    strategy_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    confidence: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    units: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
