from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BrokerEnvironment(str, Enum):
    PRACTICE = "practice"
    LIVE = "live"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class BrokerCapabilities:
    supports_rest_api: bool = False
    supports_streaming_price: bool = False
    supports_market_order: bool = False
    supports_limit_order: bool = False
    supports_stop_order: bool = False
    supports_stop_loss: bool = False
    supports_take_profit: bool = False
    supports_position_close: bool = False
    supports_reverse_order: bool = False
    supports_demo: bool = False
    min_trade_units: int = 1
    max_leverage: int = 25
    spread_source: str = "unknown"


@dataclass
class Tick:
    instrument: str
    bid: float
    ask: float
    timestamp: datetime
    spread: float = field(init=False)

    def __post_init__(self) -> None:
        self.spread = self.ask - self.bid


@dataclass
class Order:
    """id is an application-level identifier. Use broker_order_id for the broker's own order ID."""

    id: str
    instrument: str
    side: OrderSide
    order_type: OrderType
    units: int
    status: OrderStatus = OrderStatus.PENDING
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    filled_price: float | None = None
    filled_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    client_order_id: str | None = None
    client_tag: str | None = None
    client_comment: str | None = None
    broker_order_id: str | None = None
    create_transaction_id: str | None = None
    fill_transaction_id: str | None = None
    cancel_transaction_id: str | None = None
    reject_transaction_id: str | None = None
    broker_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    instrument: str
    side: OrderSide
    units: int
    avg_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    broker_data: dict[str, Any] = field(default_factory=dict)


class BrokerAdapter(ABC):
    """All broker integrations implement this interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def environment(self) -> BrokerEnvironment: ...

    @property
    @abstractmethod
    def capabilities(self) -> BrokerCapabilities: ...

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def get_tick(self, instrument: str) -> Tick: ...

    @abstractmethod
    async def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_order(self, order_id: str) -> Order: ...

    @abstractmethod
    async def get_open_orders(self) -> list[Order]: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def close_position(
        self, instrument: str, side: OrderSide | None = None
    ) -> bool: ...

    @abstractmethod
    async def get_account_balance(self) -> float: ...

    async def __aenter__(self) -> BrokerAdapter:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    def ensure_capability(self, capability: str) -> None:
        if not getattr(self.capabilities, capability, False):
            raise NotImplementedError(
                f"{self.name} does not support '{capability}'"
            )
