"""Domain objects shared by every mode (see docs/data-model.md). All times are tz-aware UTC."""
from dataclasses import dataclass, field
from datetime import datetime

SIDES = ("BUY", "SELL", "CLOSE")
EXIT_REASONS = ("TP", "SL", "SIGNAL", "KILL", "MANUAL", "END_OF_DATA")


@dataclass(slots=True)
class Bar:
    symbol: str
    time: datetime          # bar open time; prices are bid
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    spread_points: int | None = None


@dataclass(slots=True)
class Tick:
    symbol: str
    time: datetime
    bid: float
    ask: float


@dataclass(slots=True, frozen=True)
class SymbolSpec:
    name: str
    pip_size: float
    point: float
    digits: int
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    default_spread_points: int
    max_spread_points: int
    slippage_points: int
    commission_per_lot: float   # round-turn, account ccy

    # shortcut: assumes quote ccy == account ccy (true for EURUSD/XAUUSD in USD); add conv_rate for other pairs.
    @property
    def pip_value_per_lot(self) -> float:
        return self.pip_size * self.contract_size

    def pnl(self, side: str, entry: float, exit: float, lots: float) -> float:
        diff = exit - entry if side == "BUY" else entry - exit
        return diff * self.contract_size * lots


@dataclass(slots=True)
class Signal:
    symbol: str
    side: str
    sl: float | None = None
    tp: float | None = None
    reason: str = ""

    def __post_init__(self):
        if self.side not in SIDES:
            raise ValueError(f"invalid side {self.side!r}")
        if not self.reason:
            raise ValueError("signal reason must be non-empty")


@dataclass(slots=True)
class Order:
    symbol: str
    side: str
    lots: float
    sl: float
    tp: float | None
    reason: str


@dataclass(slots=True)
class Rejection:
    reason: str


@dataclass(slots=True)
class Position:
    id: str
    symbol: str
    side: str
    lots: float
    entry_price: float
    sl: float
    tp: float | None
    open_time: datetime
    initial_risk: float         # account ccy lost if SL hit at its price; basis of R
    entry_reason: str
    commission: float = 0.0     # <= 0
    swap: float = 0.0
    slippage_cost: float = 0.0  # >= 0, informational
    floating_pnl: float = 0.0


@dataclass(slots=True)
class Trade:
    position: Position
    exit_price: float
    exit_time: datetime
    exit_reason: str
    gross_pnl: float
    net_pnl: float
    r_multiple: float


@dataclass(slots=True)
class AccountInfo:
    balance: float
    equity: float
    margin_used: float
    floating_pnl: float
    free_margin: float = field(init=False)

    def __post_init__(self):
        self.free_margin = self.equity - self.margin_used
