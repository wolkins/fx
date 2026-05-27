from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fx.audit.logger import TradeLogger
from fx.broker.base import Order, OrderIntent, Position
from fx.risk.config import RiskConfig
from fx.risk.decision import RiskDecision


class RiskManager:
    """Evaluates orders against risk rules. Does not send orders to brokers."""

    def __init__(self, config: RiskConfig, logger: TradeLogger) -> None:
        self._config = config
        self._logger = logger
        self._recent_orders: list[tuple[float, str]] = []

    @property
    def config(self) -> RiskConfig:
        return self._config

    def evaluate(
        self,
        order: Order,
        positions: list[Position],
        account_balance: float,
        daily_pnl: float = 0.0,
        *,
        strategy_id: str | None = None,
    ) -> RiskDecision:
        self._logger.log_order_submitted(order, strategy_id=strategy_id)

        risk_state = self._build_risk_state(positions, account_balance, daily_pnl)

        if order.intent in (OrderIntent.CLOSE, OrderIntent.REDUCE):
            self._logger.log_risk_bypassed(order, strategy_id=strategy_id)
            return RiskDecision(allowed=True, severity="info")

        checks: list[RiskDecision] = [
            self._check_position_size(order, positions),
            self._check_open_positions(order, positions),
            self._check_daily_loss(daily_pnl, account_balance),
            self._check_duplicate(order),
        ]

        for decision in checks:
            if not decision.allowed:
                self._log_rejection(
                    order, decision, risk_state, strategy_id
                )
                return decision

        self._record_order(order)
        self._logger.log_risk_accepted(order, strategy_id=strategy_id, risk_state=risk_state)
        return RiskDecision(allowed=True)

    def _build_risk_state(
        self,
        positions: list[Position],
        account_balance: float,
        daily_pnl: float,
    ) -> dict[str, Any]:
        return {
            "account_balance": account_balance,
            "daily_pnl": daily_pnl,
            "open_positions": len([p for p in positions if p.units > 0]),
            "config": {
                "max_position_size": self._config.max_position_size,
                "max_open_positions": self._config.max_open_positions,
                "max_daily_loss_ratio": self._config.max_daily_loss_ratio,
                "max_daily_loss_amount": self._config.max_daily_loss_amount,
            },
        }

    def _log_rejection(
        self,
        order: Order,
        decision: RiskDecision,
        risk_state: dict[str, Any],
        strategy_id: str | None,
    ) -> None:
        self._logger.log_risk_rejected(
            order,
            reason_code=decision.code or "UNKNOWN",
            message=decision.reason or "Risk check failed",
            strategy_id=strategy_id,
            risk_state=risk_state,
        )

    def _check_position_size(
        self, order: Order, positions: list[Position]
    ) -> RiskDecision:
        existing_units = sum(
            p.units for p in positions
            if p.instrument == order.instrument and p.side == order.side and p.units > 0
        )
        projected = existing_units + order.units
        if projected > self._config.max_position_size:
            return RiskDecision(
                allowed=False,
                code="MAX_POSITION_SIZE_EXCEEDED",
                severity="warning",
                reason=f"Projected size {projected} exceeds max {self._config.max_position_size}",
                details={
                    "order_units": order.units,
                    "existing_units": existing_units,
                    "projected_units": projected,
                    "max_position_size": self._config.max_position_size,
                },
            )
        return RiskDecision(allowed=True)

    def _check_open_positions(
        self, order: Order, positions: list[Position]
    ) -> RiskDecision:
        open_positions = [p for p in positions if p.units > 0]
        has_existing = any(p.instrument == order.instrument for p in open_positions)
        if not has_existing and len(open_positions) >= self._config.max_open_positions:
            return RiskDecision(
                allowed=False,
                code="MAX_OPEN_POSITIONS_EXCEEDED",
                severity="warning",
                reason=f"Open positions {len(open_positions)} >= max {self._config.max_open_positions}",
                details={
                    "open_positions": len(open_positions),
                    "max_open_positions": self._config.max_open_positions,
                },
            )
        return RiskDecision(allowed=True)

    def _check_daily_loss(
        self, daily_pnl: float, account_balance: float
    ) -> RiskDecision:
        if account_balance <= 0:
            return RiskDecision(
                allowed=False,
                code="ZERO_BALANCE",
                severity="critical",
                reason="Account balance is zero or negative",
            )

        if self._config.max_daily_loss_amount is not None:
            loss_limit = self._config.max_daily_loss_amount
        else:
            loss_limit = account_balance * self._config.max_daily_loss_ratio

        actual_loss = abs(min(daily_pnl, 0.0))
        if actual_loss >= loss_limit:
            return RiskDecision(
                allowed=False,
                code="MAX_DAILY_LOSS_EXCEEDED",
                severity="critical",
                reason=f"Daily loss {actual_loss:.2f} >= limit {loss_limit:.2f}",
                details={
                    "daily_pnl": daily_pnl,
                    "actual_loss": actual_loss,
                    "loss_limit": loss_limit,
                    "max_daily_loss_ratio": self._config.max_daily_loss_ratio,
                    "max_daily_loss_amount": self._config.max_daily_loss_amount,
                },
            )
        return RiskDecision(allowed=True)

    def _check_duplicate(self, order: Order) -> RiskDecision:
        now = datetime.now(tz=timezone.utc).timestamp()
        cutoff = now - self._config.duplicate_window_seconds
        self._recent_orders = [
            (ts, key) for ts, key in self._recent_orders if ts > cutoff
        ]
        order_key = self._make_order_key(order)
        for _, key in self._recent_orders:
            if key == order_key:
                return RiskDecision(
                    allowed=False,
                    code="DUPLICATE_ORDER",
                    severity="warning",
                    reason=f"Duplicate order within {self._config.duplicate_window_seconds}s",
                    details={"order_key": order_key},
                )
        return RiskDecision(allowed=True)

    def _record_order(self, order: Order) -> None:
        now = datetime.now(tz=timezone.utc).timestamp()
        self._recent_orders.append((now, self._make_order_key(order)))

    @staticmethod
    def _make_order_key(order: Order) -> str:
        parts = [
            order.instrument,
            order.side.value,
            order.order_type.value,
            str(order.units),
        ]
        if order.client_order_id:
            parts.append(order.client_order_id)
        return ":".join(parts)
