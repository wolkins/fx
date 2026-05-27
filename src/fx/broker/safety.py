from __future__ import annotations

from fx.broker.base import (
    BrokerAdapter,
    BrokerCapabilities,
    BrokerEnvironment,
    Order,
    OrderSide,
    OrderType,
    Position,
    Tick,
)


class LiveTradingDisabledError(Exception):
    pass


class OrderValidationError(Exception):
    pass


class SafetyGuard(BrokerAdapter):
    """Decorator that wraps a BrokerAdapter and enforces safety controls."""

    def __init__(self, broker: BrokerAdapter, *, enable_live_trading: bool = False) -> None:
        self._broker = broker
        self._enable_live_trading = enable_live_trading

    def _unsafe_inner_for_tests(self) -> BrokerAdapter:
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

    def _validate_order(self, order: Order) -> None:
        if order.units <= 0:
            raise OrderValidationError("order.units must be positive.")

        caps = self._broker.capabilities

        if order.order_type == OrderType.MARKET and not caps.supports_market_order:
            raise OrderValidationError(
                f"{self._broker.name} does not support market orders."
            )
        if order.order_type == OrderType.LIMIT and not caps.supports_limit_order:
            raise OrderValidationError(
                f"{self._broker.name} does not support limit orders."
            )

        if self._broker.environment == BrokerEnvironment.LIVE:
            if not caps.supports_stop_loss:
                raise LiveTradingDisabledError(
                    f"{self._broker.name} does not support stop_loss. "
                    "Live trading requires SL capability."
                )
            if not caps.supports_take_profit:
                raise LiveTradingDisabledError(
                    f"{self._broker.name} does not support take_profit. "
                    "Live trading requires TP capability."
                )
            if order.order_type == OrderType.MARKET:
                if order.stop_loss is None:
                    raise OrderValidationError(
                        "Live market order requires stop_loss."
                    )
                if order.take_profit is None:
                    raise OrderValidationError(
                        "Live market order requires take_profit."
                    )

    async def connect(self) -> None:
        await self._broker.connect()

    async def disconnect(self) -> None:
        await self._broker.disconnect()

    async def get_tick(self, instrument: str) -> Tick:
        return await self._broker.get_tick(instrument)

    async def place_order(self, order: Order) -> Order:
        self._check_write_allowed()
        self._validate_order(order)
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

    async def close_position(
        self, instrument: str, side: OrderSide | None = None
    ) -> bool:
        self._check_write_allowed()
        return await self._broker.close_position(instrument, side)

    async def get_account_balance(self) -> float:
        return await self._broker.get_account_balance()
