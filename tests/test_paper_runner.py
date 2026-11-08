import dataclasses
import os
import signal
import threading

from conftest import append_bars, bar_time
from src.main import run_paper
from src.models import Signal
from src.storage.db import Storage

FLAT = 1.1000
BUY = Signal("EURUSD", "BUY", sl=1.0950, tp=1.1100, reason="test buy")


def flat(i):
    return (i, FLAT, FLAT + 0.0005, FLAT - 0.0005, FLAT)


def test_fresh_start_only_warms_up_on_existing_bars(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    r = paper({0: BUY})  # signal on an old bar, superseded by bar 1's (no) signal
    r.start()
    assert r.cycle() and r.broker.positions() == []
    append_bars(paper.dir, "EURUSD", [flat(2)])
    assert r.cycle() and r.broker.positions() == []
    assert r.last_bars["EURUSD"] == bar_time(2)


def test_signal_on_last_bar_executes_on_next_bar_open(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    r = paper({1: BUY})
    r.start()
    r.cycle()
    assert r.broker.positions() == []  # waits for the next bar's open
    append_bars(paper.dir, "EURUSD", [flat(2)])
    r.cycle()
    [p] = r.broker.positions()
    assert p.open_time == bar_time(2) and p.side == "BUY" and p.lots > 0
    assert "entry" in r.notifier.names()


def test_restart_restores_balance_positions_and_continues(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    r1 = paper({1: BUY})
    r1.start()
    append_bars(paper.dir, "EURUSD", [flat(2)])
    r1.cycle()
    pos_before = [dataclasses.asdict(p) for p in r1.broker.positions()]
    bal_before, day_eq = r1.broker.balance, r1.risk.day_start_equity
    r1.storage.close()  # "crash"

    r2 = paper({1: BUY})
    r2.start()
    assert [dataclasses.asdict(p) for p in r2.broker.positions()] == pos_before
    assert r2.broker.balance == bal_before and r2.risk.day_start_equity == day_eq
    assert r2.pending == {}  # bar 1's signal was already executed, must not re-open

    append_bars(paper.dir, "EURUSD", [(3, FLAT, FLAT, 1.0940, 1.0960)])  # hits SL 1.0950
    r2.cycle()
    assert r2.broker.positions() == []
    [t] = r2.storage.trades()
    assert t["exit_reason"] == "SL" and t["net_pnl"] < 0
    assert r2.storage.load_state()["positions"] == []
    assert "exit" in r2.notifier.names()


def test_bars_missed_while_down_are_processed_on_restart(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    r1 = paper({1: BUY})
    r1.start()
    append_bars(paper.dir, "EURUSD", [flat(2)])
    r1.cycle()
    r1.storage.close()
    append_bars(paper.dir, "EURUSD", [(3, FLAT, 1.1110, FLAT, 1.1105)])  # TP 1.1100 hit while bot was off
    r2 = paper({1: BUY})
    r2.start()
    r2.cycle()
    [t] = r2.storage.trades()
    assert t["exit_reason"] == "TP" and t["exit_price"] == 1.1100


def test_trailing_stop_ratchets_sl(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    r = paper({1: BUY}, trailing_stop_r=1.0)
    r.start()
    append_bars(paper.dir, "EURUSD", [flat(2)])
    r.cycle()
    [p] = r.broker.positions()
    sl0, dist = p.sl, p.entry_price - p.sl
    append_bars(paper.dir, "EURUSD", [(3, FLAT, 1.1035, FLAT, 1.1030)])
    r.cycle()
    assert p.sl == round(1.1030 - dist, 5) > sl0
    append_bars(paper.dir, "EURUSD", [(4, 1.1030, 1.1030, 1.1020, 1.1020)])  # pullback: SL must not loosen
    r.cycle()
    assert p.sl == round(1.1030 - dist, 5)
    assert r.storage.load_state()["positions"][0].sl == p.sl


def test_daily_lock_alert_once(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    r = paper({1: BUY}, risk_per_trade_pct=5.0)
    r.start()
    append_bars(paper.dir, "EURUSD", [flat(2), (3, FLAT, FLAT, 1.0900, 1.0920), flat(4)])
    r.cycle()
    assert r.risk.daily_locked
    assert r.notifier.names().count("daily_lock") == 1
    assert len(r.storage.events("daily_lock")) == 1


def test_sigterm_graceful_shutdown_keeps_state(paper, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    cfg = dataclasses.replace(paper.cfg, paper=dataclasses.replace(paper.cfg.paper, poll_seconds=0.05))
    threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGTERM)).start()
    assert run_paper(cfg, max_cycles=200) == 0
    s = Storage(cfg.paper.db)
    assert [e[2] for e in s.events()][-1] == "stop"
    assert s.load_state()["balance"] == cfg.account.initial_balance
    s.close()
