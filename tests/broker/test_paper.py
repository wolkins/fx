from datetime import datetime, timezone

import pytest

from fx.broker.base import (
    BrokerEnvironment,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Tick,
)
from fx.broker.paper import PaperBroker


@pytest.fixture
def broker() -> PaperBroker:
    b = PaperBroker(initial_balance=1_000_000.0)
    b.inject_tick(
        Tick(instrument="USD_JPY", bid=150.00, ask=150.02, timestamp=datetime.now(tz=timezone.utc))
    )
    return b


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def test_environment(broker: PaperBroker) -> None:
    assert broker.environment == BrokerEnvironment.PRACTICE
    assert broker.name == "paper"


async def test_capabilities(broker: PaperBroker) -> None:
    caps = broker.capabilities
    assert caps.supports_market_order is True
    assert caps.supports_stop_order is True
    assert caps.supports_demo is True
    assert caps.min_trade_units == 1


async def test_connect_disconnect(broker: PaperBroker) -> None:
    await broker.connect()
    await broker.disconnect()


async def test_async_context_manager(broker: PaperBroker) -> None:
    async with broker:
        tick = await broker.get_tick("USD_JPY")
        assert tick.bid == 150.00


async def test_get_tick(broker: PaperBroker) -> None:
    tick = await broker.get_tick("USD_JPY")
    assert tick.bid == 150.00
    assert tick.ask == 150.02
    assert tick.spread == pytest.approx(0.02)


async def test_get_tick_missing(broker: PaperBroker) -> None:
    with pytest.raises(KeyError):
        await broker.get_tick("EUR_USD")


async def test_market_buy(broker: PaperBroker) -> None:
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    )
    result = await broker.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_price == 150.02
    assert result.id != ""

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].units == 1000
    assert positions[0].side == OrderSide.BUY


async def test_market_sell(broker: PaperBroker) -> None:
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=500,
    )
    result = await broker.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_price == 150.00


async def test_close_position(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    closed = await broker.close_position("USD_JPY")
    assert closed is True
    positions = await broker.get_positions()
    assert len(positions) == 0


async def test_close_position_with_matching_side(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    closed = await broker.close_position("USD_JPY", side=OrderSide.BUY)
    assert closed is True


async def test_close_position_with_wrong_side(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    closed = await broker.close_position("USD_JPY", side=OrderSide.SELL)
    assert closed is False


async def test_close_nonexistent_position(broker: PaperBroker) -> None:
    closed = await broker.close_position("EUR_USD")
    assert closed is False


async def test_limit_order_stays_pending(broker: PaperBroker) -> None:
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, units=1000, price=149.50,
    )
    result = await broker.place_order(order)
    assert result.status == OrderStatus.PENDING
    open_orders = await broker.get_open_orders()
    assert len(open_orders) == 1


async def test_cancel_order(broker: PaperBroker) -> None:
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, units=1000, price=149.50,
    )
    result = await broker.place_order(order)
    cancelled = await broker.cancel_order(result.id)
    assert cancelled is True
    open_orders = await broker.get_open_orders()
    assert len(open_orders) == 0


async def test_balance(broker: PaperBroker) -> None:
    balance = await broker.get_account_balance()
    assert balance == 1_000_000.0


async def test_get_order(broker: PaperBroker) -> None:
    order = Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=100,
    )
    result = await broker.place_order(order)
    fetched = await broker.get_order(result.id)
    assert fetched.id == result.id


async def test_close_position_updates_balance(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    broker.inject_tick(
        Tick(instrument="USD_JPY", bid=151.00, ask=151.02, timestamp=_now())
    )
    await broker.close_position("USD_JPY")
    balance = await broker.get_account_balance()
    assert balance == pytest.approx(1_000_980.0)


async def test_opposite_order_partial_close(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=400,
    ))
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].units == 600
    assert positions[0].side == OrderSide.BUY


async def test_opposite_order_full_close(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1000,
    ))
    positions = await broker.get_positions()
    assert len(positions) == 0


async def test_opposite_order_reversal(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1500,
    ))
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].units == 500
    assert positions[0].side == OrderSide.SELL


async def test_opposite_order_pnl(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1000,
    ))
    balance = await broker.get_account_balance()
    assert balance == pytest.approx(1_000_000.0 - 20.0)


# --- process_tick: pending order tests ---


async def test_process_tick_limit_buy_triggers(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, units=1000, price=149.80,
    ))
    filled, closes = broker.process_tick(
        Tick(instrument="USD_JPY", bid=149.78, ask=149.80, timestamp=_now())
    )
    assert len(filled) == 1
    assert filled[0].status == OrderStatus.FILLED
    assert filled[0].filled_price == 149.80
    assert len(closes) == 0


async def test_process_tick_limit_buy_not_triggered(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, units=1000, price=149.80,
    ))
    filled, _ = broker.process_tick(
        Tick(instrument="USD_JPY", bid=149.90, ask=149.92, timestamp=_now())
    )
    assert len(filled) == 0


