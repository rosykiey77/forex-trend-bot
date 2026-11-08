import json
from datetime import datetime, timedelta, timezone

import pytest

from config import settings
from src.broker.paper_broker import PaperBroker
from src.data.csv_feed import load_csv
from src.engine.backtest import BacktestEngine
from src.engine.report import metrics
from src.main import main, run_backtest
from src.models import Bar, Position, Signal, Trade
from src.risk.risk_manager import RiskManager
from src.strategy.base import Strategy

from conftest import ROOT

FIX = ROOT / "tests" / "fixtures"
T0 = datetime(2025, 1, 6, tzinfo=timezone.utc)


def test_backtest_is_deterministic_and_trades(cfg):
    s1, r1 = run_backtest(cfg, FIX)
    s2, r2 = run_backtest(cfg, FIX)
    assert s1 == s2
    assert [(t.position.entry_price, t.exit_price, t.net_pnl) for t in r1.trades] == \
           [(t.position.entry_price, t.exit_price, t.net_pnl) for t in r2.trades]
    assert s1["trades"] > 10
    assert {t.position.symbol for t in r1.trades} == {"EURUSD", "XAUUSD"}
    assert all(t.position.sl is not None for t in r1.trades)
    assert r1.trades[-1].exit_reason in ("TP", "SL", "SIGNAL", "END_OF_DATA")


def test_never_more_than_max_positions(cfg):
    _, r = run_backtest(cfg, FIX)
    events = sorted([(t.position.open_time, 1) for t in r.trades] + [(t.exit_time, -1) for t in r.trades],
                    key=lambda e: (e[0], e[1]))  # closes before opens at the same time
    open_now = peak = 0
    for _, d in events:
        open_now += d
        peak = max(peak, open_now)
    assert peak <= cfg.risk.max_open_positions


class BuyOnThirdBar(Strategy):
    def on_bar(self, symbol, bars, position):
        if len(bars) == 3:
            return Signal(symbol, "BUY", sl=bars[-1].close - 0.0020, tp=bars[-1].close + 0.0040, reason="t")


def test_signal_executes_at_next_bar_open(cfg):
    bars = [Bar("EURUSD", T0 + timedelta(minutes=15 * i), 1.1 + i * 1e-4, 1.1 + i * 1e-4 + 5e-5,
                1.1 + i * 1e-4 - 5e-5, 1.1 + i * 1e-4, 0, 10) for i in range(6)]
    broker = PaperBroker(cfg.symbols, 10_000, 100)
    res = BacktestEngine(bars, BuyOnThirdBar({}), broker, RiskManager(cfg.risk)).run()
    [t] = res.trades
    assert t.position.open_time == bars[3].time
    assert t.position.entry_price == pytest.approx(bars[3].open + 10e-5 + 2e-5)
    assert t.exit_reason == "END_OF_DATA" and t.exit_time == bars[5].time


def _trade(net, r):
    p = Position("1", "EURUSD", "BUY", 0.1, 1.1, 1.09, None, T0, abs(net / r), "x")
    return Trade(p, 1.1, T0, "TP", net, net, r)


def test_metrics():
    trades = [_trade(20, 2.0), _trade(-10, -1.0), _trade(-10, -1.0), _trade(30, 3.0)]
    eq = [(T0, 1000), (T0, 1020), (T0, 1010), (T0, 1000), (T0, 1030)]
    m = metrics(trades, eq, 1000)
    assert m["trades"] == 4 and m["win_rate"] == 50.0
    assert m["profit_factor"] == 2.5
    assert m["total_r"] == 3.0 and m["avg_r"] == 0.75
    assert m["max_drawdown_pct"] == pytest.approx(round(20 / 1020 * 100, 2))
    assert m["net_pnl"] == 30 and m["final_balance"] == 1030


def test_metrics_empty():
    assert metrics([], [], 1000)["trades"] == 0


def test_cli_backtest_writes_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = main(["--mode", "backtest", "--config", str(ROOT / "config/config.yaml"),
               "--data", str(FIX), "--log-level", "WARNING"])
    assert rc == 0
    [summary] = list((tmp_path / "reports").glob("*/summary.json"))
    s = json.loads(summary.read_text())
    assert {"win_rate", "profit_factor", "max_drawdown_pct", "total_r"} <= s.keys()
    assert (summary.parent / "trades.csv").exists()
    assert "Backtest summary" in capsys.readouterr().out


def test_cli_missing_data_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--mode", "backtest", "--config", str(ROOT / "config/config.yaml"), "--data", "nope"]) == 1


def test_cli_stop_file_kills_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "STOP").touch()
    assert main(["--mode", "backtest", "--config", str(ROOT / "config/config.yaml"),
                 "--data", str(FIX), "--log-level", "WARNING"]) == 3


@pytest.mark.parametrize("body,msg", [
    ("time,open,high,low\n", "missing columns"),
    ("time,open,high,low,close\n2025-01-01T00:00:00Z,1,1,1,1\n2025-01-01T00:00:00Z,1,1,1,1\n", "row 3"),
    ("time,open,high,low,close\n2025-01-01T00:00:00Z,1,0.9,0.8,1\n", "row 2"),
    ("time,open,high,low,close\n2025-01-01T00:00:00Z,-1,1,-1,1\n", "price <= 0"),
])
def test_csv_validation(tmp_path, body, msg):
    f = tmp_path / "X.csv"
    f.write_text(body)
    with pytest.raises(ValueError, match=msg):
        load_csv(f, "X", 10)


def test_csv_epoch_time_and_default_spread(tmp_path):
    f = tmp_path / "X.csv"
    f.write_text("time,open,high,low,close\n1735689600,1,1.1,0.9,1\n")
    [b] = load_csv(f, "X", 7)
    assert b.time == datetime(2025, 1, 1, tzinfo=timezone.utc) and b.spread_points == 7


@pytest.mark.parametrize("patch", ["risk_per_trade_pct: 0", "risk_per_trade_pct: 6"])
def test_config_rejects_bad_risk(tmp_path, patch):
    text = (ROOT / "config/config.yaml").read_text().replace("risk_per_trade_pct: 1.0", patch)
    (tmp_path / "c.yaml").write_text(text)
    with pytest.raises(ValueError, match="risk_per_trade_pct"):
        settings.load(tmp_path / "c.yaml")


def test_config_rejects_symbol_without_pip_size(tmp_path):
    text = (ROOT / "config/config.yaml").read_text().replace("    pip_size: 0.0001\n", "")
    (tmp_path / "c.yaml").write_text(text)
    with pytest.raises(ValueError, match="pip_size"):
        settings.load(tmp_path / "c.yaml")
