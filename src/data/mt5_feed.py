"""Live bar feed from the MT5 gateway. Same poll() contract as PollingCsvFeed (paper_runner.py)."""
import dataclasses

from src.broker.mt5_broker import GatewayClient, _utc
from src.models import Bar, SymbolSpec


class Mt5Feed:
    def __init__(self, client: GatewayClient, symbols: dict[str, SymbolSpec], timeframe: str, count: int = 500):
        self.client, self.symbols, self.timeframe, self.count = client, symbols, timeframe, count

    def poll(self, after: dict) -> list[Bar]:
        """Closed bars newer than after[symbol] (all `count` bars on first call = warm-up history).
        shortcut: a downtime longer than `count` bars leaves a gap; raise live.history_bars if that matters."""
        bars = []
        for name, spec in self.symbols.items():
            # start=1 skips bar 0, the one still forming
            rows = self.client.get("/candles", symbol=name, timeframe=self.timeframe, count=self.count, start=1)
            last = after.get(name)
            for r in rows:
                b = Bar(name, _utc(r["time"]), r["open"], r["high"], r["low"], r["close"], r.get("tick_volume", 0),
                        r.get("spread", spec.default_spread_points))
                if last is None or b.time > last:
                    bars.append(b)
        return sorted(bars, key=lambda b: (b.time, b.symbol))

    def specs(self) -> dict[str, SymbolSpec]:
        """Config specs with the broker's real contract data (lot sizing must match the server)."""
        out = {}
        for name, spec in self.symbols.items():
            i = self.client.get("/symbol_info", symbol=name)
            out[name] = dataclasses.replace(spec, point=i["point"], digits=i["digits"], contract_size=i["contract_size"],
                                            volume_min=i["volume_min"], volume_max=i["volume_max"],
                                            volume_step=i["volume_step"])
        return out
