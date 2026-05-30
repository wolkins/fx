from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from fx.broker.oanda import OandaAdapter
from fx.broker.safety import SafetyGuard
from tests.integration.oanda.helpers import (
    OandaPracticeSettings,
    load_practice_settings,
    make_oanda_adapter,
    make_safety_guard,
)


@pytest.fixture(scope="session")
def practice_settings() -> OandaPracticeSettings:
    return load_practice_settings()


@pytest_asyncio.fixture
async def oanda_adapter(
    practice_settings: OandaPracticeSettings,
) -> AsyncIterator[OandaAdapter]:
    adapter = make_oanda_adapter(practice_settings)
    await adapter.connect()
    try:
        yield adapter
    finally:
        await adapter.disconnect()


@pytest.fixture
def oanda_guard(oanda_adapter: OandaAdapter) -> SafetyGuard:
    # Wraps the same connected adapter; all calls delegate to it.
    # Protective mode ON: practice OPEN orders need SL/TP/client_order_id.
    return make_safety_guard(oanda_adapter, protective=True)


@pytest.fixture
def oanda_guard_without_protective_mode_for_reject_test(
    oanda_adapter: OandaAdapter,
) -> SafetyGuard:
    # Protective mode OFF so an order can intentionally reach OANDA and trigger an
    # OANDA-side reject (used only by the actual-reject payload test).
    return make_safety_guard(oanda_adapter, protective=False)


@pytest.fixture
def require_order_permission(practice_settings: OandaPracticeSettings) -> None:
    if not practice_settings.allow_orders:
        pytest.skip("Set OANDA_PRACTICE_ALLOW_ORDERS=true to run order-placing tests.")
