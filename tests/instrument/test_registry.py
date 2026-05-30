import pytest

from fx.instrument.registry import InstrumentRegistry, UnknownInstrumentError
from fx.instrument.spec import InstrumentSpec


def test_default_has_usd_jpy() -> None:
    registry = InstrumentRegistry.default()
    spec = registry.get("USD_JPY")
    assert spec.base_currency == "USD"
    assert spec.quote_currency == "JPY"
    assert spec.pip_size == 0.01
    assert spec.display_precision == 3


def test_default_has_eur_usd() -> None:
    registry = InstrumentRegistry.default()
    spec = registry.get("EUR_USD")
    assert spec.base_currency == "EUR"
    assert spec.quote_currency == "USD"
    assert spec.pip_size == 0.0001
    assert spec.display_precision == 5


def test_default_has_all_majors() -> None:
    registry = InstrumentRegistry.default()
    for name in ("USD_JPY", "EUR_USD", "GBP_USD", "EUR_JPY", "GBP_JPY", "AUD_JPY"):
        assert registry.has(name)


def test_unknown_instrument_raises() -> None:
    registry = InstrumentRegistry.default()
    with pytest.raises(UnknownInstrumentError):
        registry.get("UNKNOWN_PAIR")


def test_register_custom_spec() -> None:
    registry = InstrumentRegistry()
    spec = InstrumentSpec(
        name="XAU_USD", base_currency="XAU", quote_currency="USD",
        pip_size=0.01, display_precision=2, trade_units_precision=0,
        min_trade_units=1,
    )
    registry.register(spec)
    assert registry.has("XAU_USD")
    assert registry.get("XAU_USD") is spec


def test_empty_registry_no_defaults() -> None:
    registry = InstrumentRegistry()
    assert not registry.has("USD_JPY")
    assert registry.names() == []
