from __future__ import annotations

from fx.audit.events import AuditEvent, AuditEventType
from fx.audit.logger import TradeLogger
from fx.broker.base import BrokerAdapter, Order


class OrderExecutionError(Exception):
    pass


class OrderExecutor:
    """Sends orders through SafetyGuard-wrapped BrokerAdapter and logs results."""

    def __init__(self, broker: BrokerAdapter, logger: TradeLogger) -> None:
        self._broker = broker
        self._logger = logger

    async def execute(self, order: Order) -> Order:
        self._logger.log_sent_to_broker(order)
        try:
            result = await self._broker.place_order(order)
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
            raise OrderExecutionError(str(e)) from e
        self._logger.log_order_result(result)
        return result
