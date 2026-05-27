from __future__ import annotations

from fx.signal.model import Signal, SignalAction
from fx.strategy.base import Strategy
from fx.strategy.indicators import ema


class EmaCrossStrategy(Strategy):
    def __init__(
        self,
        instrument: str = "USD_JPY",
        fast_period: int = 12,
        slow_period: int = 26,
        default_units: int = 1000,
    ) -> None:
        self._instrument = instrument
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._default_units = default_units
        self._prev_fast_above: bool | None = None

    @property
    def strategy_id(self) -> str:
        return f"ema_cross_{self._fast_period}_{self._slow_period}"

    def on_bar(self, prices: list[float], timestamp: float | None = None) -> Signal:
        if len(prices) < self._slow_period + 1:
            return Signal(
                action=SignalAction.HOLD,
                instrument=self._instrument,
                strategy_id=self.strategy_id,
                metadata={"reason": "insufficient_data"},
            )

        fast_ema = ema(prices, self._fast_period)
        slow_ema = ema(prices, self._slow_period)

        fast_now = fast_ema[-1]
        slow_now = slow_ema[-1]
        fast_above = fast_now > slow_now

        if self._prev_fast_above is None:
            self._prev_fast_above = fast_above
            return Signal(
                action=SignalAction.HOLD,
                instrument=self._instrument,
                strategy_id=self.strategy_id,
                metadata={"reason": "initializing", "fast_ema": fast_now, "slow_ema": slow_now},
            )

        action = SignalAction.HOLD
        if fast_above and not self._prev_fast_above:
            action = SignalAction.REVERSE_TO_BUY
        elif not fast_above and self._prev_fast_above:
            action = SignalAction.REVERSE_TO_SELL

        self._prev_fast_above = fast_above

        return Signal(
            action=action,
            instrument=self._instrument,
            strategy_id=self.strategy_id,
            units=self._default_units,
            metadata={"fast_ema": fast_now, "slow_ema": slow_now},
        )
