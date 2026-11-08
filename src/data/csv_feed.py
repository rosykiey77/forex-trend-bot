"""CSV bar loader. File per symbol: {SYMBOL}_{TF}.csv, columns time,open,high,low,close[,volume][,spread].
time = ISO-8601 (UTC if no offset) or epoch seconds; spread in points."""
import csv
import heapq
from datetime import datetime, timezone
from pathlib import Path

from src.models import Bar

REQUIRED = ("time", "open", "high", "low", "close")


def _parse_time(s: str) -> datetime:
    s = s.strip()
    if s.replace(".", "", 1).isdigit():
        return datetime.fromtimestamp(float(s), tz=timezone.utc)
    t = datetime.fromisoformat(s)
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def load_csv(path: str | Path, symbol: str, default_spread: int,
             start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
    bars: list[Bar] = []
    prev = None
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        for row_no, r in enumerate(reader, start=2):  # row 1 = header
            try:
                spread = r.get("spread")
                b = Bar(symbol, _parse_time(r["time"]), float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]), float(r.get("volume") or 0),
                        int(float(spread)) if spread not in (None, "") else default_spread)
            except (TypeError, ValueError) as e:
                raise ValueError(f"{path} row {row_no}: {e}") from None
            if min(b.open, b.high, b.low, b.close) <= 0:
                raise ValueError(f"{path} row {row_no}: price <= 0")
            if b.high < max(b.open, b.close) or b.low > min(b.open, b.close):
                raise ValueError(f"{path} row {row_no}: high/low inconsistent with open/close")
            if prev and b.time <= prev:
                raise ValueError(f"{path} row {row_no}: time not strictly increasing")
            prev = b.time
            if (start and b.time < start) or (end and b.time >= end):
                continue
            bars.append(b)
    return bars


class CsvFeed:
    def __init__(self, data_dir: str | Path, symbols: dict, timeframe: str,
                 start: datetime | None = None, end: datetime | None = None):
        """symbols: name -> SymbolSpec (for default spread)."""
        self.series = {
            name: load_csv(Path(data_dir) / f"{name}_{timeframe}.csv", name, spec.default_spread_points, start, end)
            for name, spec in symbols.items()
        }

    def bars(self):
        """All symbols merged in time order (ties broken by symbol name, deterministic)."""
        return heapq.merge(*self.series.values(), key=lambda b: (b.time, b.symbol))
