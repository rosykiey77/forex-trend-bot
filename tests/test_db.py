import dataclasses
from datetime import date, datetime, timezone

import pytest

from src.models import Position, Trade
from src.storage.db import Storage

T = datetime(2025, 1, 6, 10, 15, tzinfo=timezone.utc)


def pos(id="1", **kw):
    return Position(id, "EURUSD", "BUY", 0.02, 1.1001, 1.0950, 1.1100, T, 10.2, "why",
                    commission=-0.14, slippage_cost=0.04, floating_pnl=-1.5, **kw)


class Risk:
    day, day_start_equity, daily_locked = date(2025, 1, 6), 1000.0, True


@pytest.fixture
def db(tmp_path):
    s = Storage(tmp_path / "sub" / "t.db")
    yield s
    s.close()


def test_fresh_db_has_no_state(db):
    assert db.load_state() is None


def test_state_roundtrip_survives_reopen(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.save(990.5, [pos("1"), pos("2", swap=-0.3)], [], Risk, (T, 987.0), {"EURUSD": T})
    s.close()
    st = Storage(tmp_path / "t.db").load_state()
    assert st["balance"] == 990.5
    assert st["positions"] == [pos("1"), pos("2", swap=-0.3)]
    assert (st["day"], st["day_start_equity"], st["daily_locked"]) == (date(2025, 1, 6), 1000.0, True)
    assert st["last_bars"] == {"EURUSD": T}


def test_close_moves_position_to_trades(db):
    p = pos()
    db.save(1000, [p], [])
    db.save(1009.8, [], [Trade(p, 1.1100, T, "TP", 19.8, 19.66, 1.93)])
    assert db.load_state()["positions"] == [] and db.load_state()["balance"] == 1009.8
    [t] = db.trades()
    assert (t["position_id"], t["symbol"], t["exit_reason"], t["net_pnl"], t["commission"], t["slippage_cost"]) == \
           ("1", "EURUSD", "TP", 19.66, -0.14, 0.04)
    assert t["mode"] == "paper" and t["open_time"] == T.isoformat()


def test_failed_save_rolls_back(db):
    db.save(1000, [pos()], [])
    bad = Trade(dataclasses.replace(pos(), open_time=None), 1.11, T, "TP", 1, 1, 1)
    with pytest.raises(AttributeError):
        db.save(1500, [], [bad])
    st = db.load_state()
    assert st["balance"] == 1000 and len(st["positions"]) == 1 and db.trades() == []


def test_equity_snapshots_and_events(db):
    db.save(1000, [], [], equity=(T, 1000.0))
    db.save(1000, [], [], equity=(T, 1001.0))  # same bar time twice -> replaced, not duplicated
    assert db.conn.execute("SELECT equity FROM equity").fetchall() == [(1001.0,)]
    db.log_event("kill", "stop_file", "WARNING")
    db.log_event("error", "x", "ERROR")
    assert [e[2:] for e in db.events()] == [("kill", "stop_file"), ("error", "x")]
    assert len(db.events("kill")) == 1


def test_meta(db):
    assert db.get_meta("x") is None
    db.set_meta("x", "1")
    db.set_meta("x", "2")
    assert db.get_meta("x") == "2"
