"""Unit tests for OandaAdapter pure helpers (no network)."""

from __future__ import annotations

from datetime import datetime, timezone

from fx.broker.base import OrderSide
from fx.broker.oanda import OandaAdapter


def test_parse_close_response_long_fill() -> None:
    data = {
        "longOrderFillTransaction": {
            "units": "-1000",
            "price": "150.123",
            "pl": "42.5",
            "time": "2025-01-02T03:04:05.000000000Z",
        },
        "lastTransactionID": "99",
    }
    tc = OandaAdapter._parse_close_response("USD_JPY", OrderSide.BUY, data)
    assert tc.instrument == "USD_JPY"
    assert tc.side == OrderSide.BUY
    assert tc.units == 1000
    assert tc.close_price == 150.123
    assert tc.pnl == 42.5
    assert tc.closed_at == datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert tc.broker_data == data


def test_parse_close_response_short_fill() -> None:
    data = {
        "shortOrderFillTransaction": {
            "units": "500",
            "price": "1.08234",
            "pl": "-3.0",
            "time": "2025-01-02T03:04:05Z",
        },
    }
    tc = OandaAdapter._parse_close_response("EUR_USD", OrderSide.SELL, data)
    assert tc.side == OrderSide.SELL
    assert tc.units == 500
    assert tc.close_price == 1.08234
    assert tc.pnl == -3.0


def test_parse_close_response_both_sides_defaults_to_long() -> None:
    data = {
        "longOrderFillTransaction": {"units": "-100", "price": "150.0", "pl": "1.0"},
        "shortOrderFillTransaction": {"units": "100", "price": "150.0", "pl": "2.0"},
    }
    tc = OandaAdapter._parse_close_response("USD_JPY", None, data)
    assert tc.side == OrderSide.BUY
    assert tc.units == 100


def test_parse_close_response_missing_fill_falls_back() -> None:
    data = {"lastTransactionID": "5"}
    tc = OandaAdapter._parse_close_response("USD_JPY", OrderSide.BUY, data)
    assert tc.units == 0
    assert tc.close_price == 0.0
    assert tc.pnl == 0.0
    assert tc.reason == "close_position"
    assert tc.broker_data == data


def test_parse_close_response_malformed_numbers_safe() -> None:
    data = {
        "longOrderFillTransaction": {"units": "x", "price": "y", "pl": "z", "time": "bad"},
    }
    tc = OandaAdapter._parse_close_response("USD_JPY", OrderSide.BUY, data)
    assert tc.units == 0
    assert tc.close_price == 0.0
    assert tc.pnl == 0.0
