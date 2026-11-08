"""Decision memory + 5-day reflection (TradingAgents style). One row per (day, symbol) daily bias;
after `horizon` newer daily decisions the bias is scored in ATR units and a lesson is stored."""
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Callable

from src.strategy.daily_bias import direction

log = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, symbol TEXT, score INTEGER,
    llm_rating TEXT, final_rating TEXT, reason TEXT, close REAL, atr REAL, settled INTEGER DEFAULT 0,
    move_atr REAL, correct INTEGER, UNIQUE(day, symbol));
CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER, day TEXT,
    symbol TEXT, text TEXT);
"""


def default_lesson(d: dict) -> str:
    verdict = "netral" if d["correct"] is None else "benar" if d["correct"] else "salah"
    return f"{d['day']} {d['symbol']} {d['final_rating']} (skor {d['score']}): {d['move_atr']:+.2f} ATR dalam 5 hari -> {verdict}"


class ReflectionStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def record(self, day: date, symbol: str, score: int, final_rating: str, close: float, atr: float,
               llm_rating: str | None = None, reason: str = "") -> None:
        with self.conn:  # IGNORE: paper restarts replay history and must not rewrite past decisions
            self.conn.execute("INSERT OR IGNORE INTO decisions(day, symbol, score, llm_rating, final_rating, reason,"
                              " close, atr) VALUES (?,?,?,?,?,?,?,?)",
                              (str(day), symbol, score, llm_rating, final_rating, reason, close, atr))

    def settle(self, symbol: str, horizon: int = 5, writer: Callable[[dict], str] | None = None) -> list[dict]:
        """Score unsettled decisions that have >= horizon newer decisions, against the close `horizon` days later."""
        rows = self.conn.execute("SELECT * FROM decisions WHERE symbol = ? ORDER BY day", (symbol,)).fetchall()
        done = []
        with self.conn:
            for i, r in enumerate(rows[:-horizon] if horizon else rows):
                if r["settled"]:
                    continue
                d = dict(r)
                dirn = direction(d["final_rating"])
                move = (rows[i + horizon]["close"] - d["close"]) / d["atr"] if d["atr"] > 0 else 0.0
                d["move_atr"] = move * dirn if dirn else move
                d["correct"] = None if dirn == 0 else d["move_atr"] > 0
                try:
                    text = writer(d) if writer else default_lesson(d)
                except Exception as e:  # noqa: BLE001 - an LLM writer failing must not block settlement
                    log.warning("lesson writer failed: %s", e)
                    text = default_lesson(d)
                self.conn.execute("UPDATE decisions SET settled = 1, move_atr = ?, correct = ? WHERE id = ?",
                                  (d["move_atr"], d["correct"], d["id"]))
                self.conn.execute("INSERT INTO lessons(decision_id, day, symbol, text) VALUES (?,?,?,?)",
                                  (d["id"], d["day"], symbol, text))
                done.append(d)
        return done

    def lessons(self, n: int = 5, symbol: str | None = None) -> list[str]:
        q = "SELECT text FROM lessons" + (" WHERE symbol = ?" if symbol else "") + " ORDER BY day DESC, id DESC LIMIT ?"
        return [r[0] for r in self.conn.execute(q, (symbol, n) if symbol else (n,))]
