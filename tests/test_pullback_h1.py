from datetime import date, datetime, timedelta, timezone

import pytest

from src.data.news_calendar import CalendarEvent
from src.memory.reflection import ReflectionStore
from src.models import Bar, Position
from src.strategy import STRATEGIES
from src.strategy.pullback_h1 import PullbackH1Strategy

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SYM = "EURUSD"


def bar(i, o, h, l, c):
    return Bar(SYM, T0 + timedelta(hours=i), o, h, l, c)


def warm(s, n=70, px=1.1):
    """Flat H1 bars: EMA20 = EMA50 = px, ATR = 0.001. Stays in the first 3 days so the daily rating is Hold."""
    bars = []
    for i in range(n):
        bars.append(bar(i, px, px + 0.0005, px - 0.0005, px))
        assert s.on_bar(SYM, bars, None) is None
    return bars


def feed(s, bars, b, pos=None):
    bars.append(b)
    return s.on_bar(SYM, bars, pos)


def pos(side, open_time):
    return Position("1", SYM, side, 0.1, 1.1, 1.09 if side == "BUY" else 1.11, None, open_time, 10.0, "x")


def test_registered():
    assert STRATEGIES["pullback_h1"] is PullbackH1Strategy


def test_hold_never_enters():
    s = PullbackH1Strategy({})
    bars = warm(s)
    assert s.ratings[SYM] == "Hold"
    assert feed(s, bars, bar(70, 1.0998, 1.1010, 1.0990, 1.1008)) is None


@pytest.mark.parametrize("rating,risk", [("Buy", 1.0), ("Overweight", 0.5)])
def test_buy_pullback_entry_with_rating_risk(rating, risk):
    s = PullbackH1Strategy({})
    bars = warm(s)
    s.ratings[SYM] = rating
    sig = feed(s, bars, bar(70, 1.0998, 1.1010, 1.0990, 1.1008))  # dips into EMA zone, closes back above, bullish
    assert sig.side == "BUY" and sig.risk_pct == risk
    # ATR after this bar ~0.00107 -> 1.5 ATR = 0.0016 < swing distance 0.0018 -> SL behind the swing low
    assert sig.sl == pytest.approx(1.0990) and sig.tp == pytest.approx(1.1008 + 2 * 0.0018)


@pytest.mark.parametrize("rating,risk", [("Sell", 1.0), ("Underweight", 0.5)])
def test_sell_pullback_entry(rating, risk):
    s = PullbackH1Strategy({})
    bars = warm(s)
    s.ratings[SYM] = rating
    sig = feed(s, bars, bar(70, 1.1002, 1.1010, 1.0990, 1.0992))
    assert sig.side == "SELL" and sig.risk_pct == risk
    assert sig.sl == pytest.approx(1.1010) and sig.tp == pytest.approx(1.0992 - 2 * 0.0018)


def test_no_entry_without_zone_touch_or_against_candle():
    s = PullbackH1Strategy({})
    bars = warm(s)
    s.ratings[SYM] = "Buy"
    assert feed(s, bars, bar(70, 1.1003, 1.1012, 1.1002, 1.1010)) is None  # never touched the zone
    assert feed(s, bars, bar(71, 1.1008, 1.1010, 1.0990, 1.1003)) is None  # bearish candle
    assert feed(s, bars, bar(72, 1.0990, 1.0999, 1.0985, 1.0995)) is None  # closed inside/below zone
    s.ratings[SYM] = "Sell"
    assert feed(s, bars, bar(73, 1.0998, 1.1010, 1.0990, 1.1008)) is None  # bullish candle vs Sell bias


def test_sl_uses_atr_when_swing_is_near():
    s = PullbackH1Strategy({})
    bars = warm(s)
    s.ratings[SYM] = "Buy"
    sig = feed(s, bars, bar(70, 1.0999, 1.1004, 1.0996, 1.1003))  # swing low 1.0995 (warm bars) -> 0.0008 < 1.5 ATR
    atr = 0.001 + (0.0008 - 0.001) / 14
    assert 1.1003 - sig.sl == pytest.approx(1.5 * atr)


