from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    max_position_size: int = 100_000
    max_open_positions: int = 3
    max_daily_loss_ratio: float = 0.02
    max_daily_loss_amount: float | None = None
    duplicate_window_seconds: float = 5.0
