from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AuditEventType(str, Enum):
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACCEPTED_BY_RISK = "ORDER_ACCEPTED_BY_RISK"
    ORDER_REJECTED_BY_RISK = "ORDER_REJECTED_BY_RISK"
    ORDER_SENT_TO_BROKER = "ORDER_SENT_TO_BROKER"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED_BY_BROKER = "ORDER_REJECTED_BY_BROKER"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    TRADE_CLOSED = "TRADE_CLOSED"
    POSITION_SL_TRIGGERED = "POSITION_SL_TRIGGERED"
    POSITION_TP_TRIGGERED = "POSITION_TP_TRIGGERED"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    SIGNAL_HOLD = "SIGNAL_HOLD"
    ORDER_INTENT_CREATED = "ORDER_INTENT_CREATED"
    RISK_BYPASSED_FOR_CLOSE = "RISK_BYPASSED_FOR_CLOSE"
    RISK_BYPASSED_FOR_REDUCE = "RISK_BYPASSED_FOR_REDUCE"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    ORDER_FAILED = "ORDER_FAILED"
    POSITION_POLICY_REJECTED = "POSITION_POLICY_REJECTED"


@dataclass
class AuditEvent:
    event_type: AuditEventType
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    instrument: str = ""
    side: str = ""
    units: int = 0
    order_type: str = ""
    client_order_id: str | None = None
    broker_order_id: str | None = None
    strategy_id: str | None = None
    reason_code: str | None = None
    message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "instrument": self.instrument,
            "side": self.side,
            "units": self.units,
            "order_type": self.order_type,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "strategy_id": self.strategy_id,
            "reason_code": self.reason_code,
            "message": self.message,
            "payload": self.payload,
        }