def test_sl_capped_at_2_5_atr():
    s = PullbackH1Strategy({})
    bars = warm(s)
    s.ratings[SYM] = "Buy"
    bars.append(bar(70, 1.1, 1.1005, 1.0950, 1.1))  # deep wick -> far swing low
    s.on_bar(SYM, bars, None)
    sig = feed(s, bars, bar(71, 1.0999, 1.1006, 1.0998, 1.1005))
    assert sig is not None
    atr = s._state[SYM]["atr"]
    assert 1.1005 - sig.sl == pytest.approx(2.5 * atr)


def test_rr_zero_means_no_tp():
    s = PullbackH1Strategy({"rr": 0})
    bars = warm(s)
    s.ratings[SYM] = "Buy"
    assert feed(s, bars, bar(70, 1.0998, 1.1010, 1.0990, 1.1008)).tp is None


def test_time_stop_after_five_days_of_h1_bars():
    s = PullbackH1Strategy({})
    bars = warm(s)
    s.ratings[SYM] = "Buy"
    p = pos("BUY", bars[-1].time + timedelta(hours=1))
    for i in range(70, 70 + 119):  # bars 70..188 -> 119 bars since open
        bars.append(bar(i, 1.1, 1.1005, 1.0995, 1.1))
        s.ratings[SYM] = "Buy"  # keep bias stable across day rollovers (daily data not ready)
        assert s.on_bar(SYM, bars, p) is None
    s.ratings[SYM] = "Buy"
    sig = feed(s, bars, bar(189, 1.1, 1.1005, 1.0995, 1.1), p)
    assert sig.side == "CLOSE" and "time stop" in sig.reason


def test_bias_flip_closes_position():
    s = PullbackH1Strategy({})
    bars = warm(s)
    s.ratings[SYM] = "Underweight"
    sig = feed(s, bars, bar(70, 1.1, 1.1005, 1.0995, 1.1), pos("BUY", bars[-1].time))
    assert sig.side == "CLOSE" and "bias" in sig.reason
    s.ratings[SYM] = "Hold"  # neutral bias keeps the position
    assert feed(s, bars, bar(71, 1.1, 1.1005, 1.0995, 1.1), pos("BUY", bars[-1].time)) is None


def test_news_blackout_blocks_entry():
    fill = T0 + timedelta(hours=71)  # signal on bar 70 fills at bar 71's open
    s = PullbackH1Strategy({}, calendar=[CalendarEvent(fill + timedelta(minutes=20), "USD", "high", "CPI")])
    bars = warm(s)
    s.ratings[SYM] = "Buy"
    assert feed(s, bars, bar(70, 1.0998, 1.1010, 1.0990, 1.1008)) is None


# --- daily bias from aggregated H1 bars ------------------------------------------
def choppy_days(n_days=230):
    """H1 bars whose daily closes follow the choppy uptrend from test_daily_bias (rating Buy)."""
    closes, c = [], 1.0
    for i in range(n_days):
        c += 0.002 + 0.001 * i / 260 if i % 2 == 0 else -0.0018
        closes.append(c)
    bars = []
    for d, dc in enumerate(closes):
        for h in range(24):
            bars.append(Bar(SYM, T0 + timedelta(days=d, hours=h), dc, dc + 0.0004, dc - 0.0004, dc))
    return bars, closes


class FakeJudge:
    def __init__(self, rating="Sell", fail=False):
        self.rating, self.fail, self.calls = rating, fail, []

    def rate(self, symbol, day):
        self.calls.append(day)
        if self.fail:
            raise RuntimeError("boom")
        return {"rating": self.rating, "alasan": "x", "risiko_utama": "y"}


def run(s, bars):
    hist = []
    for b in bars:
        hist.append(b)
        s.on_bar(SYM, hist, None)


def test_daily_rating_from_completed_days_only():
    bars, closes = choppy_days(230)
    s = PullbackH1Strategy({})
    run(s, bars[:-23])  # last day has only its first bar: not completed, must not be used
    assert s.daily_score[SYM] is not None and s.ratings[SYM] == "Buy"
    from src.strategy.daily_bias import score
    assert s.daily_score[SYM] == score(closes[:-1])


