from __future__ import annotations

from fx.audit.events import AuditEvent, AuditEventType
from fx.audit.logger import TradeLogger
from fx.broker.base import Order, OrderIntent, OrderSide, OrderType, Position
from fx.execution.executor import OrderExecutor
from fx.execution.result import ExecutionResult
from fx.risk.manager import RiskManager
from fx.signal.model import Signal, SignalAction


class TradeManager:
    """Converts Signals into Orders, handles REVERSE→CLOSE+OPEN decomposition,
    runs RiskManager checks, and delegates to OrderExecutor."""

    def __init__(
        self,
        risk_manager: RiskManager,
        executor: OrderExecutor,
        logger: TradeLogger,
        default_units: int = 1000,
    ) -> None:
        self._risk = risk_manager
        self._executor = executor
        self._logger = logger
        self._default_units = default_units

    async def process_signal(
        self,
        signal: Signal,
        positions: list[Position],
        account_balance: float,
        daily_pnl: float = 0.0,
    ) -> list[ExecutionResult]:
        if signal.action == SignalAction.HOLD:
            self._logger.log(AuditEvent(
                event_type=AuditEventType.SIGNAL_HOLD,
                instrument=signal.instrument,
                strategy_id=signal.strategy_id,
                payload={"signal_id": signal.id, "reason": signal.reason, **signal.metadata},
            ))
            return []

        self._logger.log(AuditEvent(
            event_type=AuditEventType.SIGNAL_GENERATED,
            instrument=signal.instrument,
            side=self._signal_side(signal),
            strategy_id=signal.strategy_id,
            payload={
                "signal_id": signal.id,
                "action": signal.action.value,
                "reason": signal.reason,
                **signal.metadata,
            },
        ))

        orders = self._build_orders(signal, positions)

        self._logger.log(AuditEvent(
            event_type=AuditEventType.ORDER_INTENT_CREATED,
            instrument=signal.instrument,
            strategy_id=signal.strategy_id,
            payload={
                "signal_id": signal.id,
                "order_count": len(orders),
                "intents": [o.intent.value for o in orders],
            },
        ))

        results: list[ExecutionResult] = []
        for order in orders:
            decision = self._risk.evaluate(
                order, positions, account_balance, daily_pnl,
                strategy_id=signal.strategy_id,
            )
            if not decision.allowed:
                continue
            exec_result = await self._executor.execute(order)
            results.append(exec_result)
        return results

    def _build_orders(self, signal: Signal, positions: list[Position]) -> list[Order]:
        units = signal.units or self._default_units

        if signal.action in (SignalAction.REVERSE_TO_BUY, SignalAction.REVERSE_TO_SELL):
            return self._build_reverse_orders(signal, positions, units)

        if signal.action in (SignalAction.CLOSE_BUY, SignalAction.CLOSE_SELL):
            return self._build_close_orders(signal, positions)

        side = OrderSide.BUY if signal.action == SignalAction.BUY else OrderSide.SELL
        return [self._make_order(
            signal=signal,
            side=side,
            units=units,
            intent=OrderIntent.OPEN,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )]

    def _build_reverse_orders(
        self, signal: Signal, positions: list[Position], units: int
    ) -> list[Order]:
        new_side = OrderSide.BUY if signal.action == SignalAction.REVERSE_TO_BUY else OrderSide.SELL
        close_side = OrderSide.SELL if new_side == OrderSide.BUY else OrderSide.BUY

        orders: list[Order] = []

        existing = [
            p for p in positions
            if p.instrument == signal.instrument and p.side == close_side and p.units > 0
        ]
        if existing:
            self._logger.log(AuditEvent(
                event_type=AuditEventType.REVERSE_SPLIT,
                instrument=signal.instrument,
                strategy_id=signal.strategy_id,
                payload={
                    "signal_id": signal.id,
                    "close_side": close_side.value,
                    "open_side": new_side.value,
                },
            ))
            orders.append(self._make_order(
                signal=signal,
                side=close_side,
                units=existing[0].units,
                intent=OrderIntent.CLOSE,
            ))

        orders.append(self._make_order(
            signal=signal,
            side=new_side,
            units=units,
            intent=OrderIntent.OPEN,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        ))
        return orders

    def _build_close_orders(self, signal: Signal, positions: list[Position]) -> list[Order]:
        close_side = OrderSide.BUY if signal.action == SignalAction.CLOSE_BUY else OrderSide.SELL
        existing = [
            p for p in positions
            if p.instrument == signal.instrument and p.side == close_side and p.units > 0
        ]
        close_units = existing[0].units if existing else (signal.units or self._default_units)
        return [self._make_order(
            signal=signal,
            side=close_side,
            units=close_units,
            intent=OrderIntent.CLOSE,
        )]

    def _make_order(
        self,
        signal: Signal,
        side: OrderSide,
        units: int,
        intent: OrderIntent,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Order:
        client_order_id = f"{signal.strategy_id}:{signal.id}:{intent.value}:{signal.instrument}"
        return Order(
            id="",
            instrument=signal.instrument,
            side=side,
            order_type=OrderType.MARKET,
            units=units,
            intent=intent,
            stop_loss=stop_loss,
            take_profit=take_profit,
            client_order_id=client_order_id,
        )

    @staticmethod
    def _signal_side(signal: Signal) -> str:
        mapping = {
            SignalAction.BUY: "buy",
            SignalAction.SELL: "sell",
            SignalAction.CLOSE_BUY: "buy",
            SignalAction.CLOSE_SELL: "sell",
            SignalAction.REVERSE_TO_BUY: "buy",
            SignalAction.REVERSE_TO_SELL: "sell",
        }
        return mapping.get(signal.action, "")
