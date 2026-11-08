"""Lapisan C: H1 pullback entries in the direction of the daily rating (Lapisan A, optionally merged with B).

Daily bias: H1 bars are aggregated into UTC days; when a day completes, its close feeds the D1 score
(no look-ahead: the running day is never used). Entry: the bar dips into the EMA20-50 zone and closes back
out of it in the bias direction. SL = max(1.5 ATR, nearest swing) capped at 2.5 ATR; TP = rr R (0 = none,
use risk.trailing_stop_r). Risk per trade comes from the rating (Buy/Sell 1%, Over/Underweight 0.5%).
Open positions close on a time stop (time_stop_bars H1 bars) or when the bias flips to the other side."""
import logging

from src.llm.macro_judge import combine
from src.models import Bar, Position, Signal
from src.data.news_calendar import in_blackout
from src.strategy.base import Strategy
from src.strategy.daily_bias import MIN_CLOSES, RISK_PCT, direction, rating_from_score, score

log = logging.getLogger(__name__)


class PullbackH1Strategy(Strategy):
    name = "pullback_h1"

    def __init__(self, params: dict, judge=None, memory=None, calendar=None):
        """judge: MacroJudge-like (.rate(symbol, day) -> dict), used only if llm_bias_enabled.
        memory: ReflectionStore for daily decision log + 5-day settlement. calendar: CalendarEvents for news blackout."""
        super().__init__(params)
        self.fast = int(params.get("ema_fast", 20))
        self.slow = int(params.get("ema_slow", 50))
        self.atr_period = int(params.get("atr_period", 14))
        self.sl_atr = float(params.get("sl_atr", 1.5))
        self.max_sl_atr = float(params.get("max_sl_atr", 2.5))
        self.swing_bars = int(params.get("swing_bars", 10))
        self.rr = float(params.get("rr", 2.0))
        self.time_stop_bars = int(params.get("time_stop_bars", 120))  # 5 days x 24 H1 bars
        self.news_blackout_min = int(params.get("news_blackout_minutes", 30))
        self.judge = judge if params.get("llm_bias_enabled", False) else None
        if params.get("llm_bias_enabled") and judge is None:
            log.warning("llm_bias_enabled but no judge wired: using Lapisan A only")
        self.memory, self.calendar = memory, calendar or []
        self.warmup_bars = self.slow + self.atr_period
        self._state: dict[str, dict] = {}
        self.ratings: dict[str, str] = {}
        self.daily_score: dict[str, int | None] = {}

    # --- daily bias -------------------------------------------------------------------
    def _close_day(self, symbol: str, st: dict) -> None:
        st["daily"].append((st["d_high"], st["d_low"], st["d_close"]))
        closes = [d[2] for d in st["daily"]]
        if len(closes) < MIN_CLOSES:
            return
        s = score(closes)
        tech = rating_from_score(s)
        llm = None
        if self.judge:
            try:
                llm = self.judge.rate(symbol, st["day"])["rating"]
            except Exception as e:  # noqa: BLE001 - a broken LLM layer must never stop trading on Lapisan A
                log.warning("macro judge %s: %s -> Hold", symbol, e)
                llm = "Hold"
        final = combine(tech, llm) if llm else tech
        self.daily_score[symbol], self.ratings[symbol] = s, final
        if self.memory:
            d = st["daily"][-15:]
            trs = [max(h, pc) - min(l, pc) for (h, l, _), (_, _, pc) in zip(d[1:], d[:-1])]
            self.memory.record(st["day"], symbol, s, final, closes[-1], sum(trs) / len(trs),
                               llm_rating=llm, reason=f"tech={tech} llm={llm}")
            self.memory.settle(symbol)

    # --- per H1 bar ------------------------------------------------------------------
    def on_bar(self, symbol: str, bars: list[Bar], position: Position | None) -> Signal | None:
        b = bars[-1]
        st = self._state.get(symbol)
        if st is None:
            self.ratings[symbol], self.daily_score[symbol] = "Hold", None
            st = self._state[symbol] = {"n": 1, "fast": b.close, "slow": b.close, "atr": b.high - b.low,
                                        "close": b.close, "daily": [], "day": b.time.date(),
                                        "d_high": b.high, "d_low": b.low, "d_close": b.close}
            return None
        if b.time.date() != st["day"]:
            self._close_day(symbol, st)
            st.update(day=b.time.date(), d_high=b.high, d_low=b.low)
        st["d_high"], st["d_low"], st["d_close"] = max(st["d_high"], b.high), min(st["d_low"], b.low), b.close

        tr = max(b.high - b.low, abs(b.high - st["close"]), abs(b.low - st["close"]))
        st["fast"] += (b.close - st["fast"]) * 2 / (self.fast + 1)
        st["slow"] += (b.close - st["slow"]) * 2 / (self.slow + 1)
        st["atr"] += (tr - st["atr"]) / self.atr_period
        st["close"] = b.close
        st["n"] += 1
        if st["n"] < self.warmup_bars:
            return None

        rating = self.ratings[symbol]
        bias = direction(rating)
        if position is not None:
            side = 1 if position.side == "BUY" else -1
            if bias == -side:
                return Signal(symbol, "CLOSE", reason=f"daily bias flipped to {rating}")
            held = sum(1 for x in bars[-self.time_stop_bars:] if x.time >= position.open_time)
            if held >= self.time_stop_bars:
                return Signal(symbol, "CLOSE", reason=f"time stop: {held} H1 bars without TP/SL")
            return None
        if bias == 0:
            return None

        top, bot = max(st["fast"], st["slow"]), min(st["fast"], st["slow"])
        if bias > 0:
            ok = b.low <= top and b.close > top and b.close > b.open
            swing_dist = b.close - min(x.low for x in bars[-self.swing_bars:])
        else:
            ok = b.high >= bot and b.close < bot and b.close < b.open
            swing_dist = max(x.high for x in bars[-self.swing_bars:]) - b.close
        # entry fills at the next bar's open, so that is the moment checked against the news calendar
        if not ok or in_blackout(self.calendar, symbol, b.time + (b.time - bars[-2].time), self.news_blackout_min):
            return None
        atr = st["atr"]
        dist = min(max(atr * self.sl_atr, swing_dist), atr * self.max_sl_atr)
        side = "BUY" if bias > 0 else "SELL"
        return Signal(symbol, side, sl=b.close - bias * dist, tp=b.close + bias * self.rr * dist if self.rr > 0 else None,
                      reason=f"{rating} pullback EMA{self.fast}-{self.slow}, ATR={atr:.5f}", risk_pct=RISK_PCT[rating])
