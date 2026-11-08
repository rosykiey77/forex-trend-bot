import dataclasses

import pytest

from src.broker.base import OrderRejected
from src.broker.mt5_broker import GatewayClient, GatewayError, Mt5Broker
from src.data.mt5_feed import Mt5Feed
from src.engine.live_runner import LiveRunner
from src.main import run_live
from src.models import Order, Signal
from src.storage.db import Storage
from tests.conftest import GW_TOKEN, FakeNotifier, ScriptStrategy

MAGIC = 777


@pytest.fixture
def broker(gw, eurusd):
    return Mt5Broker(gw.client, {"EURUSD": eurusd}, MAGIC)


def buy(broker, sl=1.099, tp=1.102, lots=0.1):
    return broker.open(Order("EURUSD", "BUY", lots, sl, tp, "ema cross up"))


def test_account(broker):
    a = broker.account()
    assert (a.balance, a.equity, a.floating_pnl) == (1000.0, 1000.0, 0.0)
    assert broker.balance == 1000.0


def test_open_and_positions(gw, broker):
    p = buy(broker)
    assert (p.side, p.lots, p.entry_price, p.sl, p.tp) == ("BUY", 0.1, 1.1001, 1.099, 1.102)
    assert p.initial_risk == pytest.approx(0.0011 * 100000 * 0.1)
    assert gw.fake.requests[-1]["magic"] == MAGIC
    gw.fake.add_manual_position(magic=0)
    [q] = broker.positions()  # manual position invisible
    assert (q.id, q.entry_reason, q.initial_risk) == (p.id, "ema cross up", p.initial_risk)


def test_open_rejected(gw, broker):
    gw.fake.reject_next = gw.fake.TRADE_RETCODE_INVALID_STOPS
    with pytest.raises(OrderRejected):
        buy(broker)
    with pytest.raises(OrderRejected):
        buy(broker, sl=0)  # gateway's no-SL guard
    assert broker.positions() == []


def test_modify_keeps_r_basis(broker):
    p = buy(broker)
    broker.modify(p.id, 1.1, None)
    [q] = broker.positions()
    assert (q.sl, q.tp) == (1.1, 1.102)
    assert q.initial_risk == p.initial_risk  # not recomputed from the trailed SL


def test_close_uses_deal_history(gw, broker):
    p = buy(broker)
    t = broker.close(p.id, "SIGNAL")
    assert (t.exit_price, t.exit_reason) == (1.1, "SIGNAL")
    assert t.gross_pnl == pytest.approx(-1.0)  # 1 pip spread x 0.1 lot x 100k
    assert t.net_pnl == pytest.approx(-1.0 - 0.7)  # commission 3.5/lot/side
    assert t.r_multiple == pytest.approx(-1.7 / p.initial_risk)
    assert broker.positions() == [] and broker.on_price(None) == []


def test_server_side_sl_and_tp_detected(gw, broker):
    a, b = buy(broker), buy(broker)
    assert broker.on_price(None) == []
    gw.fake.server_close(int(a.id), "sl")
    gw.fake.server_close(int(b.id), "tp")
    trades = {t.position.id: t for t in broker.on_price(None)}
    assert trades[a.id].exit_reason == "SL" and trades[a.id].exit_price == 1.099
    assert trades[a.id].r_multiple == pytest.approx(-1 - 0.7 / a.initial_risk)
    assert trades[b.id].exit_reason == "TP" and trades[b.id].net_pnl > 0
    assert broker.on_price(None) == []  # reported once


def test_restore_reports_positions_closed_while_down(gw, broker, eurusd):
    p = buy(broker)
    gw.fake.server_close(int(p.id), "sl")
    fresh = Mt5Broker(gw.client, {"EURUSD": eurusd}, MAGIC)
    fresh.restore(0.0, [p])
    [t] = fresh.on_price(None)
    assert t.exit_reason == "SL" and t.position.entry_reason == "ema cross up"


