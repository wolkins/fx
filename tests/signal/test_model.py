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
    assert signal.id != ""


def test_signal_has_auto_id() -> None:
    s1 = Signal(action=SignalAction.HOLD, instrument="USD_JPY", strategy_id="t")
    s2 = Signal(action=SignalAction.HOLD, instrument="USD_JPY", strategy_id="t")
    assert s1.id != s2.id


def test_signal_custom_id() -> None:
    signal = Signal(
        action=SignalAction.BUY,
        instrument="USD_JPY",
        strategy_id="t",
        id="my-signal-001",
    )
    assert signal.id == "my-signal-001"


def test_signal_reason() -> None:
    signal = Signal(
        action=SignalAction.HOLD,
        instrument="USD_JPY",
        strategy_id="t",
        reason="insufficient_data",
    )
    assert signal.reason == "insufficient_data"


def test_signal_reverse() -> None:
    signal = Signal(
        action=SignalAction.REVERSE_TO_BUY,
        instrument="USD_JPY",
        strategy_id="test",
    )
    assert signal.action == SignalAction.REVERSE_TO_BUY
