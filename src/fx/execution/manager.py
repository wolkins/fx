from __future__ import annotations

from dataclasses import dataclass, field

from fx.audit.events import AuditEvent, AuditEventType
from fx.audit.logger import TradeLogger
from fx.broker.base import Order, OrderIntent, OrderSide, OrderStatus, OrderType, Position
from fx.execution.executor import OrderExecutor
from fx.execution.policy import PositionPolicy
from fx.execution.result import ExecutionResult
from fx.risk.manager import RiskManager
from fx.signal.model import Signal, SignalAction


@dataclass
class _OrderPlan:
    """A built sequence of orders plus whether the OPEN leg depends on a preceding
    CLOSE leg (the CLOSE+OPEN reverse/auto-reverse pair). When True, the OPEN leg must
    not be placed unless the CLOSE leg actually succeeded."""

    orders: list[Order] = field(default_factory=list)
    open_depends_on_close: bool = False


class TradeManager:
    """Converts Signals into Orders, handles REVERSE→CLOSE+OPEN decomposition,
    runs RiskManager checks, and delegates to OrderExecutor."""

    def __init__(
        self,
        risk_manager: RiskManager,
        executor: OrderExecutor,
        logger: TradeLogger,
        default_units: int = 1000,
        position_policy: PositionPolicy = PositionPolicy.REJECT_OPPOSITE_OPEN,
    ) -> None:
        self._risk = risk_manager
        self._executor = executor
        self._logger = logger
        self._default_units = default_units
        self._position_policy = position_policy

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

        plan = self._build_orders(signal, positions)

        self._logger.log(AuditEvent(
            event_type=AuditEventType.ORDER_INTENT_CREATED,
            instrument=signal.instrument,
            strategy_id=signal.strategy_id,
            payload={
                "signal_id": signal.id,
                "order_count": len(plan.orders),
                "intents": [o.intent.value for o in plan.orders],
                "open_depends_on_close": plan.open_depends_on_close,
            },
        ))

        return await self._execute_plan(
            signal, plan, positions, account_balance, daily_pnl
        )

    async def _execute_plan(
        self,
        signal: Signal,
        plan: _OrderPlan,
        positions: list[Position],
        account_balance: float,
        daily_pnl: float,
    ) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        # Only meaningful for a CLOSE→OPEN pair: tracks whether the CLOSE leg succeeded.
        close_leg_ok = True

        for order in plan.orders:
            dependent_open = (
                plan.open_depends_on_close and order.intent == OrderIntent.OPEN
            )
            # Do not place a reverse OPEN leg if its CLOSE leg did not succeed.
            if dependent_open and not close_leg_ok:
                self._log_reverse_open_skipped(signal, order)
                continue

            decision = self._risk.evaluate(
                order, positions, account_balance, daily_pnl,
                strategy_id=signal.strategy_id,
            )
            if not decision.allowed:
                if plan.open_depends_on_close and order.intent == OrderIntent.CLOSE:
                    close_leg_ok = False
                elif dependent_open:
                    self._log_reverse_open_failed(signal, order, reason="risk_rejected")
                continue

            exec_result = await self._executor.execute(order)
            results.append(exec_result)

            if plan.open_depends_on_close and order.intent == OrderIntent.CLOSE:
                close_leg_ok = self._close_leg_succeeded(exec_result)
            elif dependent_open and exec_result.order.status != OrderStatus.FILLED:
                self._log_reverse_open_failed(
                    signal, order, reason="open_execution_failed"
                )

        return results

    @staticmethod
    def _close_leg_succeeded(result: ExecutionResult) -> bool:
        return (
            result.trade_close is not None
            and result.order.status == OrderStatus.FILLED
        )

    def _log_reverse_open_skipped(self, signal: Signal, order: Order) -> None:
        self._logger.log(AuditEvent(
            event_type=AuditEventType.REVERSE_OPEN_SKIPPED,
            instrument=signal.instrument,
            side=order.side.value,
            units=order.units,
            strategy_id=signal.strategy_id,
            client_order_id=order.client_order_id,
            reason_code="close_leg_failed",
            message="Close leg did not succeed; reverse open leg was not placed.",
            payload={
                "signal_id": signal.id,
                "reason": "close_leg_failed",
                "policy": self._position_policy.value,
            },
        ))

    def _log_reverse_open_failed(
        self, signal: Signal, order: Order, *, reason: str
    ) -> None:
        self._logger.log(AuditEvent(
            event_type=AuditEventType.REVERSE_OPEN_FAILED,
            instrument=signal.instrument,
            side=order.side.value,
            units=order.units,
            strategy_id=signal.strategy_id,
            client_order_id=order.client_order_id,
            reason_code=reason,
            message="Close leg succeeded but open leg did not fill; position is flat.",
            payload={
                "signal_id": signal.id,
                "reason": reason,
                "policy": self._position_policy.value,
            },
        ))

    def _build_orders(self, signal: Signal, positions: list[Position]) -> _OrderPlan:
        units = signal.units or self._default_units

        if signal.action in (SignalAction.REVERSE_TO_BUY, SignalAction.REVERSE_TO_SELL):
            return self._build_reverse_orders(signal, positions, units)

        if signal.action in (SignalAction.CLOSE_BUY, SignalAction.CLOSE_SELL):
            return _OrderPlan(self._build_close_orders(signal, positions))

        return self._build_open_orders(signal, positions, units)

    def _build_open_orders(
        self, signal: Signal, positions: list[Position], units: int
    ) -> _OrderPlan:
        side = OrderSide.BUY if signal.action == SignalAction.BUY else OrderSide.SELL
        opposite = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

        existing = [
            p for p in positions
            if p.instrument == signal.instrument and p.side == opposite and p.units > 0
        ]
        if existing:
            if self._position_policy == PositionPolicy.REJECT_OPPOSITE_OPEN:
                self._logger.log(AuditEvent(
                    event_type=AuditEventType.POSITION_POLICY_REJECTED,
                    instrument=signal.instrument,
                    side=side.value,
                    units=units,
                    strategy_id=signal.strategy_id,
                    reason_code="opposite_position_exists",
                    payload={
                        "signal_id": signal.id,
                        "action": signal.action.value,
                        "policy": self._position_policy.value,
                        "reason": "opposite_position_exists",
                        "existing_side": opposite.value,
                    },
                ))
                return _OrderPlan([])
            if self._position_policy == PositionPolicy.AUTO_REVERSE_SPLIT:
                return self._build_auto_reverse_orders(signal, existing, side, units)
            # ALLOW_NETTING falls through to a plain OPEN that nets at the broker.

        return _OrderPlan([self._make_order(
            signal=signal,
            side=side,
            units=units,
            intent=OrderIntent.OPEN,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )])

    def _build_auto_reverse_orders(
        self, signal: Signal, existing: list[Position], side: OrderSide, units: int
    ) -> _OrderPlan:
        close_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        self._logger.log(AuditEvent(
            event_type=AuditEventType.REVERSE_SPLIT,
            instrument=signal.instrument,
            strategy_id=signal.strategy_id,
            payload={
                "signal_id": signal.id,
                "close_side": close_side.value,
                "open_side": side.value,
                "policy": self._position_policy.value,
            },
        ))
        return _OrderPlan(
            orders=[
                self._make_order(
                    signal=signal,
                    side=close_side,
                    units=existing[0].units,
                    intent=OrderIntent.CLOSE,
                ),
                self._make_order(
                    signal=signal,
                    side=side,
                    units=units,
                    intent=OrderIntent.OPEN,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                ),
            ],
            open_depends_on_close=True,
        )

    def _build_reverse_orders(
        self, signal: Signal, positions: list[Position], units: int
    ) -> _OrderPlan:
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
        # The OPEN leg depends on the CLOSE leg only when a CLOSE leg is present.
        return _OrderPlan(orders=orders, open_depends_on_close=bool(existing))

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
