from __future__ import annotations

from fx.broker.base import OrderSide
from fx.instrument.spec import InstrumentSpec


def round_price(price: float, spec: InstrumentSpec) -> float:
    return round(price, spec.display_precision)


def pips_to_price(pips: float, spec: InstrumentSpec) -> float:
    return pips * spec.pip_size


def price_to_pips(price_diff: float, spec: InstrumentSpec) -> float:
    if spec.pip_size <= 0:
        return 0.0
    return price_diff / spec.pip_size


def normalize_units(units: int, spec: InstrumentSpec) -> int:
    if units < spec.min_trade_units:
        return 0
    if spec.max_trade_units is not None and units > spec.max_trade_units:
        return spec.max_trade_units
    return units


def calculate_pnl_quote_currency(
    side: OrderSide,
    entry_price: float,
    exit_price: float,
    units: int,
    spec: InstrumentSpec,
) -> float:
    """PnL in quote currency. Account currency conversion is TODO."""
    _ = spec
    if side == OrderSide.BUY:
        return (exit_price - entry_price) * units
    return (entry_price - exit_price) * units
