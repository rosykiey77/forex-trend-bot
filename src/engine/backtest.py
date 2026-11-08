"""Bar-by-bar backtest. Signal on close of bar t -> executed at open of bar t+1 (no look-ahead)."""
import logging
from dataclasses import dataclass, field
from datetime import datetime

from src.broker.base import OrderRejected
from src.broker.paper_broker import PaperBroker
from src.models import Bar, Rejection, Signal, Trade
from src.risk.risk_manager import RiskManager
from src.strategy.base import Strategy

log = logging.getLogger("engine")


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity: list[tuple[datetime, float]] = field(default_factory=list)
    rejections: list[tuple[datetime, str, str]] = field(default_factory=list)  # (time, symbol, reason)
    kill_reason: str | None = None


class BacktestEngine:
    def __init__(self, bars, strategy: Strategy, broker: PaperBroker, risk: RiskManager):
        self.bars = bars  # iterable of Bar, all symbols, time ordered
        self.strategy, self.broker, self.risk = strategy, broker, risk
        self.history: dict[str, list[Bar]] = {}
        self.pending: dict[str, Signal] = {}
        self.result = BacktestResult()

    def _record(self, trades: list[Trade]) -> None:
        for t in trades:
            log.info("close %s %s %s @%.5f net=%.2f R=%.2f", t.position.symbol, t.position.side,
                     t.exit_reason, t.exit_price, t.net_pnl, t.r_multiple)
        self.result.trades.extend(trades)

    def _close_all(self, reason: str) -> None:
        self._record([self.broker.close(p.id, reason) for p in self.broker.positions()])

    def _position(self, symbol: str):
        return next((p for p in self.broker.positions() if p.symbol == symbol), None)

    def _execute(self, sig: Signal, bar: Bar) -> None:
        pos = self._position(sig.symbol)
        if sig.side == "CLOSE":
            if pos:
                self._record([self.broker.close(pos.id, "SIGNAL")])
            return
        spec = self.broker.specs[sig.symbol]
        bid, ask = self.broker.quote(sig.symbol)
        spread = bar.spread_points if bar.spread_points is not None else spec.default_spread_points
        decision = self.risk.evaluate(sig, spec, bid, ask, spread, self.broker.account(),
                                      self.broker.positions(), bar.time)
        if isinstance(decision, Rejection):
            reason = decision.reason
        else:
            try:
                p = self.broker.open(decision)
                log.info("open %s %s %.2f lots @%.5f sl=%.5f tp=%s | %s", p.symbol, p.side, p.lots,
                         p.entry_price, p.sl, p.tp, p.entry_reason)
                return
            except OrderRejected as e:
                reason = str(e)
        log.info("reject %s %s: %s", sig.symbol, sig.side, reason)
        self.result.rejections.append((bar.time, sig.symbol, reason))

    def run(self) -> BacktestResult:
        for bar in self.bars:
            if kill := self.risk.check_kill(bar.time):
                log.warning("kill switch: %s", kill)
                self.result.kill_reason = kill
                self._close_all("KILL")
                return self.result
            self.broker.set_quote(bar)  # market price = this bar's open
            if sig := self.pending.pop(bar.symbol, None):
                self._execute(sig, bar)
            self._record(self.broker.on_price(bar))
            equity = self.broker.account().equity
            self.risk.update(equity, bar.time)

            hist = self.history.setdefault(bar.symbol, [])
            hist.append(bar)
            if sig := self.strategy.on_bar(bar.symbol, hist, self._position(bar.symbol)):
                self.pending[bar.symbol] = sig
            self.result.equity.append((bar.time, equity))
        self._close_all("END_OF_DATA")
        if self.result.equity:
            self.result.equity.append((self.result.equity[-1][0], self.broker.account().equity))
        return self.result