def test_gateway_down(eurusd):
    b = Mt5Broker(GatewayClient("http://127.0.0.1:9", GW_TOKEN, timeout=1), {"EURUSD": eurusd}, MAGIC)
    with pytest.raises(GatewayError) as e:
        b.account()
    assert e.value.code == "UNAVAILABLE"


# --- live runner + CLI guards ---------------------------------------------------------------
@pytest.fixture
def live_cfg(cfg, gw, tmp_path, monkeypatch):
    monkeypatch.setenv("MT5_GATEWAY_TOKEN", GW_TOKEN)
    monkeypatch.chdir(tmp_path)  # no stray .env / STOP
    return dataclasses.replace(
        cfg, symbols={"EURUSD": cfg.symbols["EURUSD"]},
        live=dataclasses.replace(cfg.live, live_enabled=True, gateway_url=gw.url, magic=MAGIC,
                                 db=str(tmp_path / "live.db"), poll_seconds=0))


@pytest.mark.parametrize("enabled,flag", [(False, True), (True, False), (False, False)])
def test_live_guards(live_cfg, gw, enabled, flag, capsys):
    c = dataclasses.replace(live_cfg, live=dataclasses.replace(live_cfg.live, live_enabled=enabled))
    assert run_live(c, flag, input_fn=lambda _: pytest.fail("must not prompt")) == 2
    assert "--confirm-live" in capsys.readouterr().err and gw.fake.requests == []


def test_live_gateway_unreachable(live_cfg, capsys):
    c = dataclasses.replace(live_cfg, live=dataclasses.replace(live_cfg.live, gateway_url="http://127.0.0.1:9",
                                                                 timeout_seconds=1))
    assert run_live(c, True, input_fn=lambda _: pytest.fail("must not prompt")) == 1
    assert "gateway/mt5_gateway.py" in capsys.readouterr().err


@pytest.mark.parametrize("answer", ["no", "YES", "", EOFError])
def test_live_banner_then_exact_yes(live_cfg, answer, capsys):
    def ask(_):
        if answer is EOFError:
            raise EOFError
        return answer
    assert run_live(live_cfg, True, input_fn=ask) == 2
    out = capsys.readouterr().out
    for s in ("12345678", "DEMO", "FakeBroker-Demo", "1000.00 USD", "Fake Broker Ltd"):
        assert s in out


def test_live_real_account_flagged(live_cfg, gw, capsys):
    gw.fake.trade_mode = gw.fake.ACCOUNT_TRADE_MODE_REAL
    run_live(live_cfg, True, input_fn=lambda _: "no")
    assert "REAL MONEY" in capsys.readouterr().out


def test_live_yes_runs(live_cfg):
    assert run_live(live_cfg, True, max_cycles=1, input_fn=lambda _: "yes") == 0


def test_live_runner_trades_at_tick_on_bar_close(live_cfg, gw, tmp_path):
    # fake history = bars 0..99, bar 99 forming; signal on bar 99 once it closes
    sig = Signal("EURUSD", "BUY", sl=1.0990, tp=1.1030, reason="test buy")
    storage = Storage(live_cfg.live.db, run_id="live", mode="live")
    feed = Mt5Feed(gw.client, live_cfg.symbols, "M15")
    broker = Mt5Broker(gw.client, feed.specs(), MAGIC)
    notifier = FakeNotifier()
    r = LiveRunner(live_cfg, feed, storage, notifier, 0, broker=broker)
    r.strategy = ScriptStrategy({98: sig, 99: sig})  # 98 is warm-up history: must NOT trade
    r.start()
    assert r.pending == {} and gw.fake.requests == []
    gw.fake.add_bar(1.1003)
    assert r.cycle()
    [p] = broker.positions()
    assert (p.side, p.entry_price, p.sl) == ("BUY", 1.1001, 1.099)  # filled at the live ask, no bar wait
    assert notifier.names()[:2] == ["startup", "entry"]
    gw.fake.server_close(int(p.id), "tp")
    gw.fake.add_bar(1.1031)
    assert r.cycle()
    [t] = r.result.trades
    assert t.exit_reason == "TP"
    assert [row["exit_reason"] for row in storage.trades()] == ["TP"]
    storage.close()
