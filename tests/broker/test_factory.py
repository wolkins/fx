import pytest

from fx.broker.base import BrokerEnvironment
from fx.broker.factory import create_broker
from fx.broker.mt5_stub import MT5Adapter
from fx.broker.oanda import OandaAdapter
from fx.broker.paper import PaperBroker
from fx.broker.safety import SafetyGuard


def test_create_paper_broker() -> None:
    guard = create_broker("paper")
    assert isinstance(guard, SafetyGuard)
    assert isinstance(guard.inner, PaperBroker)
    assert guard.is_live_allowed is True


def test_create_oanda_broker() -> None:
    guard = create_broker(
        "oanda",
        oanda_account_id="test-id",
        oanda_api_token="test-token",
        environment=BrokerEnvironment.PRACTICE,
    )
    assert isinstance(guard.inner, OandaAdapter)
    assert guard.is_live_allowed is True


def test_create_oanda_live_default_disabled() -> None:
    guard = create_broker(
        "oanda",
        oanda_account_id="test-id",
        oanda_api_token="test-token",
        environment=BrokerEnvironment.LIVE,
    )
    assert guard.is_live_allowed is False


def test_create_mt5_stub() -> None:
    guard = create_broker("mt5")
    assert isinstance(guard.inner, MT5Adapter)


def test_create_oanda_missing_credentials() -> None:
    with pytest.raises(ValueError, match="OANDA_ACCOUNT_ID"):
        create_broker("oanda")


def test_create_unknown_broker() -> None:
    with pytest.raises(ValueError, match="Unknown broker"):
        create_broker("nonexistent")