async def test_process_tick_limit_sell_triggers(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.LIMIT, units=1000, price=150.50,
    ))
    filled, _ = broker.process_tick(
        Tick(instrument="USD_JPY", bid=150.50, ask=150.52, timestamp=_now())
    )
    assert len(filled) == 1
    assert filled[0].filled_price == 150.50


async def test_process_tick_stop_buy_triggers(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.STOP, units=1000, price=150.50,
    ))
    filled, _ = broker.process_tick(
        Tick(instrument="USD_JPY", bid=150.48, ask=150.50, timestamp=_now())
    )
    assert len(filled) == 1
    assert filled[0].status == OrderStatus.FILLED


async def test_process_tick_stop_sell_triggers(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.STOP, units=1000, price=149.50,
    ))
    filled, _ = broker.process_tick(
        Tick(instrument="USD_JPY", bid=149.50, ask=149.52, timestamp=_now())
    )
    assert len(filled) == 1


async def test_process_tick_updates_position(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, units=500, price=149.80,
    ))
    broker.process_tick(
        Tick(instrument="USD_JPY", bid=149.78, ask=149.80, timestamp=_now())
    )
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].units == 500
    assert positions[0].side == OrderSide.BUY


async def test_process_tick_ignores_other_instruments(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, units=1000, price=149.80,
    ))
    filled, _ = broker.process_tick(
        Tick(instrument="EUR_USD", bid=1.0800, ask=1.0802, timestamp=_now())
    )
    assert len(filled) == 0


# --- process_tick: SL/TP tests ---


async def test_stop_loss_buy_position(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
        stop_loss=149.50, take_profit=151.00,
    ))
    _, closes = broker.process_tick(
        Tick(instrument="USD_JPY", bid=149.50, ask=149.52, timestamp=_now())
    )
    assert len(closes) == 1
    assert closes[0].reason == "stop_loss"
    assert closes[0].close_price == 149.50
    # bought at 150.02, SL at 149.50 → pnl = (149.50 - 150.02) * 1000 = -520
    assert closes[0].pnl == pytest.approx(-520.0)
    positions = await broker.get_positions()
    assert len(positions) == 0


async def test_take_profit_buy_position(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
        stop_loss=149.50, take_profit=151.00,
    ))
    _, closes = broker.process_tick(
        Tick(instrument="USD_JPY", bid=151.00, ask=151.02, timestamp=_now())
    )
    assert len(closes) == 1
    assert closes[0].reason == "take_profit"
    assert closes[0].close_price == 151.00
    # bought at 150.02, TP at 151.00 → pnl = (151.00 - 150.02) * 1000 = 980
    assert closes[0].pnl == pytest.approx(980.0)


async def test_stop_loss_sell_position(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1000,
        stop_loss=150.50, take_profit=149.00,
    ))
    _, closes = broker.process_tick(
        Tick(instrument="USD_JPY", bid=150.48, ask=150.50, timestamp=_now())
    )
    assert len(closes) == 1
    assert closes[0].reason == "stop_loss"
    assert closes[0].close_price == 150.50
    # sold at 150.00, SL at 150.50 → pnl = (150.00 - 150.50) * 1000 = -500
    assert closes[0].pnl == pytest.approx(-500.0)


async def test_take_profit_sell_position(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.SELL,
        order_type=OrderType.MARKET, units=1000,
        stop_loss=150.50, take_profit=149.00,
    ))
    _, closes = broker.process_tick(
        Tick(instrument="USD_JPY", bid=148.98, ask=149.00, timestamp=_now())
    )
    assert len(closes) == 1
    assert closes[0].reason == "take_profit"
    assert closes[0].close_price == 149.00
    # sold at 150.00, TP at 149.00 → pnl = (150.00 - 149.00) * 1000 = 1000
    assert closes[0].pnl == pytest.approx(1000.0)


async def test_sl_tp_updates_balance(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
        stop_loss=149.50, take_profit=151.00,
    ))
    broker.process_tick(
        Tick(instrument="USD_JPY", bid=149.50, ask=149.52, timestamp=_now())
    )
    balance = await broker.get_account_balance()
    assert balance == pytest.approx(1_000_000.0 - 520.0)


async def test_no_sl_tp_no_close(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
    ))
    _, closes = broker.process_tick(
        Tick(instrument="USD_JPY", bid=149.50, ask=149.52, timestamp=_now())
    )
    assert len(closes) == 0
    positions = await broker.get_positions()
    assert len(positions) == 1


async def test_position_preserves_sl_tp(broker: PaperBroker) -> None:
    await broker.place_order(Order(
        id="", instrument="USD_JPY", side=OrderSide.BUY,
        order_type=OrderType.MARKET, units=1000,
        stop_loss=149.50, take_profit=151.00,
    ))
    positions = await broker.get_positions()
    assert positions[0].stop_loss == 149.50
    assert positions[0].take_profit == 151.00
