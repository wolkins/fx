from __future__ import annotations

from fx.audit.logger import InMemoryTradeLogger
from fx.backtest.data import BacktestCandle
from fx.backtest.metrics import (
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_total_return,
    calculate_win_rate,
)
from fx.backtest.result import BacktestResult, BacktestTrade
from fx.broker.base import OrderSide, Tick, TradeClose
from fx.broker.paper import PaperBroker
from fx.execution.executor import OrderExecutor
from fx.execution.manager import TradeManager
from fx.risk.config import RiskConfig
from fx.risk.manager import RiskManager
from fx.strategy.base import Strategy


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        initial_balance: float = 1_000_000.0,
        risk_config: RiskConfig | None = None,
        spread: float = 0.02,
        close_on_finish: bool = True,
    ) -> None:
        self._strategy = strategy
        self._initial_balance = initial_balance
        self._risk_config = risk_config or RiskConfig()
        self._spread = spread
        self._close_on_finish = close_on_finish

    async def run(self, candles: list[BacktestCandle]) -> BacktestResult:
        broker = PaperBroker(initial_balance=self._initial_balance)
        logger = InMemoryTradeLogger()
        risk = RiskManager(self._risk_config, logger)
        executor = OrderExecutor(broker, logger, raise_on_error=False)
        manager = TradeManager(risk, executor, logger)

        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        prices: list[float] = []
        daily_pnl = 0.0

        for candle in candles:
            prices.append(candle.close)

            tick = self._candle_to_tick(candle)
            filled_orders, trade_closes = broker.process_tick(tick)

            for tc in trade_closes:
                trades.append(self._to_backtest_trade(tc, self._strategy.strategy_id))
                daily_pnl += tc.pnl
                self._log_trade_close(logger, tc)

            signal = self._strategy.on_bar(list(prices))

            positions = await broker.get_positions()
            balance = await broker.get_account_balance()

            exec_results = await manager.process_signal(
                signal, positions, balance, daily_pnl
            )

            for er in exec_results:
                if er.trade_close is not None:
                    trades.append(self._to_backtest_trade(
                        er.trade_close, self._strategy.strategy_id
                    ))
                    daily_pnl += er.trade_close.pnl

            equity = await self._calculate_equity(broker, tick)
            equity_curve.append(equity)

        if self._close_on_finish:
            positions = await broker.get_positions()
            if positions and candles:
                for pos in positions:
                    result = await broker.close_position(pos.instrument, side=pos.side)
                    if result is not None:
                        trades.append(self._to_backtest_trade(
                            result, self._strategy.strategy_id
                        ))
                        self._log_trade_close(logger, result)

        final_balance = await broker.get_account_balance()
        total_pnl = final_balance - self._initial_balance
        win_count = sum(1 for t in trades if t.pnl > 0)
        loss_count = sum(1 for t in trades if t.pnl < 0)

        return BacktestResult(
            initial_balance=self._initial_balance,
            final_balance=final_balance,
            total_pnl=total_pnl,
            total_return=calculate_total_return(self._initial_balance, final_balance),
            max_drawdown=calculate_max_drawdown(equity_curve),
            trade_count=len(trades),
            win_count=win_count,
            loss_count=loss_count,
            win_rate=calculate_win_rate(trades),
            profit_factor=calculate_profit_factor(trades),
            trades=trades,
            equity_curve=equity_curve,
            audit_events=logger.get_events(),
            orders=broker.get_all_orders(),
        )

    def _candle_to_tick(self, candle: BacktestCandle) -> Tick:
        half_spread = self._spread / 2
        return Tick(
            instrument=candle.instrument,
            bid=candle.close - half_spread,
            ask=candle.close + half_spread,
            timestamp=candle.timestamp,
        )

    @staticmethod
    def _to_backtest_trade(tc: TradeClose, strategy_id: str = "") -> BacktestTrade:
        return BacktestTrade(
            instrument=tc.instrument,
            side=tc.side.value,
            units=tc.units,
            entry_price=tc.entry_price,
            exit_price=tc.close_price,
            pnl=tc.pnl,
            closed_at=tc.closed_at,
            reason=tc.reason,
            strategy_id=strategy_id,
        )

    @staticmethod
    def _log_trade_close(logger: InMemoryTradeLogger, tc: TradeClose) -> None:
        if tc.reason == "stop_loss":
            logger.log_sl_triggered(
                tc.instrument, tc.side.value, tc.units, tc.close_price, tc.pnl
            )
        elif tc.reason == "take_profit":
            logger.log_tp_triggered(
                tc.instrument, tc.side.value, tc.units, tc.close_price, tc.pnl
            )
        logger.log_trade_closed(
            tc.instrument, tc.side.value, tc.units, tc.close_price, tc.pnl, tc.reason
        )

    @staticmethod
    async def _calculate_equity(broker: PaperBroker, tick: Tick) -> float:
        balance = await broker.get_account_balance()
        positions = await broker.get_positions()
        unrealized = 0.0
        for pos in positions:
            if pos.instrument == tick.instrument:
                if pos.side == OrderSide.BUY:
                    unrealized += (tick.bid - pos.avg_price) * pos.units
                else:
                    unrealized += (pos.avg_price - tick.ask) * pos.units
        return balance + unrealized
