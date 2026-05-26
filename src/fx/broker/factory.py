from __future__ import annotations

from fx.broker.base import BrokerAdapter, BrokerEnvironment
from fx.broker.mt5_stub import MT5Adapter
from fx.broker.oanda import OandaAdapter
from fx.broker.paper import PaperBroker
from fx.broker.safety import SafetyGuard


def create_broker(
    broker_type: str,
    *,
    oanda_account_id: str = "",
    oanda_api_token: str = "",
    environment: BrokerEnvironment = BrokerEnvironment.PRACTICE,
    enable_live_trading: bool = False,
    paper_balance: float = 1_000_000.0,
) -> SafetyGuard:
    broker: BrokerAdapter
    if broker_type == "paper":
        broker = PaperBroker(initial_balance=paper_balance)
    elif broker_type == "oanda":
        if not oanda_account_id or not oanda_api_token:
            raise ValueError("OANDA_ACCOUNT_ID and OANDA_API_TOKEN are required for oanda broker")
        broker = OandaAdapter(
            account_id=oanda_account_id,
            api_token=oanda_api_token,
            environment=environment,
        )
    elif broker_type == "mt5":
        broker = MT5Adapter(environment=environment)
    else:
        raise ValueError(f"Unknown broker type: {broker_type}")

    return SafetyGuard(broker, enable_live_trading=enable_live_trading)
