from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentSpec:
    name: str
    base_currency: str
    quote_currency: str
    pip_size: float
    display_precision: int
    trade_units_precision: int
    min_trade_units: int
    max_trade_units: int | None = None
    margin_rate: float | None = None
