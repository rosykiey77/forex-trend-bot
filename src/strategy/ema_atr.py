"""EMA fast/slow crossover; SL = close -/+ ATR*atr_mult, TP = rr * SL distance (default 2R)."""
from src.models import Bar, Position, Signal
from src.strategy.base import Strategy


class EmaAtrStrategy(Strategy):
    name = "ema_atr"

    def __init__(self, params: dict):
        super().__init__(params)
        self.fast = int(params.get("fast", 20))
        self.slow = int(params.get("slow", 50))
        self.atr_period = int(params.get("atr_period", 14))
        self.atr_mult = float(params.get("atr_mult", 1.5))
        self.rr = float(params.get("rr", 2.0))
        if not 0 < self.fast < self.slow:
            raise ValueError("ema_atr: need 0 < fast < slow")
        self.warmup_bars = self.slow + self.atr_period
        self._state: dict[str, dict] = {}

    def on_bar(self, symbol: str, bars: list[Bar], position: Position | None) -> Signal | None:
        # Indicators are updated incrementally from bars[-1] (O(1) per bar), same values as a full
        # recompute with ewm(adjust=False) / Wilder ATR, as long as every closed bar is passed in order.
        b = bars[-1]
        st = self._state.get(symbol)
        if st is None:
            st = self._state[symbol] = {"n": 1, "fast": b.close, "slow": b.close, "atr": b.high - b.low, "close": b.close}
            return None
        tr = max(b.high - b.low, abs(b.high - st["close"]), abs(b.low - st["close"]))
        prev_fast, prev_slow = st["fast"], st["slow"]
        st["fast"] += (b.close - st["fast"]) * 2 / (self.fast + 1)
        st["slow"] += (b.close - st["slow"]) * 2 / (self.slow + 1)
        st["atr"] += (tr - st["atr"]) / self.atr_period
        st["close"] = b.close
        st["n"] += 1
        if st["n"] < self.warmup_bars:
            return None

        up = prev_fast <= prev_slow and st["fast"] > st["slow"]
        down = prev_fast >= prev_slow and st["fast"] < st["slow"]
        if not (up or down):
            return None
        side = "BUY" if up else "SELL"
        why = f"EMA{self.fast}{'>' if up else '<'}EMA{self.slow} cross, ATR={st['atr']:.5f}"
        if position is not None:
            return Signal(symbol, "CLOSE", reason=why) if position.side != side else None
        dist = st["atr"] * self.atr_mult
        sign = 1 if up else -1
        return Signal(symbol, side, sl=b.close - sign * dist, tp=b.close + sign * self.rr * dist, reason=why)
