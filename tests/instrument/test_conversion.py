import pytest

from fx.broker.base import OrderSide
from fx.instrument.conversion import (
    calculate_pnl_quote_currency,
    normalize_units,
    pips_to_price,
    price_to_pips,
    round_price,
)
from fx.instrument.registry import InstrumentRegistry


@pytest.fixture
def registry() -> InstrumentRegistry:
    return InstrumentRegistry.default()


def test_round_price_usd_jpy(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    assert round_price(150.0234567, spec) == 150.023


def test_round_price_eur_usd(registry: InstrumentRegistry) -> None:
    spec = registry.get("EUR_USD")
    assert round_price(1.08234567, spec) == 1.08235


def test_pips_to_price_usd_jpy(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    assert pips_to_price(2.0, spec) == pytest.approx(0.02)


def test_pips_to_price_eur_usd(registry: InstrumentRegistry) -> None:
    spec = registry.get("EUR_USD")
    assert pips_to_price(2.0, spec) == pytest.approx(0.0002)


def test_price_to_pips_usd_jpy(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    assert price_to_pips(0.05, spec) == pytest.approx(5.0)


def test_price_to_pips_eur_usd(registry: InstrumentRegistry) -> None:
    spec = registry.get("EUR_USD")
    assert price_to_pips(0.0005, spec) == pytest.approx(5.0)


def test_normalize_units_within_range(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    assert normalize_units(1000, spec) == 1000


def test_normalize_units_below_min(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    assert normalize_units(0, spec) == 0


def test_normalize_units_above_max() -> None:
    from fx.instrument.spec import InstrumentSpec
    spec = InstrumentSpec(
        name="TEST", base_currency="A", quote_currency="B",
        pip_size=0.01, display_precision=3, trade_units_precision=0,
        min_trade_units=1, max_trade_units=1000,
    )
    assert normalize_units(5000, spec) == 1000


def test_pnl_buy(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    pnl = calculate_pnl_quote_currency(OrderSide.BUY, 150.0, 151.0, 1000, spec)
    assert pnl == pytest.approx(1000.0)


def test_pnl_sell(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    pnl = calculate_pnl_quote_currency(OrderSide.SELL, 150.0, 149.5, 1000, spec)
    assert pnl == pytest.approx(500.0)


def test_pnl_buy_loss(registry: InstrumentRegistry) -> None:
    spec = registry.get("USD_JPY")
    pnl = calculate_pnl_quote_currency(OrderSide.BUY, 150.0, 149.5, 1000, spec)
    assert pnl == pytest.approx(-500.0)
