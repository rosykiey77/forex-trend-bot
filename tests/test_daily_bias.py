import pytest

from src.strategy.daily_bias import RISK_PCT, components, direction, rating_from_score, rsi, score


def test_rating_map_all_scores():
    expect = {5: "Buy", 4: "Buy", 3: "Overweight", 2: "Overweight", 1: "Hold", 0: "Hold", -1: "Hold",
              -2: "Underweight", -3: "Underweight", -4: "Sell", -5: "Sell"}
    for s, r in expect.items():
        assert rating_from_score(s) == r


def test_rating_rejects_out_of_range():
    with pytest.raises(ValueError):
        rating_from_score(6)


def test_risk_and_direction():
    assert RISK_PCT == {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": 0.5, "Sell": 1.0}
    assert [direction(r) for r in ("Buy", "Overweight", "Hold", "Underweight", "Sell")] == [1, 1, 0, -1, -1]


def test_needs_200_closes():
    with pytest.raises(ValueError):
        score([1.0] * 199)


def choppy_uptrend():
    # zig-zag rise with slowly growing up-steps: RSI stays in 50-70, MACD histogram > 0
    c = [1.0]
    for i in range(260):
        c.append(c[-1] + (0.002 + 0.001 * i / 260 if i % 2 == 0 else -0.0018))
    return c


def test_choppy_uptrend_is_buy():
    c = components(choppy_uptrend())
    assert {k: v for k, v in c.items() if k != "rsi_value"} == {"sma200": 1, "sma50_200": 1, "macd": 1, "ema10": 1, "rsi": 1}
    assert rating_from_score(score(choppy_uptrend())) == "Buy"


def test_mirror_downtrend_is_sell():
    down = [3.0 - c for c in choppy_uptrend()]
    assert score(down) == -5 and rating_from_score(score(down)) == "Sell"


def test_rsi_overbought_scores_zero():
    closes = [1.0 + 0.001 * i for i in range(250)]  # straight line up -> RSI 100
    c = components(closes)
    assert c["rsi_value"] > 70 and c["rsi"] == 0
    assert score(closes) == 4


def test_rsi_bounds():
    assert rsi([1.0] * 20) == 50.0  # flat market: neutral
    assert rsi([1 + i for i in range(20)]) == 100.0
