from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fx.broker.base import (
    BrokerAdapter,
    BrokerCapabilities,
    BrokerEnvironment,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Tick,
    TradeClose,
)


class PaperBroker(BrokerAdapter):
    """In-memory simulated broker for backtesting and paper trading."""

    def __init__(self, initial_balance: float = 1_000_000.0) -> None:
        self._balance = initial_balance
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._ticks: dict[str, Tick] = {}

    @property
    def name(self) -> str:
        return "paper"

    @property
    def environment(self) -> BrokerEnvironment:
        return BrokerEnvironment.PRACTICE

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_rest_api=False,
            supports_streaming_price=False,
            supports_market_order=True,
            supports_limit_order=True,
            supports_stop_order=True,
            supports_stop_loss=True,
            supports_take_profit=True,
            supports_position_close=True,
            supports_reverse_order=False,
            supports_demo=True,
            min_trade_units=1,
            max_leverage=25,
            spread_source="simulated",
        )

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    def inject_tick(self, tick: Tick) -> None:
        self._ticks[tick.instrument] = tick

    async def get_tick(self, instrument: str) -> Tick:
        if instrument not in self._ticks:
            raise KeyError(f"No tick data for {instrument}. Call inject_tick() first.")
        return self._ticks[instrument]

    async def place_order(self, order: Order) -> Order:
        order.id = order.id or str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)

        if order.order_type == OrderType.MARKET:
            tick = await self.get_tick(order.instrument)
            fill_price = tick.ask if order.side == OrderSide.BUY else tick.bid
            order.status = OrderStatus.FILLED
            order.filled_price = fill_price
            order.filled_at = now
            self._update_position(order)
        else:
            order.status = OrderStatus.PENDING

        self._orders[order.id] = order
        return order

    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders and self._orders[order_id].status == OrderStatus.PENDING:
            self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    async def get_order(self, order_id: str) -> Order:
        if order_id not in self._orders:
            raise KeyError(f"Order {order_id} not found")
        return self._orders[order_id]

    async def get_open_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.PENDING]

    async def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.units > 0]

    async def close_position(
        self, instrument: str, side: OrderSide | None = None
    ) -> TradeClose | None:
        if instrument not in self._positions or self._positions[instrument].units <= 0:
            return None
        pos = self._positions[instrument]
        if side is not None and pos.side != side:
            return None
        tick = await self.get_tick(instrument)
        close_price = tick.bid if pos.side == OrderSide.BUY else tick.ask
        if pos.side == OrderSide.BUY:
            pnl = (close_price - pos.avg_price) * pos.units
        else:
            pnl = (pos.avg_price - close_price) * pos.units
        result = TradeClose(
            instrument=instrument,
            side=pos.side,
            units=pos.units,
            close_price=close_price,
            pnl=pnl,
            reason="close_position",
            entry_price=pos.avg_price,
        )
        self._balance += pnl
        pos.realized_pnl += pnl
        pos.units = 0
        return result

    async def get_account_balance(self) -> float:
        return self._balance

    def get_all_orders(self) -> list[Order]:
        return list(self._orders.values())

    def process_tick(self, tick: Tick) -> tuple[list[Order], list[TradeClose]]:
        """Evaluate pending orders and SL/TP against the new tick.

        Returns (filled_orders, trade_closes).
        """
        self._ticks[tick.instrument] = tick
        filled = self._process_pending_orders(tick)
        closes = self._process_sl_tp(tick)
        return filled, closes

    def _process_pending_orders(self, tick: Tick) -> list[Order]:
        filled: list[Order] = []
        for order in list(self._orders.values()):
            if order.status != OrderStatus.PENDING:
                continue
            if order.instrument != tick.instrument:
                continue
            if order.price is None:
                continue

            triggered = False
            if order.order_type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and tick.ask <= order.price:
                    triggered = True
                elif order.side == OrderSide.SELL and tick.bid >= order.price:
                    triggered = True
            elif order.order_type == OrderType.STOP:
                if order.side == OrderSide.BUY and tick.ask >= order.price:
                    triggered = True
                elif order.side == OrderSide.SELL and tick.bid <= order.price:
                    triggered = True

            if triggered:
                fill_price = tick.ask if order.side == OrderSide.BUY else tick.bid
                order.status = OrderStatus.FILLED
                order.filled_price = fill_price
                order.filled_at = datetime.now(tz=timezone.utc)
                self._update_position(order)
                filled.append(order)
        return filled

    def process_ohlc_sl_tp(
        self, instrument: str, high: float, low: float, close: float, spread: float
    ) -> list[TradeClose]:
        """OHLC-based SL/TP check. SL is prioritized when both hit in same candle."""
        closes: list[TradeClose] = []
        for pos in list(self._positions.values()):
            if pos.units <= 0 or pos.instrument != instrument:
                continue

            sl_hit = False
            tp_hit = False
            if pos.side == OrderSide.BUY:
                if pos.stop_loss is not None and low <= pos.stop_loss:
                    sl_hit = True
                if pos.take_profit is not None and high >= pos.take_profit:
                    tp_hit = True
            else:
                if pos.stop_loss is not None and high >= pos.stop_loss:
                    sl_hit = True
                if pos.take_profit is not None and low <= pos.take_profit:
                    tp_hit = True

            if sl_hit:
                close_price = pos.stop_loss or 0.0
                reason = "stop_loss"
            elif tp_hit:
                close_price = pos.take_profit or 0.0
                reason = "take_profit"
            else:
                continue

            if pos.side == OrderSide.BUY:
                pnl = (close_price - pos.avg_price) * pos.units
            else:
                pnl = (pos.avg_price - close_price) * pos.units
            closes.append(TradeClose(
                instrument=pos.instrument,
                side=pos.side,
                units=pos.units,
                close_price=close_price,
                pnl=pnl,
                reason=reason,
                entry_price=pos.avg_price,
            ))
            self._balance += pnl
            pos.realized_pnl += pnl
            pos.units = 0

            half = spread / 2
            self._ticks[instrument] = Tick(
                instrument=instrument,
                bid=close - half,
                ask=close + half,
                timestamp=datetime.now(tz=timezone.utc),
            )
        return closes

    def _process_sl_tp(self, tick: Tick) -> list[TradeClose]:
        closes: list[TradeClose] = []
        for pos in list(self._positions.values()):
            if pos.units <= 0 or pos.instrument != tick.instrument:
                continue

            close_price: float | None = None
            reason = ""

            if pos.side == OrderSide.BUY:
                if pos.stop_loss is not None and tick.bid <= pos.stop_loss:
                    close_price = tick.bid
                    reason = "stop_loss"
                elif pos.take_profit is not None and tick.bid >= pos.take_profit:
                    close_price = tick.bid
                    reason = "take_profit"
            else:
                if pos.stop_loss is not None and tick.ask >= pos.stop_loss:
                    close_price = tick.ask
                    reason = "stop_loss"
                elif pos.take_profit is not None and tick.ask <= pos.take_profit:
                    close_price = tick.ask
                    reason = "take_profit"

            if close_price is not None:
                if pos.side == OrderSide.BUY:
                    pnl = (close_price - pos.avg_price) * pos.units
                else:
                    pnl = (pos.avg_price - close_price) * pos.units
                closes.append(TradeClose(
                    instrument=pos.instrument,
                    side=pos.side,
                    units=pos.units,
                    close_price=close_price,
                    pnl=pnl,
                    reason=reason,
                    entry_price=pos.avg_price,
                ))
                self._balance += pnl
                pos.realized_pnl += pnl
                pos.units = 0

        return closes

    def _update_position(self, order: Order) -> None:
        assert order.filled_price is not None, "Cannot update position with unfilled order"
        fill_price = order.filled_price

        if order.instrument not in self._positions:
            self._positions[order.instrument] = Position(
                instrument=order.instrument,
                side=order.side,
                units=order.units,
                avg_price=fill_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
            )
            return

        pos = self._positions[order.instrument]
        if pos.units == 0:
            pos.side = order.side
            pos.units = order.units
            pos.avg_price = fill_price
            pos.stop_loss = order.stop_loss
            pos.take_profit = order.take_profit
        elif pos.side == order.side:
            total_cost = pos.avg_price * pos.units + fill_price * order.units
            pos.units += order.units
            pos.avg_price = total_cost / pos.units
            if order.stop_loss is not None:
                pos.stop_loss = order.stop_loss
            if order.take_profit is not None:
                pos.take_profit = order.take_profit
        else:
            if pos.side == OrderSide.BUY:
                pnl = (fill_price - pos.avg_price) * min(order.units, pos.units)
            else:
                pnl = (pos.avg_price - fill_price) * min(order.units, pos.units)
            self._balance += pnl
            pos.realized_pnl += pnl

            if order.units >= pos.units:
                remaining = order.units - pos.units
                pos.side = order.side
                pos.units = remaining
                pos.avg_price = fill_price
                pos.stop_loss = order.stop_loss
                pos.take_profit = order.take_profit
            else:
                pos.units -= order.units
