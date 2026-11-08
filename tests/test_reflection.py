from datetime import date, timedelta

import pytest

from src.memory.reflection import ReflectionStore

D0 = date(2026, 11, 2)


@pytest.fixture
def mem(tmp_path):
    m = ReflectionStore(tmp_path / "mem.db")
    yield m
    m.close()


def record_days(mem, closes, rating="Buy", symbol="EURUSD", atr=0.01):
    for i, c in enumerate(closes):
        mem.record(D0 + timedelta(days=i), symbol, score=4, final_rating=rating, close=c, atr=atr)


def test_not_settled_before_horizon(mem):
    record_days(mem, [1.10, 1.11, 1.12, 1.13, 1.14])  # only 4 newer days for the first decision
    assert mem.settle("EURUSD") == [] and mem.lessons() == []


def test_settle_after_five_days_buy_correct(mem):
    record_days(mem, [1.10, 1.11, 1.12, 1.13, 1.14, 1.15])
    [d] = mem.settle("EURUSD")
    assert d["day"] == str(D0) and d["move_atr"] == pytest.approx(5.0) and d["correct"] is True
    assert len(mem.lessons()) == 1 and "benar" in mem.lessons()[0]
    assert mem.settle("EURUSD") == []  # idempotent


def test_sell_bias_scored_in_its_direction(mem):
    record_days(mem, [1.10, 1.11, 1.12, 1.13, 1.14, 1.15], rating="Sell")
    [d] = mem.settle("EURUSD")
    assert d["move_atr"] == pytest.approx(-5.0) and d["correct"] is False and "salah" in mem.lessons()[0]


def test_hold_has_no_correctness(mem):
    record_days(mem, [1.10] * 6, rating="Hold")
    [d] = mem.settle("EURUSD")
    assert d["correct"] is None


def test_record_is_idempotent_per_day(mem):
    record_days(mem, [1.10])
    record_days(mem, [1.20])  # restart replay of the same day must not duplicate
    assert tuple(mem.conn.execute("SELECT COUNT(*), MAX(close) FROM decisions").fetchone()) == (1, 1.10)


def test_custom_writer_and_latest_five_lessons(mem):
    record_days(mem, [1.10 + 0.01 * i for i in range(12)])
    mem.settle("EURUSD", writer=lambda d: f"lesson {d['day']}")
    ls = mem.lessons(n=5)
    assert len(ls) == 5 and ls[0] == f"lesson {D0 + timedelta(days=6)}"  # newest first


def test_symbols_are_separate(mem):
    record_days(mem, [1.10] * 6)
    record_days(mem, [2.0] * 3, symbol="XAUUSD")
    assert mem.settle("XAUUSD") == [] and len(mem.settle("EURUSD")) == 1
    assert mem.lessons(symbol="XAUUSD") == []


def test_writer_failure_falls_back(mem):
    record_days(mem, [1.10 + 0.01 * i for i in range(6)])
    def bad(d):
        raise RuntimeError("llm down")
    assert len(mem.settle("EURUSD", writer=bad)) == 1 and "benar" in mem.lessons()[0]
