from datetime import datetime, timedelta, timezone

import pytest

from src.models import AccountInfo, Order, Position, Rejection, Signal
from src.risk.risk_manager import RiskManager

NOW = datetime(2025, 1, 6, 10, tzinfo=timezone.utc)


def acc(equity=1000.0):
    return AccountInfo(equity, equity, 0.0, 0.0)


def pos(symbol="EURUSD"):
    return Position("1", symbol, "BUY", 0.01, 1.1, 1.09, None, NOW, 1.0, "x")


@pytest.fixture
def rm(cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # STOP file is relative to cwd
    return RiskManager(cfg.risk)


# --- lot sizing ---------------------------------------------------------------
def test_pip_value_per_lot(eurusd, xauusd):
    assert eurusd.pip_value_per_lot == pytest.approx(10.0)
    assert xauusd.pip_value_per_lot == pytest.approx(10.0)


def test_lot_eurusd_20_pips(rm, eurusd):
    assert rm.lot_size(1000, 0.0020, eurusd) == 0.05


def test_lot_floors_to_volume_step(rm, eurusd):
    assert rm.lot_size(1000, 0.0030, eurusd) == 0.03  # 0.0333 -> 0.03, never rounds up


def test_lot_below_min_is_skipped(rm, xauusd):
    assert rm.lot_size(1000, 15.0, xauusd) == 0.0  # 0.0066 lots < 0.01


def test_lot_clamped_to_volume_max(rm, eurusd):
    assert rm.lot_size(10_000_000, 0.0001, eurusd) == eurusd.volume_max


def test_lot_zero_sl_distance(rm, eurusd):
    assert rm.lot_size(1000, 0.0, eurusd) == 0.0


# --- evaluate -----------------------------------------------------------------
def ev(rm, spec, sig, bid=1.10000, ask=1.10010, spread=10, positions=(), equity=1000.0):
    return rm.evaluate(sig, spec, bid, ask, spread, acc(equity), list(positions), NOW)


def test_valid_signal_becomes_order(rm, eurusd):
    o = ev(rm, eurusd, Signal("EURUSD", "BUY", sl=1.09810, tp=1.10410, reason="x"))
    assert isinstance(o, Order) and o.lots == 0.05 and o.sl == 1.09810


def test_signal_without_sl_rejected(rm, eurusd):
    r = ev(rm, eurusd, Signal("EURUSD", "BUY", sl=None, reason="x"))
    assert isinstance(r, Rejection) and "SL" in r.reason


@pytest.mark.parametrize("side,sl", [("BUY", 1.10100), ("SELL", 1.09900)])
def test_sl_on_wrong_side_rejected(rm, eurusd, side, sl):
    assert isinstance(ev(rm, eurusd, Signal("EURUSD", side, sl=sl, reason="x")), Rejection)


def test_signal_requires_reason():
    with pytest.raises(ValueError):
        Signal("EURUSD", "BUY", sl=1.0, reason="")


def test_max_open_positions(rm, eurusd):
    r = ev(rm, eurusd, Signal("EURUSD", "BUY", sl=1.098, reason="x"), positions=[pos(), pos("XAUUSD")])
    assert r == Rejection("max open positions")


def test_spread_too_wide(rm, eurusd):
    r = ev(rm, eurusd, Signal("EURUSD", "BUY", sl=1.098, reason="x"), spread=31)
    assert isinstance(r, Rejection) and "spread" in r.reason


def test_daily_loss_limit_locks_until_next_day(rm, eurusd):
    sig = Signal("EURUSD", "BUY", sl=1.098, reason="x")
    rm.update(1000, NOW)
    rm.update(971, NOW + timedelta(hours=1))  # -2.9%
    assert not rm.daily_locked
    rm.update(970, NOW + timedelta(hours=2))  # -3.0%
    assert rm.daily_locked
    assert ev(rm, eurusd, sig) == Rejection("daily loss limit reached")
    rm.update(990, NOW + timedelta(hours=3))  # recovery same day keeps the lock
    assert rm.daily_locked
    rm.update(990, NOW + timedelta(days=1))
    assert not rm.daily_locked and rm.day_start_equity == 990
    assert isinstance(ev(rm, eurusd, sig), Order)


def test_kill_switch_stop_file(rm, eurusd, tmp_path):
    assert rm.check_kill() is None
    (tmp_path / "STOP").touch()
    assert rm.check_kill() == "stop_file"
    r = ev(rm, eurusd, Signal("EURUSD", "BUY", sl=1.098, reason="x"))
    assert isinstance(r, Rejection) and "kill" in r.reason


def test_kill_switch_consecutive_errors(rm):
    for _ in range(rm.cfg.max_consecutive_errors - 1):
        rm.record_error()
    rm.record_success()
    for _ in range(rm.cfg.max_consecutive_errors - 1):
        rm.record_error()
    assert rm.check_kill() is None
    rm.record_error()
    assert rm.check_kill() == "errors"
