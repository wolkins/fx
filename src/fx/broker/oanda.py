from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

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
)

OANDA_HOSTS = {
    BrokerEnvironment.PRACTICE: "https://api-fxpractice.oanda.com",
    BrokerEnvironment.LIVE: "https://api-fxtrade.oanda.com",
}


class OandaError(Exception):
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body
        super().__init__(f"OANDA API error {status}: {body}")


class OandaAdapter(BrokerAdapter):
    def __init__(
        self,
        account_id: str,
        api_token: str,
        environment: BrokerEnvironment = BrokerEnvironment.PRACTICE,
    ) -> None:
        self._account_id = account_id
        self._api_token = api_token
        self._environment = environment
        self._base_url = OANDA_HOSTS[environment]
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return f"oanda-{self._environment.value}"

    @property
    def environment(self) -> BrokerEnvironment:
        return self._environment

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_rest_api=True,
            supports_streaming_price=True,
            supports_market_order=True,
            supports_limit_order=True,
            supports_stop_loss=True,
            supports_take_profit=True,
            supports_position_close=True,
            supports_reverse_order=False,
            supports_demo=(self._environment == BrokerEnvironment.PRACTICE),
            min_trade_units=1,
            max_leverage=25,
            spread_source="oanda",
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }

    async def connect(self) -> None:
        client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=30.0,
        )
        try:
            resp = await client.get(f"/v3/accounts/{self._account_id}")
            if resp.status_code != 200:
                raise OandaError(resp.status_code, self._safe_json(resp))
        except Exception:
            await client.aclose()
            raise
        self._client = client

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_connected(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._client

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            data: dict[str, Any] = resp.json()
            return data
        except Exception:
            return {"raw": resp.text}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = self._ensure_connected()
        resp = await client.request(method, path, **kwargs)
        data = self._safe_json(resp)
        if resp.status_code >= 400:
            raise OandaError(resp.status_code, data)
        return data

    async def get_tick(self, instrument: str) -> Tick:
        data = await self._request(
            "GET",
            f"/v3/accounts/{self._account_id}/pricing",
            params={"instruments": instrument},
        )
        prices = data.get("prices", [])
        if not prices:
            raise OandaError(404, {"message": f"No price data for {instrument}"})
        price = prices[0]
        bids = price.get("bids", [])
        asks = price.get("asks", [])
        if not bids:
            raise OandaError(404, {"message": f"No bid data for {instrument}"})
        if not asks:
            raise OandaError(404, {"message": f"No ask data for {instrument}"})
        time_str = price.get("time")
        if not time_str:
            raise OandaError(500, {"message": f"Missing timestamp for {instrument}"})
        try:
            bid = float(bids[0]["price"])
            ask = float(asks[0]["price"])
            timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError) as e:
            raise OandaError(500, {"message": f"Invalid price data: {e}"}) from e
        return Tick(instrument=instrument, bid=bid, ask=ask, timestamp=timestamp)

    async def place_order(self, order: Order) -> Order:
        body: dict[str, Any] = {
            "order": {
                "instrument": order.instrument,
                "units": str(order.units if order.side == OrderSide.BUY else -order.units),
                "timeInForce": "FOK" if order.order_type == OrderType.MARKET else "GTC",
                "type": self._to_oanda_order_type(order.order_type),
            }
        }
        if order.price is not None and order.order_type != OrderType.MARKET:
            body["order"]["price"] = str(order.price)
        if order.stop_loss is not None:
            body["order"]["stopLossOnFill"] = {"price": str(order.stop_loss)}
        if order.take_profit is not None:
            body["order"]["takeProfitOnFill"] = {"price": str(order.take_profit)}

        data = await self._request(
            "POST",
            f"/v3/accounts/{self._account_id}/orders",
            json=body,
        )

        order.broker_data["lastTransactionID"] = data.get("lastTransactionID")
        order.broker_data["relatedTransactionIDs"] = data.get("relatedTransactionIDs")
        handled = False

        if "orderCreateTransaction" in data:
            create_txn = data["orderCreateTransaction"]
            order.create_transaction_id = str(create_txn["id"])
            order.broker_order_id = str(create_txn.get("id"))
            handled = True

        if "orderFillTransaction" in data:
            fill = data["orderFillTransaction"]
            order.status = OrderStatus.FILLED
            order.fill_transaction_id = str(fill["id"])
            order.filled_price = float(fill["price"])
            order.filled_at = datetime.fromisoformat(fill["time"].replace("Z", "+00:00"))
            if not order.id:
                order.id = str(fill["id"])
            handled = True
        elif "orderCancelTransaction" in data:
            cancel_txn = data["orderCancelTransaction"]
            order.status = OrderStatus.CANCELLED
            order.cancel_transaction_id = str(cancel_txn["id"])
            order.broker_data["cancel_reason"] = cancel_txn.get("reason")
            if not order.id:
                order.id = str(cancel_txn["id"])
            handled = True
        elif "orderRejectTransaction" in data:
            reject_txn = data["orderRejectTransaction"]
            order.status = OrderStatus.REJECTED
            order.reject_transaction_id = str(reject_txn["id"])
            order.broker_data["reject_reason"] = reject_txn.get("rejectReason")
            if not order.id:
                order.id = str(reject_txn["id"])
            handled = True

        if "orderCreateTransaction" in data and order.status == OrderStatus.PENDING:
            order.status = OrderStatus.PENDING
            if not order.id:
                order.id = order.create_transaction_id or ""
            handled = True

        if not handled:
            order.status = OrderStatus.REJECTED
            order.broker_data["unknown_response"] = data
            raise OandaError(
                500, {"message": "Unknown OANDA order response", "data": data}
            )

        return order

    async def cancel_order(self, order_id: str) -> bool:
        try:
            await self._request(
                "PUT",
                f"/v3/accounts/{self._account_id}/orders/{order_id}/cancel",
            )
            return True
        except OandaError:
            return False

    async def get_order(self, order_id: str) -> Order:
        data = await self._request(
            "GET",
            f"/v3/accounts/{self._account_id}/orders/{order_id}",
        )
        return self._parse_order(data["order"])

    async def get_open_orders(self) -> list[Order]:
        data = await self._request(
            "GET",
            f"/v3/accounts/{self._account_id}/pendingOrders",
        )
        return [self._parse_order(o) for o in data.get("orders", [])]

    async def get_positions(self) -> list[Position]:
        data = await self._request(
            "GET",
            f"/v3/accounts/{self._account_id}/openPositions",
        )
        positions: list[Position] = []
        for p in data.get("positions", []):
            long_units = int(p["long"]["units"])
            short_units = int(p["short"]["units"])
            if long_units > 0:
                positions.append(Position(
                    instrument=p["instrument"],
                    side=OrderSide.BUY,
                    units=long_units,
                    avg_price=float(p["long"]["averagePrice"]),
                    unrealized_pnl=float(p["long"]["unrealizedPL"]),
                    realized_pnl=float(p["long"]["pl"]),
                ))
            if short_units != 0:
                positions.append(Position(
                    instrument=p["instrument"],
                    side=OrderSide.SELL,
                    units=abs(short_units),
                    avg_price=float(p["short"]["averagePrice"]),
                    unrealized_pnl=float(p["short"]["unrealizedPL"]),
                    realized_pnl=float(p["short"]["pl"]),
                ))
        return positions

    async def close_position(
        self, instrument: str, side: OrderSide | None = None
    ) -> bool:
        body: dict[str, str] = {}
        if side == OrderSide.BUY:
            body["longUnits"] = "ALL"
        elif side == OrderSide.SELL:
            body["shortUnits"] = "ALL"
        else:
            body["longUnits"] = "ALL"
            body["shortUnits"] = "ALL"
        try:
            await self._request(
                "PUT",
                f"/v3/accounts/{self._account_id}/positions/{instrument}/close",
                json=body,
            )
            return True
        except OandaError:
            return False

    async def get_account_balance(self) -> float:
        data = await self._request(
            "GET",
            f"/v3/accounts/{self._account_id}",
        )
        return float(data["account"]["balance"])

    @staticmethod
    def _to_oanda_order_type(order_type: OrderType) -> str:
        mapping = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.STOP: "STOP",
        }
        return mapping[order_type]

    @staticmethod
    def _parse_order(raw: dict[str, Any]) -> Order:
        oanda_type = raw.get("type", "MARKET")
        type_map = {"MARKET": OrderType.MARKET, "LIMIT": OrderType.LIMIT, "STOP": OrderType.STOP}
        units = int(raw.get("units", "0"))
        create_time = raw.get("createTime")
        if create_time:
            created_at = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
        else:
            created_at = datetime.now(tz=timezone.utc)
        return Order(
            id=str(raw["id"]),
            instrument=raw["instrument"],
            side=OrderSide.BUY if units >= 0 else OrderSide.SELL,
            order_type=type_map.get(oanda_type, OrderType.MARKET),
            units=abs(units),
            status=OrderStatus.PENDING,
            price=float(raw["price"]) if "price" in raw else None,
            created_at=created_at,
            broker_order_id=str(raw["id"]),
            broker_data=raw,
        )
