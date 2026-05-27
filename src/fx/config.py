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
    execution_mode: str = "paper"
    risk_per_trade: float = 0.005
    daily_loss_limit: float = 0.02
    max_open_positions: int = 3
    max_spread_pips: float = 2.0
    default_symbol: str = "USD_JPY"
    default_timeframe: str = "M15"
