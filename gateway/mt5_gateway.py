"""MT5 gateway: tiny HTTP service that runs next to the MT5 terminal (Windows VPS or Wine Python).

    set MT5_GATEWAY_TOKEN=<long random string>
    python gateway/mt5_gateway.py --host 127.0.0.1 --port 8765

Every request needs `Authorization: Bearer <MT5_GATEWAY_TOKEN>`. Bind to 127.0.0.1 and reach it from the
bot through an SSH tunnel / WireGuard: plain HTTP, the token is not encrypted on the wire.
Responses: {"ok": true, "data": ...} or {"ok": false, "error": {"code", "message", "retcode"}};
HTTP 200 except 401 (auth) / 404 (unknown endpoint). See docs/contracts/gateway.md.

Stdlib only. Without the MetaTrader5 package (e.g. on Linux) the server still starts and every call
answers NOT_CONNECTED, so the bot side can be wired up and tested anywhere.
"""
import argparse
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    import MetaTrader5 as mt5_lib
except ImportError:
    mt5_lib = None

log = logging.getLogger("mt5_gateway")
MAX_BODY = 64 * 1024


class GatewayError(Exception):
    def __init__(self, code: str, message: str, retcode: int | None = None):
        super().__init__(message)
        self.code, self.retcode = code, retcode


def _f(v):
    """numpy scalar -> plain Python (MT5 rates are a numpy structured array)."""
    return v.item() if hasattr(v, "item") else v


