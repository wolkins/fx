"""In-memory fake OANDA transport for network-free integration tests.

FakeOandaTransport implements the OandaTransport protocol and returns
OANDA-shaped responses so OandaAdapter can be exercised end-to-end without any
network access or credentials. It also records every request for assertions.

Reject scenarios are modelled as OANDA does: an HTTP >= 400 with an
orderRejectTransaction / errorCode body, surfaced by raising OandaError.
"""

from __future__ import annotations

from typing import Any

from fx.broker.oanda import OandaError

_FIXED_TIME = "2025-01-02T03:04:05.000000000Z"


class FakeOandaTransport:
    """Configurable, network-free OandaTransport.

    Tokens/account ids are never required and never stored beyond what the adapter
    passes; this fake holds no secrets.
    """

    def __init__(self, *, account_currency: str = "JPY", balance: float = 1_000_000.0) -> None:
        self.requests: list[dict[str, Any]] = []
        self._prices: dict[str, tuple[float, float]] = {}
        self._account_currency = account_currency
        self._balance = balance
        self._txid = 100
        self.connected = False
        # When set, the next matching call rejects (then the slot is cleared).
        self.next_order_reject: dict[str, Any] | None = None
        self.next_close_reject: dict[str, Any] | None = None
        # Optional open positions reported by GET openPositions.
        self.open_positions: list[dict[str, Any]] = []

    # --- configuration helpers ---

    def set_price(self, instrument: str, bid: float, ask: float) -> None:
        self._prices[instrument] = (bid, ask)

    def _price(self, instrument: str) -> tuple[float, float]:
        return self._prices.get(instrument, (100.0, 100.02))

    def _next_txid(self) -> str:
        self._txid += 1
        return str(self._txid)

    # --- OandaTransport protocol ---

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        params = kwargs.get("params") or {}
        body = kwargs.get("json") or {}
        self.requests.append({"method": method, "path": path, "params": params, "json": body})

        if path.endswith("/summary"):
            return {"account": self._account()}
        if path.endswith("/instruments"):
            return {"instruments": self._instruments(params)}
        if path.endswith("/pricing"):
            return {"prices": [self._price_payload(params)]}
        if path.endswith("/candles"):
            return {"candles": self._candles(path)}
        if path.endswith("/openPositions"):
            return {"positions": list(self.open_positions)}
        if method == "POST" and path.endswith("/orders"):
            return self._place_order(body)
        if method == "PUT" and "/positions/" in path and path.endswith("/close"):
            return self._close(path, body)
        if method == "PUT" and path.endswith("/cancel"):
            return self._cancel()
        if method == "GET" and "/v3/accounts/" in path:
            # account base (connect ping / get_account_balance)
            return {"account": self._account()}
        raise OandaError(404, {"message": f"FakeOandaTransport: unhandled {method} {path}"})

    # --- response builders ---

    def _account(self) -> dict[str, Any]:
        return {
            "id": "fake-account",
            "currency": self._account_currency,
            "balance": str(self._balance),
            "openTradeCount": len(self.open_positions),
            "openPositionCount": len(self.open_positions),
            "pendingOrderCount": 0,
        }

    @staticmethod
    def _instruments(params: dict[str, Any]) -> list[dict[str, Any]]:
        names_raw = params.get("instruments", "USD_JPY")
        names = [n for n in str(names_raw).split(",") if n]
        out: list[dict[str, Any]] = []
        for name in names:
            jpy = name.endswith("_JPY")
            out.append({
                "name": name,
                "type": "CURRENCY",
                "pipLocation": -2 if jpy else -4,
                "displayPrecision": 3 if jpy else 5,
                "tradeUnitsPrecision": 0,
                "minimumTradeSize": "1",
                "marginRate": "0.04",
            })
        return out

    def _price_payload(self, params: dict[str, Any]) -> dict[str, Any]:
        instrument = str(params.get("instruments", "USD_JPY")).split(",")[0]
        bid, ask = self._price(instrument)
        return {
            "instrument": instrument,
            "time": _FIXED_TIME,
            "bids": [{"price": str(bid), "liquidity": 1_000_000}],
            "asks": [{"price": str(ask), "liquidity": 1_000_000}],
            "closeoutBid": str(bid),
            "closeoutAsk": str(ask),
        }

    def _candles(self, path: str) -> list[dict[str, Any]]:
        # path: /v3/instruments/{instrument}/candles
        instrument = path.split("/v3/instruments/")[1].split("/candles")[0]
        bid, ask = self._price(instrument)
        mid = (bid + ask) / 2
        return [
            {
                "time": _FIXED_TIME,
                "volume": 100,
                "complete": True,
                "mid": {
                    "o": str(mid), "h": str(mid + 0.1),
                    "l": str(mid - 0.1), "c": str(mid),
                },
            }
        ]

    def _place_order(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.next_order_reject is not None:
            reject = self.next_order_reject
            self.next_order_reject = None
            raise OandaError(400, reject)

        order = body.get("order", {})
        instrument = order.get("instrument", "USD_JPY")
        units_str = str(order.get("units", "0"))
        is_buy = not units_str.startswith("-")
        bid, ask = self._price(instrument)
        fill_price = ask if is_buy else bid

        create_id = self._next_txid()
        fill_id = self._next_txid()
        create_txn: dict[str, Any] = {"id": create_id, "type": "MARKET_ORDER"}
        if "clientExtensions" in order:
            create_txn["clientExtensions"] = order["clientExtensions"]
        fill_txn = {
            "id": fill_id,
            "type": "ORDER_FILL",
            "orderID": create_id,
            "instrument": instrument,
            "units": units_str,
            "price": str(fill_price),
            "pl": "0.0",
            "time": _FIXED_TIME,
        }
        return {
            "orderCreateTransaction": create_txn,
            "orderFillTransaction": fill_txn,
            "relatedTransactionIDs": [create_id, fill_id],
            "lastTransactionID": fill_id,
        }

    def _close(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.next_close_reject is not None:
            reject = self.next_close_reject
            self.next_close_reject = None
            raise OandaError(400, reject)

        instrument = path.split("/positions/")[1].split("/close")[0]
        bid, ask = self._price(instrument)
        txid = self._next_txid()
        result: dict[str, Any] = {
            "relatedTransactionIDs": [txid],
            "lastTransactionID": txid,
        }
        if "longUnits" in body:
            result["longOrderFillTransaction"] = {
                "id": txid,
                "type": "ORDER_FILL",
                "instrument": instrument,
                "units": "-1000",
                "price": str(bid),
                "pl": "1234.0",
                "time": _FIXED_TIME,
            }
        if "shortUnits" in body:
            result["shortOrderFillTransaction"] = {
                "id": txid,
                "type": "ORDER_FILL",
                "instrument": instrument,
                "units": "1000",
                "price": str(ask),
                "pl": "-56.0",
                "time": _FIXED_TIME,
            }
        return result

    def _cancel(self) -> dict[str, Any]:
        txid = self._next_txid()
        return {
            "orderCancelTransaction": {"id": txid, "reason": "CLIENT_REQUEST"},
            "lastTransactionID": txid,
            "relatedTransactionIDs": [txid],
        }


def order_reject_body(reason: str = "STOP_LOSS_ON_FILL_LOSS") -> dict[str, Any]:
    """An OANDA-shaped order reject body (HTTP 400)."""
    return {
        "orderRejectTransaction": {
            "id": "999",
            "type": "MARKET_ORDER_REJECT",
            "rejectReason": reason,
        },
        "errorCode": reason,
        "errorMessage": f"The order was rejected: {reason}",
        "lastTransactionID": "999",
        "relatedTransactionIDs": ["999"],
    }


def close_reject_body(reason: str = "CLOSEOUT_POSITION_REJECT") -> dict[str, Any]:
    """An OANDA-shaped position-close reject body (HTTP 400)."""
    return {
        "errorCode": reason,
        "errorMessage": f"The position close was rejected: {reason}",
        "lastTransactionID": "999",
    }
