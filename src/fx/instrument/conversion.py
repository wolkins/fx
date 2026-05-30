from __future__ import annotations

from fx.broker.base import OrderSide
from fx.instrument.spec import InstrumentSpec


class CurrencyConversionNotSupportedError(Exception):
    """Raised when a PnL in quote currency would be applied to a balance held in a
    different account currency. Account currency conversion is not yet implemented.

    TODO: accept conversion_rates (quote -> account) so cross-currency instruments
    such as EUR_USD can settle into a JPY account.
    """


class InvalidTradeUnitsError(Exception):
    """Raised when an order's units violate the InstrumentSpec trade-unit constraints."""


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


def validate_trade_units(units: int, spec: InstrumentSpec) -> None:
    """Reject orders whose units violate the InstrumentSpec constraints.

    We prefer an explicit rejection over silently rounding (see normalize_units),
    so violations stay visible in the audit trail.

    TODO: wire this into RiskManager so notional/margin limits are enforced too.
    """
    if units < spec.min_trade_units:
        raise InvalidTradeUnitsError(
            f"{spec.name}: units {units} below min_trade_units {spec.min_trade_units}"
        )
    if spec.max_trade_units is not None and units > spec.max_trade_units:
        raise InvalidTradeUnitsError(
            f"{spec.name}: units {units} above max_trade_units {spec.max_trade_units}"
        )
    if spec.trade_units_precision == 0 and int(units) != units:
        raise InvalidTradeUnitsError(
            f"{spec.name}: units {units} must be a whole number "
            f"(trade_units_precision=0)"
        )


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
