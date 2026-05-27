from __future__ import annotations

from datetime import datetime, timezone

from fx.audit.logger import TradeLogger
from fx.broker.base import Order, Position
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

        checks: list[RiskDecision] = [
            self._check_position_size(order),
            self._check_open_positions(order, positions),
            self._check_daily_loss(daily_pnl, account_balance),
            self._check_duplicate(order),
        ]

        for decision in checks:
            if not decision.allowed:
                self._logger.log_risk_rejected(
                    order,
                    reason_code=decision.code or "UNKNOWN",
                    message=decision.reason or "Risk check failed",
                    strategy_id=strategy_id,
                )
                return decision

        self._record_order(order)
        self._logger.log_risk_accepted(order, strategy_id=strategy_id)
        return RiskDecision(allowed=True)

    def _check_position_size(self, order: Order) -> RiskDecision:
        if order.units > self._config.max_position_size:
            return RiskDecision(
                allowed=False,
                code="MAX_POSITION_SIZE_EXCEEDED",
                reason=f"Order size {order.units} exceeds max {self._config.max_position_size}",
                details={
                    "order_units": order.units,
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
                reason="Account balance is zero or negative",
            )
        loss_ratio = abs(min(daily_pnl, 0.0)) / account_balance
        if loss_ratio >= self._config.max_daily_loss:
            return RiskDecision(
                allowed=False,
                code="MAX_DAILY_LOSS_EXCEEDED",
                reason=f"Daily loss {loss_ratio:.4f} >= max {self._config.max_daily_loss}",
                details={
                    "daily_pnl": daily_pnl,
                    "loss_ratio": loss_ratio,
                    "max_daily_loss": self._config.max_daily_loss,
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
                    reason=f"Duplicate order within {self._config.duplicate_window_seconds}s",
                    details={"order_key": order_key},
                )
        return RiskDecision(allowed=True)

    def _record_order(self, order: Order) -> None:
        now = datetime.now(tz=timezone.utc).timestamp()
        self._recent_orders.append((now, self._make_order_key(order)))

    @staticmethod
    def _make_order_key(order: Order) -> str:
        return f"{order.instrument}:{order.side.value}:{order.order_type.value}:{order.units}"
