"""One RiskManager for every mode. evaluate() order: kill -> SL -> daily lock -> max positions -> spread -> lot."""
import math
import os
from datetime import datetime

from src.models import AccountInfo, Order, Position, Rejection, Signal, SymbolSpec


class RiskManager:
    def __init__(self, cfg):
        """cfg: config.settings.RiskCfg."""
        self.cfg = cfg
        self.day = None
        self.day_start_equity = 0.0
        self.daily_locked = False
        self.consecutive_errors = 0
        self.kill_reason: str | None = None

    # --- kill switch ------------------------------------------------------------
    def kill(self, reason: str) -> None:
        self.kill_reason = self.kill_reason or reason

    def record_error(self) -> None:
        self.consecutive_errors += 1
        if self.consecutive_errors >= self.cfg.max_consecutive_errors:
            self.kill("errors")

    def record_success(self) -> None:
        self.consecutive_errors = 0

    def check_kill(self, now: datetime | None = None) -> str | None:
        if self.cfg.stop_file and os.path.exists(self.cfg.stop_file):
            self.kill("stop_file")
        return self.kill_reason

    # --- daily loss limit -------------------------------------------------------
    # shortcut: trading day = UTC date; switch to broker-server rollover (clock.py) in Phase 3.
    def update(self, equity: float, now: datetime) -> None:
        """Call on every price update: rolls the day and evaluates the daily loss lock."""
        if now.date() != self.day:
            self.day, self.day_start_equity, self.daily_locked = now.date(), equity, False
        if self.day_start_equity - equity >= self.day_start_equity * self.cfg.daily_loss_limit_pct / 100:
            self.daily_locked = True

    # --- sizing -----------------------------------------------------------------
    def lot_size(self, equity: float, sl_distance: float, spec: SymbolSpec, risk_pct: float | None = None) -> float:
        """Lots risking risk_pct (default/ceiling: risk_per_trade_pct) of equity over sl_distance. 0.0 = skip."""
        pct = self.cfg.risk_per_trade_pct if risk_pct is None else min(risk_pct, self.cfg.risk_per_trade_pct)
        if sl_distance <= 0 or equity <= 0 or pct <= 0:
            return 0.0
        risk_money = equity * pct / 100
        loss_per_lot = sl_distance / spec.pip_size * spec.pip_value_per_lot
        steps = math.floor(round(risk_money / loss_per_lot / spec.volume_step, 9))  # round kills float noise
        lots = round(min(steps * spec.volume_step, spec.volume_max), 8)
        return lots if lots >= spec.volume_min else 0.0

    # --- gate -------------------------------------------------------------------
    def evaluate(self, signal: Signal, spec: SymbolSpec, bid: float, ask: float, spread_points: int,
                 account: AccountInfo, positions: list[Position], now: datetime) -> Order | Rejection:
        if self.check_kill(now):
            return Rejection(f"kill switch: {self.kill_reason}")
        if signal.side not in ("BUY", "SELL"):
            return Rejection(f"not an entry signal: {signal.side}")
        entry = ask if signal.side == "BUY" else bid
        if signal.sl is None:
            return Rejection("missing SL")
        if (signal.side == "BUY" and signal.sl >= entry) or (signal.side == "SELL" and signal.sl <= entry):
            return Rejection(f"invalid SL {signal.sl} for {signal.side} at {entry}")
        if self.daily_locked:
            return Rejection("daily loss limit reached")
        if len(positions) >= self.cfg.max_open_positions:
            return Rejection("max open positions")
        if spread_points > spec.max_spread_points:
            return Rejection(f"spread {spread_points} > max {spec.max_spread_points}")
        lots = self.lot_size(account.equity, abs(entry - signal.sl), spec, signal.risk_pct)
        if lots <= 0:
            return Rejection("lot below volume_min")
        return Order(signal.symbol, signal.side, lots, signal.sl, signal.tp, signal.reason)
