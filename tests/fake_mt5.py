"""In-memory stand-in for the parts of the `MetaTrader5` package the gateway uses (constants match MT5)."""
from types import SimpleNamespace as NS

T0 = 1736121600  # 2025-01-06 00:00 UTC


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M15, TIMEFRAME_H1 = 1, 15, 16385
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL, TRADE_RETCODE_INVALID_STOPS = 10009, 10010, 10016
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
    DEAL_REASON_CLIENT, DEAL_REASON_EXPERT, DEAL_REASON_SL, DEAL_REASON_TP, DEAL_REASON_SO = 0, 3, 4, 5, 6
    COMMISSION = 3.5  # per lot per side

    def __init__(self, trade_mode: int = 0, logged_in: bool = True):
        self.logged_in, self.trade_mode, self.initialized = logged_in, trade_mode, False
        self.balance = 1000.0
        self.symbols = {"EURUSD": NS(name="EURUSD", point=1e-5, digits=5, trade_contract_size=100000.0,
                                     volume_min=0.01, volume_max=50.0, volume_step=0.01, spread=10, filling_mode=2)}
        self.ticks = {"EURUSD": NS(time=T0 + 900 * 100, bid=1.10000, ask=1.10010)}
        self.rates = {"EURUSD": [
            {"time": T0 + 900 * i, "open": 1.1, "high": 1.1005, "low": 1.0995, "close": 1.1 + i * 1e-5,
             "tick_volume": 100, "spread": 10} for i in range(100)]}
        self.pos: dict[int, NS] = {}
        self.history: list[NS] = []
        self.requests: list[dict] = []
        self.reject_next = None  # retcode to answer the next order_send with
        self._ticket = 5000

    # --- terminal / account -------------------------------------------------------
    def initialize(self, *a, **k):
        self.initialized = True
        return True

    def shutdown(self):
        self.initialized = False

    def last_error(self):
        return (1, "Success")

    def account_info(self):
        if not (self.initialized and self.logged_in):
            return None
        profit = sum(p.profit for p in self.pos.values())
        return NS(login=12345678, server="FakeBroker-Demo", company="Fake Broker Ltd", name="Test Trader",
                  currency="USD", trade_mode=self.trade_mode, leverage=100, balance=self.balance,
                  equity=self.balance + profit, margin=0.0, margin_free=self.balance + profit)

    # --- market data --------------------------------------------------------------
    def symbol_select(self, name, enable=True):
        return name in self.symbols

    def symbol_info(self, name):
        return self.symbols.get(name)

    def symbol_info_tick(self, name):
        return self.ticks.get(name)

    def copy_rates_from_pos(self, symbol, tf, start, count):
        rates = self.rates[symbol]
        end = len(rates) - start
        return rates[max(0, end - count):end]

    # --- trading ------------------------------------------------------------------
    def positions_get(self, ticket=None, **k):
        return tuple(p for p in self.pos.values() if ticket is None or p.ticket == ticket)

    def history_deals_get(self, position=None, **k):
        return tuple(d for d in self.history if position is None or d.position_id == position)

    def _deal(self, pos, entry, price, volume, profit, reason):
        self._ticket += 1
        self.history.append(NS(ticket=self._ticket, position_id=pos.ticket, time=self.ticks[pos.symbol].time,
                               price=price, volume=volume, profit=profit, commission=-self.COMMISSION * volume,
                               swap=0.0, fee=0.0, magic=pos.magic, entry=entry, reason=reason))
        self.balance += profit - self.COMMISSION * volume

    def order_send(self, req):
        self.requests.append(req)
        if self.reject_next:
            code, self.reject_next = self.reject_next, None
            return NS(retcode=code, comment="Invalid stops", order=0, deal=0, price=0.0, volume=0.0)
        if req["action"] == self.TRADE_ACTION_SLTP:
            p = self.pos[req["position"]]
            p.sl, p.tp = req["sl"], req["tp"]
            return NS(retcode=self.TRADE_RETCODE_DONE, comment="done", order=0, deal=0, price=0.0, volume=0.0)
        if "position" in req:  # closing deal
            p = self.pos.pop(req["position"])
            self._close(p, req["price"], self.DEAL_REASON_EXPERT)
            return NS(retcode=self.TRADE_RETCODE_DONE, comment="done", order=0, deal=0, price=req["price"],
                      volume=p.volume)
        self._ticket += 1
        p = NS(ticket=self._ticket, symbol=req["symbol"], volume=req["volume"], price_open=req["price"],
               type=self.POSITION_TYPE_BUY if req["type"] == self.ORDER_TYPE_BUY else self.POSITION_TYPE_SELL,
               sl=req["sl"], tp=req["tp"], time=self.ticks[req["symbol"]].time, profit=0.0, swap=0.0,
               magic=req["magic"], comment=req.get("comment", ""))
        self.pos[p.ticket] = p
        self._deal(p, self.DEAL_ENTRY_IN, p.price_open, p.volume, 0.0, self.DEAL_REASON_EXPERT)
        return NS(retcode=self.TRADE_RETCODE_DONE, comment="done", order=p.ticket, deal=0, price=p.price_open,
                  volume=p.volume)

    # --- test helpers ---------------------------------------------------------------
    def _close(self, p, price, reason):
        diff = price - p.price_open if p.type == self.POSITION_TYPE_BUY else p.price_open - price
        self._deal(p, self.DEAL_ENTRY_OUT, price, p.volume,
                   round(diff * self.symbols[p.symbol].trade_contract_size * p.volume, 2), reason)

    def add_manual_position(self, magic=0):
        self._ticket += 1
        p = NS(ticket=self._ticket, symbol="EURUSD", volume=0.1, price_open=1.1, type=0, sl=0.0, tp=0.0,
               time=T0, profit=0.0, swap=0.0, magic=magic, comment="manual")
        self.pos[p.ticket] = p
        return p.ticket

    def server_close(self, ticket, at="sl"):
        """Simulate the server hitting SL or TP."""
        p = self.pos.pop(ticket)
        self._close(p, p.sl if at == "sl" else p.tp, self.DEAL_REASON_SL if at == "sl" else self.DEAL_REASON_TP)

    def add_bar(self, close):
        last = self.rates["EURUSD"][-1]
        self.rates["EURUSD"].append({**last, "time": last["time"] + 900, "open": last["close"], "close": close,
                                     "high": max(last["close"], close), "low": min(last["close"], close)})
