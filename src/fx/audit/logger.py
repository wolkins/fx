from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from fx.audit.events import AuditEvent, AuditEventType
from fx.broker.base import Order, OrderStatus


class AuditLogWriteError(Exception):
    pass


class TradeLogger(ABC):
    @abstractmethod
    def log(self, event: AuditEvent) -> None: ...

    @abstractmethod
    def get_events(
        self, event_type: AuditEventType | None = None
    ) -> list[AuditEvent]: ...

    def log_order_submitted(self, order: Order, *, strategy_id: str | None = None) -> None:
        self.log(AuditEvent(
            event_type=AuditEventType.ORDER_SUBMITTED,
            instrument=order.instrument,
            side=order.side.value,
            units=order.units,
            order_type=order.order_type.value,
            client_order_id=order.client_order_id,
            strategy_id=strategy_id,
            payload=self._order_payload(order),
        ))

    def log_risk_accepted(self, order: Order, *, strategy_id: str | None = None) -> None:
        self.log(AuditEvent(
            event_type=AuditEventType.ORDER_ACCEPTED_BY_RISK,
            instrument=order.instrument,
            side=order.side.value,
            units=order.units,
            order_type=order.order_type.value,
            client_order_id=order.client_order_id,
            strategy_id=strategy_id,
        ))

    def log_risk_rejected(
        self,
        order: Order,
        *,
        reason_code: str,
        message: str,
        strategy_id: str | None = None,
        risk_state: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"order": self._order_payload(order)}
        if risk_state:
            payload["risk_state"] = risk_state
        self.log(AuditEvent(
            event_type=AuditEventType.ORDER_REJECTED_BY_RISK,
            instrument=order.instrument,
            side=order.side.value,
            units=order.units,
            order_type=order.order_type.value,
            client_order_id=order.client_order_id,
            strategy_id=strategy_id,
            reason_code=reason_code,
            message=message,
            payload=payload,
        ))

    def log_sent_to_broker(self, order: Order) -> None:
        self.log(AuditEvent(
            event_type=AuditEventType.ORDER_SENT_TO_BROKER,
            instrument=order.instrument,
            side=order.side.value,
            units=order.units,
            order_type=order.order_type.value,
            client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
        ))

    def log_order_result(self, order: Order) -> None:
        if order.status == OrderStatus.FILLED:
            self.log(AuditEvent(
                event_type=AuditEventType.ORDER_FILLED,
                instrument=order.instrument,
                side=order.side.value,
                units=order.units,
                order_type=order.order_type.value,
                client_order_id=order.client_order_id,
                broker_order_id=order.broker_order_id,
                payload={
                    "filled_price": order.filled_price,
                    "fill_transaction_id": order.fill_transaction_id,
                },
            ))
        elif order.status == OrderStatus.REJECTED:
            self.log(AuditEvent(
                event_type=AuditEventType.ORDER_REJECTED_BY_BROKER,
                instrument=order.instrument,
                side=order.side.value,
                units=order.units,
                order_type=order.order_type.value,
                client_order_id=order.client_order_id,
                broker_order_id=order.broker_order_id,
                reason_code=order.broker_data.get("reject_reason")
                or order.broker_data.get("errorCode"),
                message=order.broker_data.get("errorMessage"),
                payload={
                    "reject_transaction_id": order.reject_transaction_id,
                },
            ))
        elif order.status == OrderStatus.CANCELLED:
            self.log(AuditEvent(
                event_type=AuditEventType.ORDER_CANCELLED,
                instrument=order.instrument,
                side=order.side.value,
                units=order.units,
                order_type=order.order_type.value,
                client_order_id=order.client_order_id,
                broker_order_id=order.broker_order_id,
                reason_code=order.broker_data.get("cancel_reason"),
            ))

    def log_sl_triggered(
        self,
        instrument: str,
        side: str,
        units: int,
        close_price: float,
        pnl: float,
    ) -> None:
        self.log(AuditEvent(
            event_type=AuditEventType.POSITION_SL_TRIGGERED,
            instrument=instrument,
            side=side,
            units=units,
            payload={"close_price": close_price, "pnl": pnl},
        ))

    def log_tp_triggered(
        self,
        instrument: str,
        side: str,
        units: int,
        close_price: float,
        pnl: float,
    ) -> None:
        self.log(AuditEvent(
            event_type=AuditEventType.POSITION_TP_TRIGGERED,
            instrument=instrument,
            side=side,
            units=units,
            payload={"close_price": close_price, "pnl": pnl},
        ))

    def log_trade_closed(
        self,
        instrument: str,
        side: str,
        units: int,
        close_price: float,
        pnl: float,
        reason: str,
    ) -> None:
        self.log(AuditEvent(
            event_type=AuditEventType.TRADE_CLOSED,
            instrument=instrument,
            side=side,
            units=units,
            reason_code=reason,
            payload={"close_price": close_price, "pnl": pnl},
        ))

    @staticmethod
    def _order_payload(order: Order) -> dict[str, Any]:
        p: dict[str, Any] = {
            "instrument": order.instrument,
            "side": order.side.value,
            "units": order.units,
            "order_type": order.order_type.value,
            "intent": order.intent.value,
        }
        if order.price is not None:
            p["price"] = order.price
        if order.stop_loss is not None:
            p["stop_loss"] = order.stop_loss
        if order.take_profit is not None:
            p["take_profit"] = order.take_profit
        if order.client_order_id:
            p["client_order_id"] = order.client_order_id
        return p


class InMemoryTradeLogger(TradeLogger):
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def log(self, event: AuditEvent) -> None:
        self._events.append(event)

    def get_events(
        self, event_type: AuditEventType | None = None
    ) -> list[AuditEvent]:
        if event_type is None:
            return list(self._events)
        return [e for e in self._events if e.event_type == event_type]


class JSONLinesTradeLogger(TradeLogger):
    def __init__(
        self,
        path: Path,
        *,
        fsync: bool = False,
        fail_on_error: bool = False,
    ) -> None:
        self._path = path
        self._fsync = fsync
        self._fail_on_error = fail_on_error
        self._events: list[AuditEvent] = []

    def log(self, event: AuditEvent) -> None:
        self._events.append(event)
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                f.flush()
                if self._fsync:
                    os.fsync(f.fileno())
        except OSError as e:
            if self._fail_on_error:
                raise AuditLogWriteError(f"Failed to write audit log: {e}") from e

    def get_events(
        self, event_type: AuditEventType | None = None
    ) -> list[AuditEvent]:
        if event_type is None:
            return list(self._events)
        return [e for e in self._events if e.event_type == event_type]
