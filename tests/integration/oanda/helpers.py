"""Helpers for OANDA practice integration tests.

Safety rules enforced here:
- practice environment only; anything that looks like live makes the run fail
- credentials are read from the environment and never logged
- order-placing tests stay disabled unless explicitly allowed
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from fx.broker.base import BrokerAdapter, BrokerEnvironment
from fx.broker.oanda import OandaAdapter
from fx.broker.safety import SafetyGuard

_MAX_PRACTICE_UNITS = 10
_LIVE_HINTS = frozenset({"live", "fxtrade", "trade", "real", "production", "prod"})


@dataclass(frozen=True)
class OandaPracticeSettings:
    """Resolved practice configuration. Never include this in log output verbatim:
    account_id and api_token are secrets."""

    account_id: str
    api_token: str
    instrument: str
    units: int
    allow_orders: bool


def load_practice_settings() -> OandaPracticeSettings:
    """Read practice settings from the environment.

    - skips (not fails) when credentials are absent, so the suite is a no-op locally
    - fails when the environment looks like live, or units are unsafe
    """
    env = os.getenv("OANDA_ENV", "practice").strip().lower()
    if env in _LIVE_HINTS:
        pytest.fail(
            f"OANDA_ENV={env!r} indicates a live environment. "
            "These tests only run against practice."
        )
    if env != "practice":
        pytest.skip(f"OANDA_ENV must be 'practice' (got {env!r}).")

    account_id = os.getenv("OANDA_ACCOUNT_ID", "").strip()
    api_token = os.getenv("OANDA_API_TOKEN", "").strip()
    if not account_id or not api_token:
        pytest.skip(
            "OANDA_ACCOUNT_ID and OANDA_API_TOKEN are required for OANDA practice tests."
        )

    instrument = os.getenv("OANDA_PRACTICE_INSTRUMENT", "USD_JPY").strip() or "USD_JPY"

    units_raw = os.getenv("OANDA_PRACTICE_UNITS", "1").strip() or "1"
    try:
        units = int(units_raw)
    except ValueError:
        pytest.fail(f"OANDA_PRACTICE_UNITS must be an integer (got {units_raw!r}).")
    if units < 1:
        pytest.fail(f"OANDA_PRACTICE_UNITS must be >= 1 (got {units}).")
    if units > _MAX_PRACTICE_UNITS:
        pytest.fail(
            f"OANDA_PRACTICE_UNITS must be <= {_MAX_PRACTICE_UNITS} for safety (got {units})."
        )

    allow_orders = os.getenv("OANDA_PRACTICE_ALLOW_ORDERS", "").strip().lower() == "true"

    return OandaPracticeSettings(
        account_id=account_id,
        api_token=api_token,
        instrument=instrument,
        units=units,
        allow_orders=allow_orders,
    )


def make_oanda_adapter(settings: OandaPracticeSettings) -> OandaAdapter:
    """Construct a practice-only OandaAdapter. The environment is hard-coded to
    PRACTICE regardless of any other input."""
    return OandaAdapter(
        account_id=settings.account_id,
        api_token=settings.api_token,
        environment=BrokerEnvironment.PRACTICE,
    )


def make_safety_guard(
    adapter: OandaAdapter, *, protective: bool = True
) -> SafetyGuard:
    """Wrap the adapter in a SafetyGuard with live trading disabled.

    protective=True (default) enforces live-grade OPEN safety on practice too:
    stop_loss, take_profit, and client_order_id are required for OPEN orders.
    Use protective=False only for tests that intentionally let an order reach OANDA
    (e.g. to observe an OANDA-side reject payload).
    """
    return SafetyGuard(
        adapter,
        enable_live_trading=False,
        require_protective_orders_for_open=protective,
        require_client_order_id_for_open=protective,
    )


async def assert_instrument_flat(broker: BrokerAdapter, instrument: str) -> None:
    """Refuse to run an order smoke test unless the target instrument is flat.

    close_position() operates per instrument+side, so an order smoke test that runs
    against an account already holding a position for this instrument would close that
    pre-existing position in its cleanup step. Fail loudly instead of risking that.

    Does not log token/account_id (only the instrument name appears in the message).
    """
    positions = await broker.get_positions()
    existing = [p for p in positions if p.instrument == instrument]
    if existing:
        pytest.fail(
            f"Refusing to run OANDA order smoke: existing position(s) found for "
            f"{instrument}. Use a dedicated empty practice account, or manually close "
            f"positions for {instrument} before running."
        )
