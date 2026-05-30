from __future__ import annotations

from enum import Enum


class PositionPolicy(str, Enum):
    """How TradeManager handles a plain BUY/SELL OPEN against an opposite position.

    REVERSE_TO_BUY / REVERSE_TO_SELL signals always decompose into CLOSE + OPEN and
    are unaffected by this policy.
    """

    REJECT_OPPOSITE_OPEN = "reject_opposite_open"
    """Reject a plain BUY/SELL when an opposite position exists. The strategy must emit
    REVERSE_TO_BUY / REVERSE_TO_SELL to flip. Safest default for live/practice."""

    AUTO_REVERSE_SPLIT = "auto_reverse_split"
    """Automatically convert a plain BUY/SELL against an opposite position into
    CLOSE + OPEN, as if a REVERSE signal had been emitted."""

    ALLOW_NETTING = "allow_netting"
    """Allow the OPEN to net against the opposite position (legacy behaviour).
    Intended for paper/backtest only; not recommended for live/practice."""
