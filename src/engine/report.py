"""Backtest metrics + files (summary.json, trades.csv)."""
import csv
import json
from pathlib import Path

from src.models import Trade


def metrics(trades: list[Trade], equity: list[tuple], initial_balance: float) -> dict:
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl <= 0]
    peak, max_dd = initial_balance, 0.0
    for _, e in equity:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak if peak > 0 else 0.0)
    net = sum(t.net_pnl for t in trades)
    total_r = sum(t.r_multiple for t in trades)
    gross_loss = -sum(losses)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(sum(wins) / gross_loss, 3) if gross_loss else (float("inf") if wins else 0.0),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "total_r": round(total_r, 2),
        "avg_r": round(total_r / len(trades), 3) if trades else 0.0,
        "net_pnl": round(net, 2),
        "final_balance": round(initial_balance + net, 2),
    }


def write(out_dir: str | Path, summary: dict, trades: list[Trade]) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    with open(out / "trades.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "side", "lots", "entry_price", "exit_price", "sl", "tp", "open_time", "exit_time",
                    "commission", "slippage_cost", "gross_pnl", "net_pnl", "r_multiple", "entry_reason", "exit_reason"])
        for t in trades:
            p = t.position
            w.writerow([p.symbol, p.side, p.lots, p.entry_price, t.exit_price, p.sl, p.tp, p.open_time.isoformat(),
                        t.exit_time.isoformat(), round(p.commission, 2), round(p.slippage_cost, 2),
                        round(t.gross_pnl, 2), round(t.net_pnl, 2), round(t.r_multiple, 3),
                        p.entry_reason, t.exit_reason])
    return out