class Gateway:
    def __init__(self, mt5, token: str):
        if not token:
            raise ValueError("MT5_GATEWAY_TOKEN is empty")
        self.mt5, self.token = mt5, token
        self.lock = threading.Lock()  # the MetaTrader5 package is not thread-safe
        self.routes = {
            ("GET", "/health"): self.health, ("GET", "/candles"): self.candles,
            ("GET", "/tick"): self.tick, ("GET", "/symbol_info"): self.symbol_info,
            ("GET", "/positions"): self.positions, ("GET", "/deals"): self.deals,
            ("POST", "/order"): self.order, ("POST", "/modify"): self.modify, ("POST", "/close"): self.close,
        }

    def call(self, fn, params: dict) -> dict:
        with self.lock:
            try:
                self._connect()
                return {"ok": True, "data": fn(params)}
            except GatewayError as e:
                return _err(e.code, str(e), e.retcode)
            except (KeyError, ValueError, TypeError) as e:
                return _err("BAD_REQUEST", f"{type(e).__name__}: {e}")
            except Exception as e:  # noqa: BLE001 - never kill the server thread
                log.exception("internal error")
                return _err("INTERNAL", f"{type(e).__name__}: {e}")

    # --- helpers ----------------------------------------------------------------
    def _connect(self) -> None:
        m = self.mt5
        if m is None:
            raise GatewayError("NOT_CONNECTED", "MetaTrader5 package not installed (pip install MetaTrader5, Windows/Wine only)")
        if m.account_info() is None and not m.initialize():
            raise GatewayError("NOT_CONNECTED", f"MT5 initialize failed: {m.last_error()}")
        if m.account_info() is None:
            raise GatewayError("NOT_CONNECTED", f"terminal not logged in: {m.last_error()}")

    def _symbol(self, p: dict):
        name = p["symbol"]
        info = self.mt5.symbol_info(name) if self.mt5.symbol_select(name, True) else None
        if info is None:
            raise GatewayError("UNKNOWN_SYMBOL", f"unknown symbol {name!r}")
        return info

    def _tick(self, name: str):
        t = self.mt5.symbol_info_tick(name)
        if t is None or not t.bid or not t.ask:
            raise GatewayError("UNKNOWN_SYMBOL", f"no tick for {name!r}")
        return t

    def _filling(self, info) -> int:
        m = self.mt5
        fm = info.filling_mode  # bitmask: 1 = FOK allowed, 2 = IOC allowed
        return m.ORDER_FILLING_FOK if fm & 1 else m.ORDER_FILLING_IOC if fm & 2 else m.ORDER_FILLING_RETURN

    def _send(self, req: dict):
        r = self.mt5.order_send(req)
        if r is None:
            raise GatewayError("ORDER_REJECTED", f"order_send returned None: {self.mt5.last_error()}")
        if r.retcode not in (self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_DONE_PARTIAL):
            raise GatewayError("ORDER_REJECTED", f"retcode {r.retcode}: {r.comment}", r.retcode)
        return r

    def _own_position(self, p: dict):
        ticket, magic = int(p["ticket"]), int(p["magic"])
        found = self.mt5.positions_get(ticket=ticket)
        if not found:
            raise GatewayError("ORDER_REJECTED", f"position {ticket} not found")
        if found[0].magic != magic:  # never touch manual / other EA positions
            raise GatewayError("ORDER_REJECTED", f"position {ticket} has foreign magic {found[0].magic}")
        return found[0]

    # --- endpoints --------------------------------------------------------------
    def health(self, p: dict) -> dict:
        m, a = self.mt5, self.mt5.account_info()
        mode = {m.ACCOUNT_TRADE_MODE_DEMO: "demo", m.ACCOUNT_TRADE_MODE_CONTEST: "contest"}.get(a.trade_mode, "real")
        return {"connected": True, "broker": a.company, "server": a.server, "login": a.login, "name": a.name,
                "currency": a.currency, "trade_mode": mode, "demo": mode == "demo", "leverage": a.leverage,
                "balance": a.balance, "equity": a.equity, "margin": a.margin, "margin_free": a.margin_free}

    def candles(self, p: dict) -> list[dict]:
        self._symbol(p)
        tf = getattr(self.mt5, f"TIMEFRAME_{p.get('timeframe', 'M15')}", None)
        if tf is None:
            raise ValueError(f"unknown timeframe {p.get('timeframe')!r}")
        count = int(p.get("count", 500))
        if not 1 <= count <= 10000:
            raise ValueError("count must be in [1, 10000]")
        rates = self.mt5.copy_rates_from_pos(p["symbol"], tf, int(p.get("start", 0)), count)
        if rates is None:
            raise GatewayError("INTERNAL", f"copy_rates_from_pos failed: {self.mt5.last_error()}")
        keys = ("time", "open", "high", "low", "close", "tick_volume", "spread")
        return [{k: _f(r[k]) for k in keys} for r in rates]

    def tick(self, p: dict) -> dict:
        info = self._symbol(p)
        t = self._tick(p["symbol"])
        return {"time": t.time, "bid": t.bid, "ask": t.ask, "spread_points": round((t.ask - t.bid) / info.point)}

    def symbol_info(self, p: dict) -> dict:
        i = self._symbol(p)
        return {"name": i.name, "point": i.point, "digits": i.digits, "contract_size": i.trade_contract_size,
                "volume_min": i.volume_min, "volume_max": i.volume_max, "volume_step": i.volume_step,
                "spread": i.spread}

    def positions(self, p: dict) -> list[dict]:
        m = self.mt5
        magic = int(p["magic"]) if p.get("magic") not in (None, "") else None
        return [{"ticket": x.ticket, "symbol": x.symbol, "side": "BUY" if x.type == m.POSITION_TYPE_BUY else "SELL",
                 "volume": x.volume, "price_open": x.price_open, "sl": x.sl, "tp": x.tp, "time": x.time,
                 "profit": x.profit, "swap": x.swap, "magic": x.magic, "comment": x.comment}
                for x in m.positions_get() or () if magic is None or x.magic == magic]

    def deals(self, p: dict) -> list[dict]:
        m = self.mt5
        reasons = {m.DEAL_REASON_SL: "SL", m.DEAL_REASON_TP: "TP", m.DEAL_REASON_SO: "STOP_OUT"}
        return [{"ticket": d.ticket, "position_id": d.position_id, "time": d.time, "price": d.price,
                 "volume": d.volume, "profit": d.profit, "commission": d.commission, "swap": d.swap,
                 "fee": getattr(d, "fee", 0.0), "magic": d.magic,
                 "entry": "IN" if d.entry == m.DEAL_ENTRY_IN else "OUT", "reason": reasons.get(d.reason, "OTHER")}
                for d in m.history_deals_get(position=int(p["position"])) or ()]

    def order(self, p: dict) -> dict:
        m = self.mt5
        side, volume, sl, tp = p["side"], float(p["volume"]), float(p.get("sl") or 0), float(p.get("tp") or 0)
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        if volume <= 0:
            raise ValueError("volume must be > 0")
        if sl <= 0:  # FR-016 double guard: no order without a stop loss
            raise GatewayError("ORDER_REJECTED", "order without SL refused")
        info = self._symbol(p)
        t = self._tick(p["symbol"])
        r = self._send({
            "action": m.TRADE_ACTION_DEAL, "symbol": p["symbol"], "volume": volume,
            "type": m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL,
            "price": t.ask if side == "BUY" else t.bid, "sl": sl, "tp": tp,
            "deviation": int(p.get("deviation", 20)), "magic": int(p["magic"]),
            "comment": str(p.get("comment", ""))[:31], "type_time": m.ORDER_TIME_GTC,
            "type_filling": self._filling(info),
        })
        # MT5: the position ticket equals the ticket of the order that opened it
        return {"ticket": r.order, "price": r.price, "volume": r.volume, "retcode": r.retcode}

    def modify(self, p: dict) -> dict:
        pos = self._own_position(p)
        sl = pos.sl if p.get("sl") is None else float(p["sl"])
        tp = pos.tp if p.get("tp") is None else float(p["tp"])
        r = self._send({"action": self.mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "symbol": pos.symbol,
                        "sl": sl, "tp": tp, "magic": pos.magic})
        return {"retcode": r.retcode, "sl": sl, "tp": tp}

    def close(self, p: dict) -> dict:
        m = self.mt5
        pos = self._own_position(p)
        info = self._symbol({"symbol": pos.symbol})
        t = self._tick(pos.symbol)
        buy = pos.type == m.POSITION_TYPE_BUY
        r = self._send({
            "action": m.TRADE_ACTION_DEAL, "position": pos.ticket, "symbol": pos.symbol, "volume": pos.volume,
            "type": m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY, "price": t.bid if buy else t.ask,
            "deviation": int(p.get("deviation", 20)), "magic": pos.magic, "comment": "close",
            "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling(info),
        })
        return {"price": r.price, "retcode": r.retcode, "profit": pos.profit}


