from __future__ import annotations

from fx.broker.base import (
    BrokerAdapter,
    BrokerCapabilities,
    BrokerEnvironment,
    Order,
    Position,
    Tick,
)


class LiveTradingDisabledError(Exception):
    pass


class SafetyGuard(BrokerAdapter):
    """Decorator that wraps a BrokerAdapter and blocks live orders unless explicitly enabled."""

    def __init__(self, broker: BrokerAdapter, *, enable_live_trading: bool = False) -> None:
        self._broker = broker
        self._enable_live_trading = enable_live_trading

    @property
    def inner(self) -> BrokerAdapter:
        return self._broker

    @property
    def name(self) -> str:
        return self._broker.name

    @property
    def environment(self) -> BrokerEnvironment:
        return self._broker.environment

    @property
    def capabilities(self) -> BrokerCapabilities:
        return self._broker.capabilities

    @property
    def is_live_allowed(self) -> bool:
        if self._broker.environment == BrokerEnvironment.PRACTICE:
            return True
        return self._enable_live_trading

    def _check_write_allowed(self) -> None:
        if self._broker.environment == BrokerEnvironment.LIVE and not self._enable_live_trading:
            raise LiveTradingDisabledError(
                "Live trading is disabled. Set ENABLE_LIVE_TRADING=true to enable. "
                "Ensure you have verified backtest and forward-test results before enabling."
            )

    async def connect(self) -> None:
        await self._broker.connect()

    async def disconnect(self) -> None:
        await self._broker.disconnect()

    async def get_tick(self, instrument: str) -> Tick:
        return await self._broker.get_tick(instrument)

    async def place_order(self, order: Order) -> Order:
        self._check_write_allowed()
        return await self._broker.place_order(order)

    async def cancel_order(self, order_id: str) -> bool:
        self._check_write_allowed()
        return await self._broker.cancel_order(order_id)

    async def get_order(self, order_id: str) -> Order:
        return await self._broker.get_order(order_id)

    async def get_open_orders(self) -> list[Order]:
        return await self._broker.get_open_orders()

    async def get_positions(self) -> list[Position]:
        return await self._broker.get_positions()

    async def close_position(self, instrument: str) -> bool:
        self._check_write_allowed()
        return await self._broker.close_position(instrument)

    async def get_account_balance(self) -> float:
        return await self._broker.get_account_balance()
