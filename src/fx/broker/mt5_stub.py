from __future__ import annotations

from fx.broker.base import (
    BrokerAdapter,
    BrokerCapabilities,
    BrokerEnvironment,
    Order,
    OrderSide,
    Position,
    Tick,
)


class MT5Adapter(BrokerAdapter):
    """Stub for future MT4/MT5 broker support.

    Target brokers:
    - 外為ファイネスト MT5
    - 楽天証券 MT4
    - FXTF MT4
    """

    def __init__(self, environment: BrokerEnvironment = BrokerEnvironment.PRACTICE) -> None:
        self._environment = environment

    @property
    def name(self) -> str:
        return f"mt5-{self._environment.value}"

    @property
    def environment(self) -> BrokerEnvironment:
        return self._environment

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_rest_api=False,
            supports_streaming_price=True,
            supports_market_order=True,
            supports_limit_order=True,
            supports_stop_order=True,
            supports_stop_loss=True,
            supports_take_profit=True,
            supports_position_close=True,
            supports_reverse_order=True,
            supports_demo=True,
            min_trade_units=1000,
            max_leverage=25,
            spread_source="mt5",
        )

    async def connect(self) -> None:
        raise NotImplementedError("MT5Adapter is a stub. Install MetaTrader5 package and implement.")

    async def disconnect(self) -> None:
        raise NotImplementedError

    async def get_tick(self, instrument: str) -> Tick:
        raise NotImplementedError

    async def place_order(self, order: Order) -> Order:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    async def get_order(self, order_id: str) -> Order:
        raise NotImplementedError

    async def get_open_orders(self) -> list[Order]:
        raise NotImplementedError

    async def get_positions(self) -> list[Position]:
        raise NotImplementedError

    async def close_position(
        self, instrument: str, side: OrderSide | None = None
    ) -> bool:
        raise NotImplementedError

    async def get_account_balance(self) -> float:
        raise NotImplementedError
