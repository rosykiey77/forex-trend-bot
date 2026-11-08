#!/usr/bin/env python3
"""Sync live H1 & M15 market data from Yahoo Finance for EURUSD and XAUUSD to CSV."""
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sync_feed")

OUT_DIR = Path("/home/ubuntu/forex-trend-bot/data/live")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TICKERS = {
    "EURUSD": ("EURUSD=X", 10, 5),   # spread 10 points (1 pip), 5 digits
    "XAUUSD": ("GC=F", 25, 2),       # spread 25 points, 2 digits
}

TIMEFRAMES = [
    ("H1", "1h", "730d"),
    ("M15", "15m", "5d"),
]

def fetch_ohlcv(ticker: str, interval: str, timerange: str, spread_points: int, digits: int) -> list[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={timerange}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        log.error("Failed to fetch %s (%s): %s", ticker, interval, e)
        return []

    try:
        res = data["chart"]["result"][0]
        timestamps = res.get("timestamp", [])
        quotes = res["indicators"]["quote"][0]
        opens = quotes.get("open", [])
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        closes = quotes.get("close", [])
        volumes = quotes.get("volume", [])
    except Exception as e:
        log.error("Malformed payload for %s (%s): %s", ticker, interval, e)
        return []

    rows = []
    # Skip the very last incomplete/forming bar
    n = len(timestamps) - 1
    for i in range(max(0, n)):
        t_sec = timestamps[i]
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        v = volumes[i] or 0
        if any(v is None for v in (o, h, l, c)):
            continue
        dt_str = datetime.fromtimestamp(t_sec, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append({
            "time": dt_str,
            "open": f"{o:.{digits}f}",
            "high": f"{h:.{digits}f}",
            "low": f"{l:.{digits}f}",
            "close": f"{c:.{digits}f}",
            "volume": int(v),
            "spread": spread_points,
        })
    return rows

def sync_symbol_tf(symbol: str, ticker: str, tf_label: str, interval: str, timerange: str, spread: int, digits: int) -> int:
    csv_path = OUT_DIR / f"{symbol}_{tf_label}.csv"
    existing_rows: dict[str, dict] = {}
    if csv_path.exists():
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    if r.get("time"):
                        existing_rows[r["time"]] = r
        except Exception as e:
            log.warning("Could not read %s: %s", csv_path, e)

    fresh = fetch_ohlcv(ticker, interval, timerange, spread, digits)
    if not fresh:
        return 0

    added = 0
    for r in fresh:
        if r["time"] not in existing_rows:
            added += 1
        existing_rows[r["time"]] = r

    sorted_rows = sorted(existing_rows.values(), key=lambda x: x["time"])

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume", "spread"])
        writer.writeheader()
        writer.writerows(sorted_rows)

    log.info("%s_%s: total %d bars (+%d new)", symbol, tf_label, len(sorted_rows), added)
    return added

def main():
    for sym, (ticker, spread, digits) in TICKERS.items():
        for tf_label, interval, timerange in TIMEFRAMES:
            sync_symbol_tf(sym, ticker, tf_label, interval, timerange, spread, digits)

if __name__ == "__main__":
    main()