def _err(code: str, message: str, retcode: int | None = None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "retcode": retcode}}


def make_server(gw: Gateway, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    expected = f"Bearer {gw.token}".encode()

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: dict) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self, method: str) -> None:
            if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected):
                return self._reply(401, _err("AUTH", "missing or wrong bearer token"))
            url = urlparse(self.path)
            fn = gw.routes.get((method, url.path))
            if fn is None:
                return self._reply(404, _err("NOT_FOUND", f"{method} {url.path}"))
            try:
                if method == "GET":
                    params = {k: v[-1] for k, v in parse_qs(url.query).items()}
                else:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > MAX_BODY:
                        raise ValueError("body too large")
                    params = json.loads(self.rfile.read(n) or b"{}")
                    if not isinstance(params, dict):
                        raise ValueError("body must be a JSON object")
            except ValueError as e:
                return self._reply(200, _err("BAD_REQUEST", str(e)))
            self._reply(200, gw.call(fn, params))

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MT5 HTTP gateway")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    if mt5_lib is None:
        log.warning("MetaTrader5 package not found: serving NOT_CONNECTED for every call")
    try:
        gw = Gateway(mt5_lib, os.environ.get("MT5_GATEWAY_TOKEN", ""))
    except ValueError as e:
        log.error("%s", e)
        return 1
    srv = make_server(gw, a.host, a.port)
    log.info("listening on http://%s:%s", a.host, a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        if mt5_lib is not None:
            mt5_lib.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
