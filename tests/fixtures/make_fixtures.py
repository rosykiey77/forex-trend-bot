"""Regenerate deterministic M15 fixtures: python tests/fixtures/make_fixtures.py"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent


def make(symbol, start_price, sigma, digits, spread, seed, n=3000):
    rnd = random.Random(seed)
    t = datetime(2025, 1, 6, tzinfo=timezone.utc)  # Monday
    price, drift, rows = start_price, 0.0, []
    while len(rows) < n:
        if t.weekday() < 5:
            if len(rows) % 200 == 0:  # new trend regime
                drift = rnd.choice((-1, 1)) * rnd.uniform(0.05, 0.3) * sigma
            o = price
            c = o + drift + rnd.gauss(0, sigma)
            h = max(o, c) + abs(rnd.gauss(0, sigma / 2))
            l = min(o, c) - abs(rnd.gauss(0, sigma / 2))
            sp = spread * (3 if rnd.random() < 0.01 else 1)
            rows.append(f"{t:%Y-%m-%dT%H:%M:%SZ},{o:.{digits}f},{h:.{digits}f},{l:.{digits}f},{c:.{digits}f},"
                        f"{rnd.randint(50, 500)},{sp}")
            price = round(c, digits)
        t += timedelta(minutes=15)
    (OUT / f"{symbol}_M15.csv").write_text("time,open,high,low,close,volume,spread\n" + "\n".join(rows) + "\n")


if __name__ == "__main__":
    make("EURUSD", 1.10000, 0.0004, 5, 10, seed=1)
    make("XAUUSD", 2000.00, 1.2, 2, 25, seed=2)
