from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    max_position_size: int = 100_000
    max_open_positions: int = 3
    max_daily_loss: float = 0.02
    duplicate_window_seconds: float = 5.0
