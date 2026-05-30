from __future__ import annotations

from fx.instrument.spec import InstrumentSpec


class UnknownInstrumentError(KeyError):
    pass


class InstrumentRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, InstrumentSpec] = {}

    def register(self, spec: InstrumentSpec) -> None:
        self._specs[spec.name] = spec

    def get(self, name: str) -> InstrumentSpec:
        if name not in self._specs:
            raise UnknownInstrumentError(f"Unknown instrument: {name}")
        return self._specs[name]

    def has(self, name: str) -> bool:
        return name in self._specs

    def names(self) -> list[str]:
        return list(self._specs.keys())

    @classmethod
    def default(cls) -> InstrumentRegistry:
        registry = cls()
        for spec in _DEFAULT_SPECS:
            registry.register(spec)
        return registry


_JPY_PIP = 0.01
_NON_JPY_PIP = 0.0001

_DEFAULT_SPECS: list[InstrumentSpec] = [
    InstrumentSpec(
        name="USD_JPY", base_currency="USD", quote_currency="JPY",
        pip_size=_JPY_PIP, display_precision=3,
        trade_units_precision=0, min_trade_units=1,
    ),
    InstrumentSpec(
        name="EUR_JPY", base_currency="EUR", quote_currency="JPY",
        pip_size=_JPY_PIP, display_precision=3,
        trade_units_precision=0, min_trade_units=1,
    ),
    InstrumentSpec(
        name="GBP_JPY", base_currency="GBP", quote_currency="JPY",
        pip_size=_JPY_PIP, display_precision=3,
        trade_units_precision=0, min_trade_units=1,
    ),
    InstrumentSpec(
        name="AUD_JPY", base_currency="AUD", quote_currency="JPY",
        pip_size=_JPY_PIP, display_precision=3,
        trade_units_precision=0, min_trade_units=1,
    ),
    InstrumentSpec(
        name="EUR_USD", base_currency="EUR", quote_currency="USD",
        pip_size=_NON_JPY_PIP, display_precision=5,
        trade_units_precision=0, min_trade_units=1,
    ),
    InstrumentSpec(
        name="GBP_USD", base_currency="GBP", quote_currency="USD",
        pip_size=_NON_JPY_PIP, display_precision=5,
        trade_units_precision=0, min_trade_units=1,
    ),
]
