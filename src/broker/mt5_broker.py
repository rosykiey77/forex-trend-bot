"""Live broker: talks to gateway/mt5_gateway.py over HTTP (stdlib urllib).

The MT5 server is the source of truth: positions are re-read on every call, positions closed
server-side (SL/TP/stop-out/manual) are detected in on_price() and turned into Trades from the deal
history. Only positions carrying our magic number are ever read, modified or closed.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlencode

from src.broker.base import Broker, OrderRejected
from src.models import AccountInfo, Bar, Order, Position, SymbolSpec, Trade


class GatewayError(OrderRejected):
    """code: gateway error code (docs/contracts/gateway.md) or UNAVAILABLE for transport failures.
    Subclass of OrderRejected so the kill switch keeps closing other positions when one call fails."""

    def __init__(self, code: str, message: str, retcode: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.retcode = code, retcode


class GatewayClient:
    def __init__(self, url: str, token: str, timeout: float = 10.0):
        if not token:
            raise ValueError("MT5_GATEWAY_TOKEN is not set")
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:  # 401 / 404 still carry the JSON envelope
            try:
                resp = json.loads(e.read())
            except ValueError:
                raise GatewayError("UNAVAILABLE", f"HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise GatewayError("UNAVAILABLE", f"{self.url}: {e}") from None
        if not resp.get("ok"):
            err = resp.get("error") or {}
            raise GatewayError(err.get("code", "INTERNAL"), err.get("message", "?"), err.get("retcode"))
        return resp["data"]

    def get(self, path: str, **params):
        return self._call("GET", f"{path}?{urlencode(params)}" if params else path)

    def post(self, path: str, **body):
        return self._call("POST", path, body)


def _utc(epoch: float) -> datetime:
    # shortcut: MT5 epoch fields are broker *server* time, used as-is (consistent with bar times);
    # convert with the server's UTC offset if daily-loss day boundaries must be true UTC.
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class Mt5Broker(Broker):
    def __init__(self, client: GatewayClient, specs: dict[str, SymbolSpec], magic: int, deviation_points: int = 20):
        self.client, self.specs, self.magic, self.deviation = client, specs, magic, deviation_points
        self._known: dict[str, Position] = {}               # our positions seen on the server
        self._meta: dict[str, tuple[float, str]] = {}       # id -> (initial_risk, entry_reason), survives SL trailing

    # --- state ------------------------------------------------------------------
    def restore(self, balance: float, positions: list[Position]) -> None:
        """Balance comes from the server; persisted positions only provide R basis + reason, and any that
        closed while the bot was down are reported by the next on_price()."""
        self._meta = {p.id: (p.initial_risk, p.entry_reason) for p in positions}
        self._known = {p.id: p for p in positions}

    @property
    def balance(self) -> float:
        return self.account().balance

    def account(self) -> AccountInfo:
        a = self.client.get("/health")
        return AccountInfo(a["balance"], a["equity"], a["margin"], a["equity"] - a["balance"])

    def _to_position(self, d: dict) -> Position:
        pid, spec = str(d["ticket"]), self.specs[d["symbol"]]
        risk, reason = self._meta.get(pid) or (
            abs(d["price_open"] - d["sl"]) * spec.contract_size * d["volume"] if d["sl"] else 0.0, d["comment"])
        return Position(id=pid, symbol=d["symbol"], side=d["side"], lots=d["volume"], entry_price=d["price_open"],
                        sl=d["sl"], tp=d["tp"] or None, open_time=_utc(d["time"]), initial_risk=risk,
                        entry_reason=reason or "external", swap=d["swap"], floating_pnl=d["profit"])

    def positions(self) -> list[Position]:
        out = [self._to_position(d) for d in self.client.get("/positions", magic=self.magic) if d["symbol"] in self.specs]
        self._known.update((p.id, p) for p in out)  # never drop here: on_price() needs to see disappearances
        return out

    # --- prices -----------------------------------------------------------------
    def quote(self, symbol: str) -> tuple[float, float]:
        t = self.client.get("/tick", symbol=symbol)
        return t["bid"], t["ask"]

    def set_quote(self, bar: Bar, price: float | None = None) -> None:
        """Live fills use the server's tick, never bar prices."""

    # --- orders -----------------------------------------------------------------
    def open(self, order: Order) -> Position:
        spec = self.specs[order.symbol]
        r = self.client.post("/order", symbol=order.symbol, side=order.side, volume=order.lots, sl=order.sl,
                             tp=order.tp, magic=self.magic, deviation=self.deviation, comment=order.reason[:31])
        lots, price = r["volume"] or order.lots, r["price"]
        pos = Position(id=str(r["ticket"]), symbol=order.symbol, side=order.side, lots=lots, entry_price=price,
                       sl=order.sl, tp=order.tp, open_time=datetime.now(timezone.utc),
                       initial_risk=abs(price - order.sl) * spec.contract_size * lots, entry_reason=order.reason)
        self._meta[pos.id] = (pos.initial_risk, pos.entry_reason)
        self._known[pos.id] = pos
        return pos

    def modify(self, position_id: str, sl: float | None, tp: float | None) -> None:
        self.client.post("/modify", ticket=int(position_id), magic=self.magic, sl=sl, tp=tp)
        if p := self._known.get(position_id):
            p.sl, p.tp = (p.sl if sl is None else sl), (p.tp if tp is None else tp)

    def close(self, position_id: str, reason: str) -> Trade:
        pos = self._known.get(position_id) or next(p for p in self.positions() if p.id == position_id)
        r = self.client.post("/close", ticket=int(position_id), magic=self.magic, deviation=self.deviation)
        trade = self._trade(pos, reason)
        if trade is None:  # deal not in history yet: fall back to the fill price
            gross = self.specs[pos.symbol].pnl(pos.side, pos.entry_price, r["price"], pos.lots)
            net = gross + pos.swap
            trade = Trade(pos, r["price"], datetime.now(timezone.utc), reason, gross, net,
                          net / pos.initial_risk if pos.initial_risk else 0.0)
        self._forget(position_id)
        return trade

    def _forget(self, pid: str) -> None:
        self._known.pop(pid, None)
        self._meta.pop(pid, None)

    def _trade(self, pos: Position, reason: str | None = None) -> Trade | None:
        """Trade from the deal history; None if the closing deal is not visible yet."""
        deals = self.client.get("/deals", position=int(pos.id))
        outs = [d for d in deals if d["entry"] == "OUT"]
        if not outs:
            return None
        last = outs[-1]
        gross = sum(d["profit"] for d in deals)
        pos.commission = sum(d["commission"] + d.get("fee", 0.0) for d in deals)
        pos.swap = sum(d["swap"] for d in deals)
        pos.floating_pnl = 0.0
        net = gross + pos.commission + pos.swap
        reason = reason or (last["reason"] if last["reason"] in ("SL", "TP") else "MANUAL")
        return Trade(pos, last["price"], _utc(last["time"]), reason, gross, net,
                     net / pos.initial_risk if pos.initial_risk else 0.0)

    # --- sync -------------------------------------------------------------------
    def on_price(self, bar: Bar) -> list[Trade]:
        """Report our positions that disappeared from the server (SL/TP hit, stop-out, closed by hand)."""
        live = {p.id for p in self.positions()}
        trades = []
        for pid in [i for i in self._known if i not in live]:
            if t := self._trade(self._known[pid]):
                trades.append(t)
                self._forget(pid)
        return trades
