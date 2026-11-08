import json
import urllib.error
import urllib.request

import pytest

from gateway.mt5_gateway import Gateway, make_server
from src.broker.mt5_broker import GatewayClient, GatewayError
from tests.conftest import GW_TOKEN

MAGIC = 777


def err(fn, *a, **k) -> GatewayError:
    with pytest.raises(GatewayError) as e:
        fn(*a, **k)
    return e.value


def test_auth_required(gw):
    for token in ("wrong", "x" * len(GW_TOKEN)):
        assert err(GatewayClient(gw.url, token).get, "/health").code == "AUTH"
    req = urllib.request.Request(gw.url + "/health")  # no header at all
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401 and json.loads(e.value.read())["error"]["code"] == "AUTH"


def test_unknown_endpoint_404(gw):
    assert err(gw.client.get, "/nope").code == "NOT_FOUND"
    assert err(gw.client.post, "/health").code == "NOT_FOUND"  # wrong method


def test_empty_token_refused():
    with pytest.raises(ValueError):
        Gateway(None, "")


def test_health_demo_and_real(gw):
    h = gw.client.get("/health")
    assert h["connected"] and h["demo"] and h["trade_mode"] == "demo"
    assert (h["login"], h["server"], h["broker"], h["balance"]) == (12345678, "FakeBroker-Demo", "Fake Broker Ltd", 1000.0)
    gw.fake.trade_mode = gw.fake.ACCOUNT_TRADE_MODE_REAL
    h = gw.client.get("/health")
    assert not h["demo"] and h["trade_mode"] == "real"


def test_without_metatrader5_package_still_serves():
    import threading
    srv = make_server(Gateway(None, GW_TOKEN), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    try:
        c = GatewayClient(f"http://127.0.0.1:{srv.server_address[1]}", GW_TOKEN)
        e = err(c.get, "/health")
        assert e.code == "NOT_CONNECTED" and "MetaTrader5" in str(e)
    finally:
        srv.shutdown()
        srv.server_close()


def test_terminal_not_logged_in(gw):
    gw.fake.logged_in = False
    assert err(gw.client.get, "/tick", symbol="EURUSD").code == "NOT_CONNECTED"


def test_candles(gw):
    rows = gw.client.get("/candles", symbol="EURUSD", timeframe="M15", count=10, start=1)
    assert len(rows) == 10
    assert rows[-1]["time"] == gw.fake.rates["EURUSD"][-2]["time"]  # forming bar skipped
    assert set(rows[0]) == {"time", "open", "high", "low", "close", "tick_volume", "spread"}
    assert err(gw.client.get, "/candles", symbol="EURUSD", timeframe="M7").code == "BAD_REQUEST"
    assert err(gw.client.get, "/candles", symbol="EURUSD", count=0).code == "BAD_REQUEST"
    assert err(gw.client.get, "/candles", symbol="NOPE").code == "UNKNOWN_SYMBOL"


def test_tick_and_symbol_info(gw):
    t = gw.client.get("/tick", symbol="EURUSD")
    assert (t["bid"], t["ask"], t["spread_points"]) == (1.1, 1.1001, 10)
    i = gw.client.get("/symbol_info", symbol="EURUSD")
    assert (i["point"], i["digits"], i["contract_size"], i["volume_min"], i["volume_step"]) == (1e-5, 5, 100000.0, 0.01, 0.01)
    assert err(gw.client.get, "/symbol_info", symbol="XXX").code == "UNKNOWN_SYMBOL"


def test_order_requires_sl(gw):
    for sl in (None, 0):
        e = err(gw.client.post, "/order", symbol="EURUSD", side="BUY", volume=0.1, sl=sl, magic=MAGIC)
        assert e.code == "ORDER_REJECTED"
    assert gw.fake.requests == []
    assert err(gw.client.post, "/order", symbol="EURUSD", side="HOLD", volume=0.1, sl=1.09, magic=MAGIC).code == "BAD_REQUEST"


def test_order_open_modify_close(gw):
    r = gw.client.post("/order", symbol="EURUSD", side="BUY", volume=0.1, sl=1.099, tp=1.102, magic=MAGIC,
                       comment="x" * 50)
    req = gw.fake.requests[-1]
    assert r["price"] == 1.1001 and req["price"] == 1.1001  # BUY at ask
    assert req["magic"] == MAGIC and len(req["comment"]) == 31
    assert req["type_filling"] == gw.fake.ORDER_FILLING_IOC  # filling_mode bitmask 2
    [p] = gw.client.get("/positions", magic=MAGIC)
    assert (p["ticket"], p["side"], p["sl"], p["tp"]) == (r["ticket"], "BUY", 1.099, 1.102)

    gw.client.post("/modify", ticket=r["ticket"], magic=MAGIC, sl=1.0995)  # tp omitted -> kept
    [p] = gw.client.get("/positions", magic=MAGIC)
    assert (p["sl"], p["tp"]) == (1.0995, 1.102)

    c = gw.client.post("/close", ticket=r["ticket"], magic=MAGIC)
    assert c["price"] == 1.1 and gw.fake.requests[-1]["type"] == gw.fake.ORDER_TYPE_SELL  # BUY closes at bid
    assert gw.client.get("/positions", magic=MAGIC) == []
    deals = gw.client.get("/deals", position=r["ticket"])
    assert [d["entry"] for d in deals] == ["IN", "OUT"]


def test_broker_rejection_carries_retcode(gw):
    gw.fake.reject_next = gw.fake.TRADE_RETCODE_INVALID_STOPS
    e = err(gw.client.post, "/order", symbol="EURUSD", side="SELL", volume=0.1, sl=1.2, magic=MAGIC)
    assert e.code == "ORDER_REJECTED" and e.retcode == 10016


def test_foreign_positions_untouchable(gw):
    manual = gw.fake.add_manual_position(magic=0)
    assert gw.client.get("/positions", magic=MAGIC) == []
    assert len(gw.client.get("/positions")) == 1  # no filter = everything (read only)
    assert err(gw.client.post, "/close", ticket=manual, magic=MAGIC).code == "ORDER_REJECTED"
    assert err(gw.client.post, "/modify", ticket=manual, magic=MAGIC, sl=1.0).code == "ORDER_REJECTED"
    assert err(gw.client.post, "/close", ticket=999999, magic=MAGIC).code == "ORDER_REJECTED"
    assert manual in gw.fake.pos and gw.fake.requests == []


def test_bad_json_body(gw):
    req = urllib.request.Request(gw.url + "/order", data=b"[1,2", method="POST",
                                 headers={"Authorization": f"Bearer {GW_TOKEN}"})
    body = json.loads(urllib.request.urlopen(req, timeout=5).read())
    assert body["ok"] is False and body["error"]["code"] == "BAD_REQUEST"
