"""Lapisan A: deterministic D1 technical score (-5..+5) -> 5-level rating (TradingAgents ladder)."""

RATINGS = ("Sell", "Underweight", "Hold", "Overweight", "Buy")  # weakest short -> strongest long
RISK_PCT = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": 0.5, "Sell": 1.0}
MIN_CLOSES = 200


def direction(rating: str) -> int:
    return {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}[rating]


def rating_from_score(s: int) -> str:
    if not -5 <= s <= 5:
        raise ValueError(f"score {s} outside -5..+5")
    return "Buy" if s >= 4 else "Overweight" if s >= 2 else "Hold" if s >= -1 else "Underweight" if s >= -3 else "Sell"


def ema_series(xs: list[float], n: int) -> list[float]:
    out, k = [xs[0]], 2 / (n + 1)  # seeded with first value, same as pandas ewm(adjust=False)
    for x in xs[1:]:
        out.append(out[-1] + (x - out[-1]) * k)
    return out


def rsi(closes: list[float], n: int = 14) -> float:
    gains = losses = 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, l = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            gains, losses = gains + g / n, losses + l / n
        else:  # Wilder smoothing
            gains, losses = gains + (g - gains) / n, losses + (l - losses) / n
    if gains == losses == 0:
        return 50.0
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def components(closes: list[float]) -> dict:
    """closes: closed D1 closes, oldest first. Each component is +1 bullish / -1 bearish (RSI may be 0)."""
    if len(closes) < MIN_CLOSES:
        raise ValueError(f"need >= {MIN_CLOSES} daily closes, got {len(closes)}")
    c = closes[-1]
    sma50, sma200 = sum(closes[-50:]) / 50, sum(closes[-200:]) / 200
    macd = [a - b for a, b in zip(ema_series(closes, 12), ema_series(closes, 26))]
    hist = macd[-1] - ema_series(macd, 9)[-1]
    r = rsi(closes)
    sign = lambda ok: 1 if ok else -1  # noqa: E731
    return {
        "sma200": sign(c > sma200),
        "sma50_200": sign(sma50 > sma200),
        "macd": sign(hist > 0),
        "ema10": sign(c > ema_series(closes, 10)[-1]),
        "rsi": 1 if 50 <= r <= 70 else -1 if 30 <= r < 50 else 0,
        "rsi_value": r,
    }


def score(closes: list[float]) -> int:
    c = components(closes)
    return c["sma200"] + c["sma50_200"] + c["macd"] + c["ema10"] + c["rsi"]
