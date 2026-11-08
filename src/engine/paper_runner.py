"""Live paper loop: polls a CSV folder for new closed bars, runs the same step() as the backtest,
persists state to SQLite after every bar, sends Telegram alerts, honours the STOP kill switch.

Restart: bars <= the last processed bar (per symbol) only warm the strategy up; the signal of the
last such bar becomes the pending order again, exactly as if the bot had never stopped."""
import logging
import threading
from datetime import datetime
from pathlib import Path

from src.broker.base import OrderRejected
from src.broker.paper_broker import PaperBroker
from src.data.csv_feed import load_csv
from src.engine.backtest import BacktestEngine
from src.models import Bar, Trade
from src.risk.risk_manager import RiskManager
from src.storage.db import Storage
from src.strategy import STRATEGIES

log = logging.getLogger("paper")


class PollingCsvFeed:
    """{data_dir}/{SYMBOL}_{TF}.csv, appended by an external writer (MT5 exporter, downloader...).
    shortcut: re-reads whole files each poll and assumes only *closed* bars are written; tail-read if files get big."""

    def __init__(self, data_dir: str | Path, symbols: dict, timeframe: str):
        self.data_dir, self.symbols, self.timeframe = Path(data_dir), symbols, timeframe

    def poll(self, after: dict[str, datetime]) -> list[Bar]:
        bars = []
        for name, spec in self.symbols.items():
            path = self.data_dir / f"{name}_{self.timeframe}.csv"
            last = after.get(name)
            bars += [b for b in load_csv(path, name, spec.default_spread_points) if last is None or b.time > last]
        return sorted(bars, key=lambda b: (b.time, b.symbol))


class PaperRunner(BacktestEngine):
    def __init__(self, cfg, feed: PollingCsvFeed, storage: Storage, notifier, poll_seconds: float = 10.0):
        super().__init__([], STRATEGIES[cfg.strategy.name](cfg.strategy.params),
                         PaperBroker(cfg.symbols, cfg.account.initial_balance, cfg.account.leverage),
                         RiskManager(cfg.risk))
        self.feed, self.storage, self.notifier, self.poll_seconds = feed, storage, notifier, poll_seconds
        self.trailing_r = cfg.risk.trailing_stop_r
        self.last_bars: dict[str, datetime] = {}
        self._unsaved: list[Trade] = []
        self._wake = threading.Event()

    # --- hooks ------------------------------------------------------------------
    def _record(self, trades: list[Trade]) -> None:
        super()._record(trades)
        self._unsaved += trades
        for t in trades:
            self.notifier.exit(t)

    def _on_open(self, pos) -> None:
        self.notifier.entry(pos)

    def kill(self, reason: str) -> None:
        """Emergency close: try every position even if one fails."""
        log.warning("kill switch: %s", reason)
        self.result.kill_reason = reason
        for p in self.broker.positions():
            try:
                self._record([self.broker.close(p.id, "KILL")])
            except (OrderRejected, KeyError) as e:
                log.error("could not close %s %s: %s", p.symbol, p.id, e)
                self.notifier.error(f"KILL: could not close {p.symbol} #{p.id}: {e}")
        self.storage.log_event("kill", reason, "WARNING")
        self._persist()
        self.notifier.kill(reason)

    def step(self, bar: Bar) -> bool:
        was_locked = self.risk.daily_locked
        ok = super().step(bar)
        if ok:
            self._trail(bar.symbol)
            if self.risk.daily_locked and not was_locked:
                eq = self.broker.account().equity
                self.storage.log_event("daily_lock", f"equity {eq:.2f} / day start {self.risk.day_start_equity:.2f}")
                self.notifier.daily_lock(eq, self.risk.day_start_equity)
        self.last_bars[bar.symbol] = bar.time
        self._persist(bar)
        return ok

    def _trail(self, symbol: str) -> None:
        """Ratchet SL to trailing_stop_r x initial SL distance behind the close (0 = off). Effective next bar."""
        if self.trailing_r <= 0:
            return
        spec = self.broker.specs[symbol]
        bid, ask = self.broker.quote(symbol)
        for p in self.broker.positions():
            if p.symbol != symbol:
                continue
            dist = self.trailing_r * p.initial_risk / (spec.contract_size * p.lots)
            if p.side == "BUY" and round(bid - dist, spec.digits) > p.sl:
                self.broker.modify(p.id, round(bid - dist, spec.digits), None)
            elif p.side == "SELL" and round(ask + dist, spec.digits) < p.sl:
                self.broker.modify(p.id, round(ask + dist, spec.digits), None)

    def _persist(self, bar: Bar | None = None) -> None:
        eq = (bar.time, self.broker.account().equity) if bar else None
        self.storage.save(self.broker.balance, self.broker.positions(), self._unsaved, self.risk, eq, self.last_bars)
        self._unsaved = []

    # --- lifecycle --------------------------------------------------------------
    def start(self) -> None:
        """Restore persisted state, then warm the strategy up on already-seen bars (no trading)."""
        state = self.storage.load_state()
        history = self.feed.poll({})
        if state:
            self.broker.restore(state["balance"], state["positions"])
            self.risk.day, self.risk.day_start_equity = state["day"], state["day_start_equity"] or 0.0
            self.risk.daily_locked = state["daily_locked"]
            cutoff = state["last_bars"]
        else:  # fresh start: everything already in the folder is history
            cutoff = {}
            for b in history:
                cutoff[b.symbol] = b.time
        for b in history:
            if b.symbol in cutoff and b.time <= cutoff[b.symbol]:
                self.history.setdefault(b.symbol, []).append(b)
                sig = self.strategy.on_bar(b.symbol, self.history[b.symbol], self._position(b.symbol))
                self.pending[b.symbol] = sig  # only the last bar's signal survives
                self.broker.set_quote(b, b.close)
        self.pending = {k: v for k, v in self.pending.items() if v}
        self.last_bars = dict(cutoff)
        self._persist()
        acc = self.broker.account()
        self.storage.log_event("start", f"balance {acc.balance:.2f}, {len(self.broker.positions())} open positions")
        self.notifier.startup("paper", acc.balance, len(self.broker.positions()))

    def cycle(self) -> bool:
        """One poll. False = kill switch fired."""
        if kill := self.risk.check_kill():
            self.kill(kill)
            return False
        for bar in self.feed.poll(self.last_bars):
            if not self.step(bar):
                return False
        return True

    def stop(self) -> None:
        self._wake.set()

    def run(self, max_cycles: int | None = None) -> int:
        """Exit code: 0 graceful stop (state kept, positions stay open), 3 kill switch."""
        self.start()
        n = 0
        while not self._wake.is_set() and (max_cycles is None or n < max_cycles):
            n += 1
            try:
                if not self.cycle():
                    return 3
                self.risk.record_success()
            except Exception as e:  # bad CSV row, disk... -> count towards the error kill switch
                log.exception("cycle failed")
                self.storage.log_event("error", f"{type(e).__name__}: {e}", "ERROR")
                self.notifier.error(f"{type(e).__name__}: {e}")
                self.risk.record_error()
            self._wake.wait(self.poll_seconds)
        self._persist()
        self.storage.log_event("stop", "graceful shutdown")
        self.notifier.stopped("shutdown")
        return 0
