from datetime import datetime, timedelta, timezone

import pytest

from src.broker.base import OrderRejected
from src.broker.paper_broker import PaperBroker
from src.models import Bar, Order

T0 = datetime(2025, 1, 6, tzinfo=timezone.utc)
# EURUSD spec: point 1e-5, spread 10 pts (0.0001), slippage 2 pts (0.00002), commission 7/lot, contract 100k
SPREAD, SLIP = 0.0001, 0.00002


def bar(i, o, h, l, c, sym="EURUSD", spread=10):
    return Bar(sym, T0 + timedelta(minutes=15 * i), o, h, l, c, 0, spread)


def make(cfg, balance=10_000):
    return PaperBroker(cfg.symbols, balance, cfg.account.leverage)


def open_at(b, side, o, sl, tp, lots=1.0):
    b.set_quote(bar(0, o, o, o, o))
    return b.open(Order("EURUSD", side, lots, sl, tp, "test"))


def test_buy_fills_at_ask_plus_slippage_and_pays_commission(cfg):
    b = make(cfg)
    p = open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    assert p.entry_price == pytest.approx(1.10000 + SPREAD + SLIP)
    assert p.commission == pytest.approx(-7.0)
    assert b.balance == pytest.approx(10_000 - 7.0)
    assert p.initial_risk == pytest.approx((p.entry_price - 1.09800) * 100_000)
    # mark to market at bid right after entry: lose spread + slippage
    assert b.account().floating_pnl == pytest.approx(-(SPREAD + SLIP) * 100_000)
    assert b.account().margin_used == pytest.approx(100_000 * p.entry_price / 100)


def test_sell_fills_at_bid_minus_slippage(cfg):
    b = make(cfg)
    p = open_at(b, "SELL", 1.10000, 1.10200, 1.09600)
    assert p.entry_price == pytest.approx(1.10000 - SLIP)


def test_buy_sl_hit_by_low_closes_at_sl_minus_slippage(cfg):
    b = make(cfg)
    p = open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    trades = b.on_price(bar(1, 1.09950, 1.09990, 1.09790, 1.09850))
    assert len(trades) == 1 and trades[0].exit_reason == "SL"
    t = trades[0]
    assert t.exit_price == pytest.approx(1.09800 - SLIP)
    assert t.gross_pnl == pytest.approx((t.exit_price - p.entry_price) * 100_000)
    assert t.net_pnl == pytest.approx(t.gross_pnl - 7.0)
    assert t.r_multiple == pytest.approx(t.net_pnl / p.initial_risk)
    assert t.r_multiple < -1  # SL loses a bit more than 1R due to slippage + commission
    assert b.balance == pytest.approx(10_000 + t.net_pnl)
    assert b.positions() == []


def test_buy_tp_fills_exactly(cfg):
    b = make(cfg)
    p = open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    [t] = b.on_price(bar(1, 1.10100, 1.10450, 1.10050, 1.10300))
    assert t.exit_reason == "TP" and t.exit_price == 1.10400
    assert t.gross_pnl == pytest.approx((1.10400 - p.entry_price) * 100_000)


def test_gap_through_sl_fills_at_open(cfg):
    b = make(cfg)
    open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    [t] = b.on_price(bar(1, 1.09500, 1.09600, 1.09400, 1.09550))
    assert t.exit_reason == "SL"
    assert t.exit_price == pytest.approx(1.09500 - SLIP)  # worse than SL


def test_gap_through_tp_fills_at_open(cfg):
    b = make(cfg)
    open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    [t] = b.on_price(bar(1, 1.10600, 1.10700, 1.10550, 1.10650))
    assert t.exit_reason == "TP" and t.exit_price == 1.10600


def test_sl_and_tp_in_same_bar_takes_sl(cfg):
    b = make(cfg)
    open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    [t] = b.on_price(bar(1, 1.10000, 1.10500, 1.09700, 1.10000))
    assert t.exit_reason == "SL"


def test_sell_sl_checked_on_ask(cfg):
    b = make(cfg)
    open_at(b, "SELL", 1.10000, 1.10200, 1.09600)
    # bid high 1.10195 < SL, but ask high = 1.10205 >= SL -> stopped out
    [t] = b.on_price(bar(1, 1.10000, 1.10195, 1.09950, 1.10100))
    assert t.exit_reason == "SL"
    assert t.exit_price == pytest.approx(1.10200 + SLIP)


def test_sell_tp_checked_on_ask(cfg):
    b = make(cfg)
    open_at(b, "SELL", 1.10000, 1.10200, 1.09600)
    assert b.on_price(bar(1, 1.09700, 1.09750, 1.09595, 1.09650)) == []  # ask low 1.09605 > TP
    [t] = b.on_price(bar(2, 1.09650, 1.09700, 1.09480, 1.09600))
    assert t.exit_reason == "TP" and t.exit_price == 1.09600


def test_floating_pnl_and_equity_marked_at_close(cfg):
    b = make(cfg)
    p = open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    b.on_price(bar(1, 1.10000, 1.10200, 1.09950, 1.10150))
    acc = b.account()
    assert acc.floating_pnl == pytest.approx((1.10150 - p.entry_price) * 100_000)
    assert acc.equity == pytest.approx(acc.balance + acc.floating_pnl)
    assert acc.free_margin == pytest.approx(acc.equity - acc.margin_used)


def test_manual_close_at_market_with_slippage(cfg):
    b = make(cfg)
    p = open_at(b, "BUY", 1.10000, 1.09800, 1.10400)
    b.set_quote(bar(1, 1.10100, 1.10100, 1.10100, 1.10100))
    t = b.close(p.id, "SIGNAL")
    assert t.exit_price == pytest.approx(1.10100 - SLIP) and t.exit_reason == "SIGNAL"


def test_sl_on_wrong_side_rejected(cfg):
    with pytest.raises(OrderRejected):
        open_at(make(cfg), "BUY", 1.10000, 1.10500, None)


def test_insufficient_margin_rejected(cfg):
    with pytest.raises(OrderRejected, match="margin"):
        open_at(make(cfg, balance=1000), "BUY", 1.10000, 1.09800, None, lots=1.0)  # needs ~1100 margin


def test_xauusd_pnl(cfg):
    b = make(cfg)
    b.set_quote(bar(0, 2000.0, 2000.0, 2000.0, 2000.0, sym="XAUUSD", spread=25))
    p = b.open(Order("XAUUSD", "SELL", 0.10, 2010.0, 1990.0, "t"))
    assert p.entry_price == pytest.approx(2000.0 - 0.05)
    [t] = b.on_price(bar(1, 1995.0, 1996.0, 1989.0, 1990.5, sym="XAUUSD", spread=25))  # ask low 1989.25
    assert t.exit_reason == "TP"
    assert t.gross_pnl == pytest.approx((1999.95 - 1990.0) * 100 * 0.10)
