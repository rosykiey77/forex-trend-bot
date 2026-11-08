import json
from datetime import date, datetime, timezone

import pytest

from src.data.news_calendar import CalendarEvent, currencies, in_blackout, load_calendar, summarize
from src.data.polymarket_probs import fed_decision_probs
from src.llm.macro_judge import MacroJudge, combine, parse_verdict

DAY = date(2026, 11, 9)


# --- combine (Lapisan A + B) --------------------------------------------------
@pytest.mark.parametrize("tech,llm,want", [
    ("Buy", "Overweight", "Buy"), ("Overweight", "Buy", "Buy"), ("Underweight", "Sell", "Sell"),
    ("Overweight", "Overweight", "Overweight"), ("Hold", "Hold", "Hold"),
    ("Buy", "Hold", "Overweight"), ("Hold", "Overweight", "Hold"), ("Sell", "Hold", "Underweight"),
    ("Hold", "Underweight", "Hold"),
    ("Buy", "Sell", "Hold"), ("Overweight", "Underweight", "Hold"), ("Sell", "Buy", "Hold"),
])
def test_combine_rules(tech, llm, want):
    assert combine(tech, llm) == want


def test_combine_rejects_unknown():
    with pytest.raises(ValueError):
        combine("Strong Buy", "Hold")


# --- verdict parsing (trust boundary: LLM output) ------------------------------
def test_parse_verdict_ok_and_fenced():
    v = {"rating": "Sell", "alasan": "USD kuat", "risiko_utama": "NFP"}
    assert parse_verdict(json.dumps(v)) == v
    assert parse_verdict("```json\n" + json.dumps(v) + "\n```")["rating"] == "Sell"


@pytest.mark.parametrize("raw", ["not json", '{"rating": "Strong Buy", "alasan": "x", "risiko_utama": "y"}',
                                 '{"rating": "Buy"}', '["Buy"]', '{"rating": "Buy", "alasan": 1, "risiko_utama": "y"}'])
def test_parse_verdict_invalid_raises(raw):
    with pytest.raises(ValueError):
        parse_verdict(raw)


# --- judge pipeline -------------------------------------------------------------
class FakeLLM:
    def __init__(self, verdict):
        self.prompts, self.verdict = [], verdict

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.verdict if "JSON" in prompt else f"argument {len(self.prompts)}"


def test_judge_runs_four_calls_with_context_and_lessons():
    llm = FakeLLM('{"rating": "Underweight", "alasan": "Fed hawkish", "risiko_utama": "CPI"}')
    j = MacroJudge(llm, news=lambda s, d: "ECB dovish", probs=lambda: {"No change": 0.8},
                   lessons=lambda s: ["pelajaran-1"])
    out = j.rate("EURUSD", DAY)
    assert out["rating"] == "Underweight" and len(llm.prompts) == 4
    assert "ECB dovish" in llm.prompts[0] and "No change" in llm.prompts[0]
    assert "pelajaran-1" in llm.prompts[3]


def test_judge_source_failure_is_hold_without_llm_calls():
    def boom(*a):
        raise OSError("down")
    llm = FakeLLM("{}")
    out = MacroJudge(llm, news=boom, probs=lambda: {}).rate("EURUSD", DAY)
    assert out["rating"] == "Hold" and "down" in out["alasan"] and llm.prompts == []


def test_judge_bad_llm_output_is_hold():
    assert MacroJudge(FakeLLM("garbage")).rate("EURUSD", DAY)["rating"] == "Hold"


# --- polymarket ----------------------------------------------------------------
def gamma_event(*markets):
    return [{"markets": [{"groupItemTitle": t, "outcomes": '["Yes", "No"]',
                          "outcomePrices": json.dumps([str(p), str(round(1 - p, 4))])} for t, p in markets]}]


def test_fed_probs_parses_gamma_event():
    urls = []
    get = lambda url: urls.append(url) or gamma_event(("25 bps decrease", 0.85), ("No change", 0.14))  # noqa: E731
    assert fed_decision_probs("fed-decision-in-december", get=get) == {"25 bps decrease": 0.85, "No change": 0.14}
    assert urls == ["https://gamma-api.polymarket.com/events?slug=fed-decision-in-december"]


def test_fed_probs_rejects_bad_data():
    with pytest.raises(ValueError):
        fed_decision_probs("x", get=lambda u: [])
    with pytest.raises(ValueError):
        fed_decision_probs("x", get=lambda u: gamma_event(("No change", 1.7)))


# --- news calendar -------------------------------------------------------------
def ev(h, m, ccy="USD", impact="high"):
    return CalendarEvent(datetime(2026, 11, 9, h, m, tzinfo=timezone.utc), ccy, impact, f"{ccy} event")


def test_currencies():
    assert currencies("EURUSD") == ("EUR", "USD") and currencies("XAUUSD") == ("XAU", "USD")


def test_blackout_window():
    events = [ev(13, 30)]
    at = lambda h, m: datetime(2026, 11, 9, h, m, tzinfo=timezone.utc)  # noqa: E731
    assert in_blackout(events, "EURUSD", at(13, 0)) and in_blackout(events, "EURUSD", at(14, 0))
    assert not in_blackout(events, "EURUSD", at(12, 59)) and not in_blackout(events, "EURUSD", at(14, 1))
    assert not in_blackout(events, "GBPJPY", at(13, 30))
    assert not in_blackout([ev(13, 30, impact="low")], "EURUSD", at(13, 30))


def test_load_and_summarize(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps([{"time": "2026-11-09T13:30:00+00:00", "currency": "USD", "impact": "high", "title": "CPI"},
                             {"time": "2026-11-10T09:00:00+00:00", "currency": "EUR", "impact": "high", "title": "PMI"}]))
    events = load_calendar(p)
    assert events[0].title == "CPI" and events[0].time.tzinfo is not None
    assert "CPI" in summarize(events, "EURUSD", DAY) and "PMI" not in summarize(events, "EURUSD", DAY)