def test_llm_disabled_by_default_ignores_judge():
    bars, _ = choppy_days(205)
    judge = FakeJudge("Sell")
    s = PullbackH1Strategy({}, judge=judge)
    run(s, bars + [Bar(SYM, T0 + timedelta(days=205), 1, 1, 1, 1)])
    assert judge.calls == [] and s.ratings[SYM] != "Hold"


def test_llm_enabled_opposite_view_forces_hold():
    bars, _ = choppy_days(205)
    s = PullbackH1Strategy({"llm_bias_enabled": True}, judge=FakeJudge("Sell"))
    run(s, bars + [Bar(SYM, T0 + timedelta(days=205), 1, 1, 1, 1)])
    assert s.ratings[SYM] == "Hold"


def test_llm_failure_counts_as_hold_and_downgrades():
    bars, closes = choppy_days(205)
    s = PullbackH1Strategy({"llm_bias_enabled": True}, judge=FakeJudge(fail=True))
    run(s, bars + [Bar(SYM, T0 + timedelta(days=205), 1, 1, 1, 1)])
    from src.strategy.daily_bias import rating_from_score, score
    tech = rating_from_score(score(closes))
    assert tech == "Buy" and s.ratings[SYM] == "Overweight"


def test_llm_enabled_without_judge_falls_back_to_layer_a():
    bars, _ = choppy_days(205)
    s = PullbackH1Strategy({"llm_bias_enabled": True})
    run(s, bars + [Bar(SYM, T0 + timedelta(days=205), 1, 1, 1, 1)])
    assert s.ratings[SYM] == "Buy"


def test_memory_records_and_settles_daily_decisions(tmp_path):
    bars, _ = choppy_days(210)
    mem = ReflectionStore(tmp_path / "m.db")
    s = PullbackH1Strategy({}, memory=mem)
    run(s, bars + [Bar(SYM, T0 + timedelta(days=210), 1, 1, 1, 1)])
    n = mem.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    settled = mem.conn.execute("SELECT COUNT(*) FROM decisions WHERE settled = 1").fetchone()[0]
    assert n == 11 and settled == 6  # days 200..210 decided; first 6 have 5 newer days
    assert mem.conn.execute("SELECT day FROM decisions ORDER BY day LIMIT 1").fetchone()[0] == str(date(2026, 7, 19))
    mem.close()


def test_backtest_end_to_end_rating_sized_trades(cfg):
    import math
    from src.broker.paper_broker import PaperBroker
    from src.engine.backtest import BacktestEngine
    from src.risk.risk_manager import RiskManager

    # 260 days of H1: daily zig-zag uptrend plus an intraday sine so price keeps revisiting the EMA zone
    bars, closes, c = [], [], 1.0
    for d in range(260):
        prev, c = c, c + (0.002 + 0.001 * d / 260 if d % 2 == 0 else -0.0018)
        for h in range(24):
            px = prev + (c - prev) * (h + 1) / 24 + 0.0015 * math.sin(h / 24 * 2 * math.pi * 2)
            o = bars[-1].close if bars else px
            bars.append(Bar(SYM, T0 + timedelta(days=d, hours=h), o, max(o, px) + 0.0003, min(o, px) - 0.0003, px))
    s = PullbackH1Strategy({})
    res = BacktestEngine(bars, s, PaperBroker(cfg.symbols, cfg.account.initial_balance, cfg.account.leverage), RiskManager(cfg.risk)).run()
    assert res.trades and all(t.position.side == "BUY" for t in res.trades)  # only with the Buy/Overweight bias
    assert all(t.position.open_time.date() > (T0 + timedelta(days=199)).date() for t in res.trades)
    # 1% of ~1000 equity at risk per Buy trade (Overweight would be ~0.5%); never above the config ceiling
    assert all(0 < t.position.initial_risk <= 1000 * cfg.risk.risk_per_trade_pct / 100 * 1.2 for t in res.trades)
