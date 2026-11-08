"""Live loop: PaperRunner (persistence, alerts, kill switch, trailing) on Mt5Feed + Mt5Broker."""
import dataclasses

from src.engine.paper_runner import PaperRunner
from src.models import Bar


class LiveRunner(PaperRunner):
    mode = "live"

    def start(self) -> None:
        super().start()
        # warm-up signals are stale (or were already executed before a restart): never trade them
        self.pending.clear()

    def step(self, bar: Bar) -> bool:
        """Closed bars arrive only after they close, so execute the signal now at the live tick, the
        equivalent of the backtest's next-bar-open fill (instead of waiting for the next bar to close).
        shortcut: bars caught up after downtime also trade at the current tick; fine for M15 trend signals."""
        ok = super().step(bar)
        if ok and (sig := self.pending.pop(bar.symbol, None)):
            bid, ask = self.broker.quote(bar.symbol)
            spread = round((ask - bid) / self.broker.specs[bar.symbol].point)
            self._execute(sig, dataclasses.replace(bar, spread_points=spread))
            self._persist()
        return ok
