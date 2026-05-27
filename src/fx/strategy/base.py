from __future__ import annotations

from abc import ABC, abstractmethod

from fx.signal.model import Signal


class Strategy(ABC):
    @property
    @abstractmethod
    def strategy_id(self) -> str: ...

    @abstractmethod
    def on_bar(self, prices: list[float], timestamp: float | None = None) -> Signal: ...
