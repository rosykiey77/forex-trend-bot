"""SQLite journal + state (docs/data-model.md). One save() per processed cycle = one transaction,
so a crash leaves either the old or the new state, never a half-closed position."""
import sqlite3
from dataclasses import asdict, fields
from datetime import date, datetime, timezone
from pathlib import Path

from src.models import Position, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS account(id INTEGER PRIMARY KEY CHECK(id=1), balance REAL, day_start_equity REAL,
    day TEXT, daily_locked INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY, symbol TEXT, side TEXT, lots REAL, entry_price REAL,
    sl REAL, tp REAL, open_time TEXT, initial_risk REAL, entry_reason TEXT, commission REAL, swap REAL,
    slippage_cost REAL, floating_pnl REAL);
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT, position_id TEXT, run_id TEXT, mode TEXT,
    symbol TEXT, side TEXT, lots REAL, entry_price REAL, exit_price REAL, sl REAL, tp REAL, open_time TEXT,
    exit_time TEXT, commission REAL, swap REAL, slippage_cost REAL, gross_pnl REAL, net_pnl REAL,
    r_multiple REAL, entry_reason TEXT, exit_reason TEXT);
CREATE TABLE IF NOT EXISTS equity(run_id TEXT, time TEXT, balance REAL, equity REAL, PRIMARY KEY(run_id, time));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, level TEXT, kind TEXT,
    message TEXT);
"""
POS_COLS = [f.name for f in fields(Position)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str | Path, run_id: str = "paper", mode: str = "paper"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)
        self.run_id, self.mode = run_id, mode

    def close(self) -> None:
        self.conn.close()

    # --- meta / events ----------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def log_event(self, kind: str, message: str, level: str = "INFO") -> None:
        with self.conn:
            self.conn.execute("INSERT INTO events(time, level, kind, message) VALUES (?, ?, ?, ?)",
                              (_now(), level, kind, message))

    def events(self, kind: str | None = None) -> list[tuple]:
        q = "SELECT time, level, kind, message FROM events" + (" WHERE kind = ?" if kind else "") + " ORDER BY id"
        return self.conn.execute(q, (kind,) if kind else ()).fetchall()

    # --- state ------------------------------------------------------------------
    def save(self, balance: float, positions: list[Position], trades: list[Trade], risk=None,
             equity: tuple[datetime, float] | None = None, last_bars: dict[str, datetime] | None = None) -> None:
        """Atomically: append closed trades, replace open positions, update account (+ risk day state)."""
        with self.conn:
            c = self.conn
            for t in trades:
                p = t.position
                c.execute("INSERT INTO trades(position_id, run_id, mode, symbol, side, lots, entry_price, exit_price,"
                          " sl, tp, open_time, exit_time, commission, swap, slippage_cost, gross_pnl, net_pnl,"
                          " r_multiple, entry_reason, exit_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (p.id, self.run_id, self.mode, p.symbol, p.side, p.lots, p.entry_price, t.exit_price,
                           p.sl, p.tp, p.open_time.isoformat(), t.exit_time.isoformat(), p.commission, p.swap,
                           p.slippage_cost, t.gross_pnl, t.net_pnl, t.r_multiple, p.entry_reason, t.exit_reason))
            c.execute("DELETE FROM positions")
            for p in positions:
                d = asdict(p)
                d["open_time"] = p.open_time.isoformat()
                c.execute(f"INSERT INTO positions({','.join(POS_COLS)}) VALUES ({','.join('?' * len(POS_COLS))})",
                          [d[k] for k in POS_COLS])
            c.execute("INSERT OR REPLACE INTO account VALUES (1, ?, ?, ?, ?, ?)",
                      (balance, risk.day_start_equity if risk else None,
                       risk.day.isoformat() if risk and risk.day else None,
                       int(bool(risk and risk.daily_locked)), _now()))
            if equity:
                c.execute("INSERT OR REPLACE INTO equity VALUES (?, ?, ?, ?)",
                          (self.run_id, equity[0].isoformat(), balance, equity[1]))
            for sym, t in (last_bars or {}).items():
                c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"last_bar:{sym}", t.isoformat()))

    def load_state(self) -> dict | None:
        """None if nothing was ever saved (fresh start)."""
        row = self.conn.execute("SELECT balance, day_start_equity, day, daily_locked FROM account").fetchone()
        if row is None:
            return None
        positions = []
        for r in self.conn.execute(f"SELECT {','.join(POS_COLS)} FROM positions ORDER BY CAST(id AS INTEGER)"):
            d = dict(zip(POS_COLS, r))
            d["open_time"] = datetime.fromisoformat(d["open_time"])
            positions.append(Position(**d))
        last_bars = {k.split(":", 1)[1]: datetime.fromisoformat(v)
                     for k, v in self.conn.execute("SELECT key, value FROM meta WHERE key LIKE 'last_bar:%'")}
        return {"balance": row[0], "day_start_equity": row[1], "day": date.fromisoformat(row[2]) if row[2] else None,
                "daily_locked": bool(row[3]), "positions": positions, "last_bars": last_bars}

    def trades(self) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        try:
            return self.conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
        finally:
            self.conn.row_factory = None
