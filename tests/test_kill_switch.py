from conftest import append_bars
from src.models import Signal

FLAT = 1.1000
BUY = Signal("EURUSD", "BUY", sl=1.0950, tp=1.1100, reason="test buy")


def flat(i):
    return (i, FLAT, FLAT + 0.0005, FLAT - 0.0005, FLAT)


def _with_open_position(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1)])
    r = paper({1: BUY})
    r.start()
    append_bars(paper.dir, "EURUSD", [flat(2)])
    r.cycle()
    assert len(r.broker.positions()) == 1
    return r


def test_stop_file_closes_all_and_exits_3(paper):
    r = _with_open_position(paper)
    paper.stop.touch()
    assert r.run(max_cycles=5) == 3  # restart path: start() restores, first cycle kills
    assert r.broker.positions() == []
    assert r.storage.load_state()["positions"] == []
    [t] = r.storage.trades()
    assert t["exit_reason"] == "KILL"
    assert r.storage.events("kill")[0][3] == "stop_file"
    assert "kill" in r.notifier.names()


def test_stop_file_checked_even_without_new_bars(paper):
    r = _with_open_position(paper)
    paper.stop.touch()
    assert r.cycle() is False  # no new bar appended
    assert r.broker.positions() == []


def test_stop_file_at_startup_no_trading(paper):
    append_bars(paper.dir, "EURUSD", [flat(0), flat(1), flat(2)])
    paper.stop.touch()
    r = paper({1: BUY, 2: BUY})
    assert r.run(max_cycles=5) == 3
    assert r.storage.trades() == [] and r.broker.positions() == []


def test_repeated_errors_trigger_kill(paper):
    append_bars(paper.dir, "EURUSD", [flat(0)])
    r = paper(max_consecutive_errors=3)
    r.start()
    with open(paper.dir / "EURUSD_M15.csv", "a") as f:
        f.write("garbage,row\n")  # every poll now fails
    r.start = lambda: None
    assert r.run(max_cycles=10) == 3
    assert len(r.storage.events("error")) == 3
    assert r.storage.events("kill")[0][3] == "errors"
    assert r.notifier.names().count("error") == 3


def test_kill_continues_when_one_close_fails(paper):
    r = _with_open_position(paper)
    r.broker._positions["99"] = r.broker.positions()[0].__class__(
        **{**{f: getattr(r.broker.positions()[0], f) for f in r.broker.positions()[0].__slots__},
           "id": "99", "symbol": "GBPUSD"})  # no quote -> close fails
    r.kill("manual")
    assert [p.id for p in r.broker.positions()] == ["99"]  # EURUSD closed regardless
    assert "error" in r.notifier.names() and "kill" in r.notifier.names()
