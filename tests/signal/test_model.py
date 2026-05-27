from fx.signal.model import Signal, SignalAction


def test_signal_creation() -> None:
    signal = Signal(
        action=SignalAction.BUY,
        instrument="USD_JPY",
        strategy_id="ema_cross_12_26",
        stop_loss=149.50,
        take_profit=151.00,
        units=1000,
    )
    assert signal.action == SignalAction.BUY
    assert signal.instrument == "USD_JPY"
    assert signal.stop_loss == 149.50
    assert signal.units == 1000


def test_signal_hold() -> None:
    signal = Signal(
        action=SignalAction.HOLD,
        instrument="USD_JPY",
        strategy_id="test",
    )
    assert signal.action == SignalAction.HOLD
    assert signal.confidence == 0.0


def test_signal_reverse() -> None:
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY,
        instrument="USD_JPY",
        strategy_id="test",
    )
    assert signal.action == SignalAction.REVERSE_TO_BUY
