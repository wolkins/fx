from __future__ import annotations

from pydantic_settings import BaseSettings

from fx.broker.base import BrokerEnvironment


class FxConfig(BaseSettings):
    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    broker_type: str = "oanda"
    oanda_account_id: str = ""
    oanda_api_token: str = ""
    oanda_env: BrokerEnvironment = BrokerEnvironment.PRACTICE
    enable_live_trading: bool = False
    paper_balance: float = 1_000_000.0
