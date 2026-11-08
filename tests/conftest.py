import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402


@pytest.fixture
def cfg():
    return settings.load(ROOT / "config" / "config.yaml")


@pytest.fixture
def eurusd(cfg):
    return cfg.symbols["EURUSD"]


@pytest.fixture
def xauusd(cfg):
    return cfg.symbols["XAUUSD"]


# --- paper-mode helpers (test_paper_runner, test_kill_switch) -------------------------------
import dataclasses  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from src.engine.paper_runner import PaperRunner, PollingCsvFeed  # noqa: E402
from src.storage.db import Storage  # noqa: E402
from src.strategy.base import Strategy  # noqa: E402

T0 = datetime(2025, 1, 6, tzinfo=timezone.utc)


def bar_time(i: int) -> datetime:
    return T0 + timedelta(minutes=15 * i)


def append_bars(folder, symbol, rows):
    """rows: (i, open, high, low, close); appends to {symbol}_M15.csv like a live exporter would."""
    path = folder / f"{symbol}_M15.csv"
    new = not path.exists()
    with open(path, "a") as f:
        if new:
            f.write("time,open,high,low,close,volume,spread\n")
        for i, o, h, l, c in rows:
            f.write(f"{bar_time(i).isoformat()},{o},{h},{l},{c},100,10\n")


class ScriptStrategy(Strategy):
    """Emits signals[bar index] (bar time T0 + 15 min * i)."""
    name = "script"

    def __init__(self, signals):
        super().__init__({})
        self.signals = {bar_time(i): s for i, s in signals.items()}

    def on_bar(self, symbol, bars, position):
        return self.signals.get(bars[-1].time)


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a)) or True

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def paper(cfg, tmp_path):
    """Factory: make(signals) -> PaperRunner on EURUSD only, DB + CSV folder + STOP path under tmp_path."""
    pcfg = dataclasses.replace(
        cfg, symbols={"EURUSD": cfg.symbols["EURUSD"]},
        risk=dataclasses.replace(cfg.risk, stop_file=str(tmp_path / "STOP")),
        paper=dataclasses.replace(cfg.paper, data_dir=str(tmp_path / "live"), db=str(tmp_path / "paper.db"),
                                  poll_seconds=0),
    )
    (tmp_path / "live").mkdir()
    opened = []

    def make(signals=None, **risk_overrides):
        c = dataclasses.replace(pcfg, risk=dataclasses.replace(pcfg.risk, **risk_overrides))
        storage = Storage(c.paper.db)
        opened.append(storage)
        r = PaperRunner(c, PollingCsvFeed(c.paper.data_dir, c.symbols, c.timeframe), storage, FakeNotifier(), 0)
        r.strategy = ScriptStrategy(signals or {})
        return r

    make.cfg, make.dir, make.stop = pcfg, tmp_path / "live", tmp_path / "STOP"
    yield make
    for s in opened:
        s.close()


# --- MT5 gateway helpers (test_mt5_gateway, test_mt5_broker, test_mt5_feed) -------------------
import threading  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from gateway.mt5_gateway import Gateway, make_server  # noqa: E402
from src.broker.mt5_broker import GatewayClient  # noqa: E402
from tests.fake_mt5 import FakeMT5  # noqa: E402

GW_TOKEN = "test-token"


@pytest.fixture
def gw():
    """Gateway on a random localhost port over a FakeMT5. Yields (client, fake, url)."""
    fake = FakeMT5()
    gateway = Gateway(fake, GW_TOKEN)
    srv = make_server(gateway, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield SimpleNamespace(client=GatewayClient(url, GW_TOKEN, timeout=5), fake=fake, url=url, gateway=gateway)
    srv.shutdown()
    srv.server_close()
