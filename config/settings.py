"""Load and validate config/config.yaml. Secrets never live here: read them from env (see .env.example)."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.models import SymbolSpec


@dataclass(frozen=True)
class AccountCfg:
    currency: str = "USD"
    initial_balance: float = 1000.0
    leverage: float = 100.0


@dataclass(frozen=True)
class RiskCfg:
    risk_per_trade_pct: float = 1.0
    daily_loss_limit_pct: float = 3.0
    max_open_positions: int = 2
    max_consecutive_errors: int = 5
    stop_file: str = "STOP"
    trailing_stop_r: float = 0.0   # trail SL at N x initial SL distance; 0 = off


@dataclass(frozen=True)
class PaperCfg:
    data_dir: str = "data/live"    # folder polled for {SYMBOL}_{TF}.csv
    db: str = "data/paper.db"
    poll_seconds: float = 10.0     # also the STOP-file reaction time (spec SC-005: <= 60 s)


@dataclass(frozen=True)
class StrategyCfg:
    name: str = "ema_atr"
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    account: AccountCfg
    risk: RiskCfg
    strategy: StrategyCfg
    symbols: dict[str, SymbolSpec]
    timeframe: str = "M15"
    reports_dir: str = "reports"
    paper: PaperCfg = field(default_factory=PaperCfg)


def _build(cls, section: str, data: dict | None, **extra):
    try:
        return cls(**(data or {}), **extra)
    except TypeError as e:  # missing / unknown key
        raise ValueError(f"config [{section}]: {e}") from None


def load(path: str | Path = "config/config.yaml") -> Settings:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    risk = _build(RiskCfg, "risk", raw.get("risk"))
    if not 0 < risk.risk_per_trade_pct <= 5:
        raise ValueError("config [risk]: risk_per_trade_pct must be in (0, 5]")
    if not 0 < risk.daily_loss_limit_pct <= 100:
        raise ValueError("config [risk]: daily_loss_limit_pct must be in (0, 100]")
    if risk.trailing_stop_r < 0:
        raise ValueError("config [risk]: trailing_stop_r must be >= 0")
    if risk.max_open_positions < 1:
        raise ValueError("config [risk]: max_open_positions must be >= 1")
    account = _build(AccountCfg, "account", raw.get("account"))
    if account.initial_balance <= 0 or account.leverage <= 0:
        raise ValueError("config [account]: initial_balance and leverage must be > 0")
    if not raw.get("symbols"):
        raise ValueError("config: at least one symbol is required")
    symbols = {n: _build(SymbolSpec, f"symbols.{n}", s, name=n) for n, s in raw["symbols"].items()}
    for s in symbols.values():
        if min(s.pip_size, s.point, s.contract_size, s.volume_min, s.volume_step) <= 0 or s.volume_max < s.volume_min:
            raise ValueError(f"config [symbols.{s.name}]: sizes must be > 0 and volume_max >= volume_min")
    return Settings(
        account=account,
        risk=risk,
        strategy=_build(StrategyCfg, "strategy", raw.get("strategy")),
        symbols=symbols,
        timeframe=raw.get("timeframe", "M15"),
        reports_dir=(raw.get("reports") or {}).get("dir", "reports"),
        paper=_build(PaperCfg, "paper", raw.get("paper")),
    )
