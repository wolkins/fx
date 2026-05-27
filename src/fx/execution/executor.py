from __future__ import annotations

from fx.audit.events import AuditEvent, AuditEventType
from fx.audit.logger import TradeLogger
from fx.broker.base import BrokerAdapter, Order, OrderIntent, OrderStatus
from fx.execution.result import ExecutionResult


class OrderExecutionError(Exception):
    pass


class ReduceNotSupportedError(OrderExecutionError):
    pass


class OrderExecutor:
    """Sends orders through SafetyGuard-wrapped BrokerAdapter and logs results."""

    def __init__(
        self,
        broker: BrokerAdapter,
        logger: TradeLogger,
        *,
        raise_on_error: bool = True,
    ) -> None:
        self._broker = broker
        self._logger = logger
        self._raise_on_error = raise_on_error

    async def execute(self, order: Order) -> ExecutionResult:
        self._logger.log_sent_to_broker(order)

        if order.intent == OrderIntent.CLOSE:
            return await self._execute_close(order)

        if order.intent == OrderIntent.REDUCE:
            return await self._execute_reduce(order)

        return await self._execute_place(order)

    async def _execute_place(self, order: Order) -> ExecutionResult:
        try:
            result = await self._broker.place_order(order)
        except Exception as e:
            if order.status == OrderStatus.REJECTED:
                self._logger.log_order_result(order)
            else:
                self._logger.log(AuditEvent(
                    event_type=AuditEventType.ORDER_FAILED,
                    instrument=order.instrument,
                    side=order.side.value,
                    units=order.units,
                    order_type=order.order_type.value,
                    client_order_id=order.client_order_id,
                    message=str(e),
                ))
            if self._raise_on_error:
                raise OrderExecutionError(str(e)) from e
            return ExecutionResult(order=order)
        self._logger.log_order_result(result)
        return ExecutionResult(order=result)

    async def _execute_close(self, order: Order) -> ExecutionResult:
        try:
            trade_close = await self._broker.close_position(order.instrument, side=order.side)
        except Exception as e:
            self._logger.log(AuditEvent(
                event_type=AuditEventType.ORDER_FAILED,
                instrument=order.instrument,
                side=order.side.value,
                units=order.units,
                order_type=order.order_type.value,
                client_order_id=order.client_order_id,
                message=str(e),
            ))
            if self._raise_on_error:
                raise OrderExecutionError(str(e)) from e
            order.status = OrderStatus.REJECTED
            return ExecutionResult(order=order)

        if trade_close is not None:
            order.status = OrderStatus.FILLED
            order.filled_price = trade_close.close_price
            self._logger.log_trade_closed(
                instrument=trade_close.instrument,
                side=trade_close.side.value,
                units=trade_close.units,
                close_price=trade_close.close_price,
                pnl=trade_close.pnl,
                reason=trade_close.reason,
            )
            return ExecutionResult(order=order, trade_close=trade_close)
        else:
            order.status = OrderStatus.CANCELLED
            self._logger.log(AuditEvent(
                event_type=AuditEventType.ORDER_CANCELLED,
                instrument=order.instrument,
                side=order.side.value,
                units=order.units,
                client_order_id=order.client_order_id,
                reason_code="no_position_to_close",
            ))
            return ExecutionResult(order=order)

    async def _execute_reduce(self, order: Order) -> ExecutionResult:
        self._logger.log(AuditEvent(
            event_type=AuditEventType.ORDER_FAILED,
            instrument=order.instrument,
            side=order.side.value,
            units=order.units,
            order_type=order.order_type.value,
            client_order_id=order.client_order_id,
            reason_code="REDUCE_NOT_SUPPORTED",
            message="REDUCE intent is not yet supported",
        ))
        order.status = OrderStatus.REJECTED
        if self._raise_on_error:
            raise ReduceNotSupportedError("REDUCE intent is not yet supported")
        return ExecutionResult(order=order)
