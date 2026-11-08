"""Simulated broker for backtest/paper (docs/research.md R5).

Bar prices are bid; ask = bid + spread. BUY opens at ask and closes at bid, SELL the reverse.
Slippage (slippage_points) always works against us on market fills and stop exits; TP fills exactly.
Gap: if a bar opens beyond SL/TP the exit fills at the open. SL and TP in the same bar -> SL (conservative).
"""
import itertools

from src.broker.base import Broker, OrderRejected
from src.models import AccountInfo, Bar, Order, Position, SymbolSpec, Trade


class PaperBroker(Broker):
    def __init__(self, specs: dict[str, SymbolSpec], initial_balance: float, leverage: float = 100.0):
        self.specs = specs
        self.balance = float(initial_balance)
        self.leverage = leverage
        self._positions: dict[str, Position] = {}
        self._quote: dict[str, tuple[float, float, object]] = {}  # symbol -> (bid, ask, time)
        self._ids = itertools.count(1)  # deterministic ids for reproducible backtests

    def restore(self, balance: float, positions: list[Position]) -> None:
        """Load persisted state after a restart (src/storage/db.py)."""
        self.balance = balance
        self._positions = {p.id: p for p in positions}
        self._ids = itertools.count(max((int(p.id) for p in positions), default=0) + 1)

    # --- prices -----------------------------------------------------------------
    def _spread(self, bar: Bar) -> float:
        spec = self.specs[bar.symbol]
        pts = bar.spread_points if bar.spread_points is not None else spec.default_spread_points
        return pts * spec.point

    def set_quote(self, bar: Bar, price: float | None = None) -> None:
        """Set the current bid (default: bar open) used for market fills."""
        bid = bar.open if price is None else price
        self._quote[bar.symbol] = (bid, bid + self._spread(bar), bar.time)

    def quote(self, symbol: str) -> tuple[float, float]:
        if symbol not in self._quote:
            raise OrderRejected(f"no price for {symbol}")
        bid, ask, _ = self._quote[symbol]
        return bid, ask

    # --- account ----------------------------------------------------------------
    def _margin(self, p: Position) -> float:
        # shortcut: margin in quote ccy == account ccy (USD-quoted symbols only).
        return p.lots * self.specs[p.symbol].contract_size * p.entry_price / self.leverage

    def account(self) -> AccountInfo:
        floating = sum(p.floating_pnl for p in self._positions.values())
        margin = sum(self._margin(p) for p in self._positions.values())
        return AccountInfo(self.balance, self.balance + floating, margin, floating)

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    # --- orders -----------------------------------------------------------------
    def open(self, order: Order) -> Position:
        spec = self.specs[order.symbol]
        if order.lots <= 0:
            raise OrderRejected("lots must be > 0")
        if order.side not in ("BUY", "SELL"):
            raise OrderRejected(f"invalid side {order.side}")
        bid, ask = self.quote(order.symbol)
        slip = spec.slippage_points * spec.point
        price = ask + slip if order.side == "BUY" else bid - slip
        if (order.side == "BUY" and order.sl >= price) or (order.side == "SELL" and order.sl <= price):
            raise OrderRejected(f"SL {order.sl} on wrong side of fill {price}")
        commission = spec.commission_per_lot * order.lots
        pos = Position(
            id=str(next(self._ids)), symbol=order.symbol, side=order.side, lots=order.lots,
            entry_price=price, sl=order.sl, tp=order.tp, open_time=self._quote[order.symbol][2],
            initial_risk=abs(price - order.sl) * spec.contract_size * order.lots,
            entry_reason=order.reason, commission=-commission,
            slippage_cost=slip * spec.contract_size * order.lots,
        )
        acc = self.account()
        if self._margin(pos) > acc.free_margin - commission:
            raise OrderRejected("insufficient free margin")
        self.balance -= commission  # charged on entry, like MT5
        self._positions[pos.id] = pos
        self._mark(pos)
        return pos

    def close(self, position_id: str, reason: str) -> Trade:
        pos = self._positions[position_id]
        spec = self.specs[pos.symbol]
        bid, ask = self.quote(pos.symbol)
        slip = spec.slippage_points * spec.point
        price = bid - slip if pos.side == "BUY" else ask + slip
        return self._close(pos, price, reason, slip)

    def modify(self, position_id: str, sl: float | None, tp: float | None) -> None:
        pos = self._positions[position_id]
        if sl is not None:
            pos.sl = sl
        if tp is not None:
            pos.tp = tp

    def _close(self, pos: Position, price: float, reason: str, slip: float) -> Trade:
        spec = self.specs[pos.symbol]
        pos.slippage_cost += slip * spec.contract_size * pos.lots
        gross = spec.pnl(pos.side, pos.entry_price, price, pos.lots)
        net = gross + pos.commission + pos.swap
        self.balance += gross + pos.swap
        pos.floating_pnl = 0.0
        del self._positions[pos.id]
        return Trade(pos, price, self._quote[pos.symbol][2], reason, gross, net,
                     net / pos.initial_risk if pos.initial_risk else 0.0)

    def _mark(self, pos: Position) -> None:
        bid, ask = self.quote(pos.symbol)
        exit_px = bid if pos.side == "BUY" else ask
        pos.floating_pnl = self.specs[pos.symbol].pnl(pos.side, pos.entry_price, exit_px, pos.lots)

    # --- per bar ----------------------------------------------------------------
    def on_price(self, bar: Bar) -> list[Trade]:
        """Check SL/TP of this symbol's positions against the bar, then mark to market at close."""
        spec = self.specs[bar.symbol]
        slip = spec.slippage_points * spec.point
        spread = self._spread(bar)
        trades = []
        self.set_quote(bar)  # exit_time = this bar
        for pos in [p for p in self._positions.values() if p.symbol == bar.symbol]:
            if pos.side == "BUY":  # exits on bid
                o, hi, lo = bar.open, bar.high, bar.low
                sl_gap, tp_gap = o <= pos.sl, pos.tp is not None and o >= pos.tp
                sl_hit, tp_hit = lo <= pos.sl, pos.tp is not None and hi >= pos.tp
                sl_fill = (o if sl_gap else pos.sl) - slip
            else:  # SELL exits on ask
                o, hi, lo = bar.open + spread, bar.high + spread, bar.low + spread
                sl_gap, tp_gap = o >= pos.sl, pos.tp is not None and o <= pos.tp
                sl_hit, tp_hit = hi >= pos.sl, pos.tp is not None and lo <= pos.tp
                sl_fill = (o if sl_gap else pos.sl) + slip
            if sl_gap or (sl_hit and not tp_gap):
                trades.append(self._close(pos, sl_fill, "SL", slip))
            elif tp_gap or tp_hit:
                trades.append(self._close(pos, o if tp_gap else pos.tp, "TP", 0.0))
        self.set_quote(bar, bar.close)
        for pos in self._positions.values():
            if pos.symbol == bar.symbol:
                self._mark(pos)
        return trades
