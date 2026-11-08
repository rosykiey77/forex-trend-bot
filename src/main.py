"""CLI: python -m src.main --mode backtest --data tests/fixtures (see docs/contracts/cli.md)."""
import argparse
import logging
import sys
from datetime import datetime, timezone

from config import settings
from src.broker.paper_broker import PaperBroker
from src.data.csv_feed import CsvFeed
from src.engine import report
from src.engine.backtest import BacktestEngine
from src.risk.risk_manager import RiskManager
from src.strategy import STRATEGIES


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def run_backtest(cfg, data_dir, start=None, end=None):
    """Returns (summary dict, BacktestResult)."""
    strategy = STRATEGIES[cfg.strategy.name](cfg.strategy.params)
    feed = CsvFeed(data_dir, cfg.symbols, cfg.timeframe, start, end)
    broker = PaperBroker(cfg.symbols, cfg.account.initial_balance, cfg.account.leverage)
    result = BacktestEngine(feed.bars(), strategy, broker, RiskManager(cfg.risk)).run()
    summary = report.metrics(result.trades, result.equity, cfg.account.initial_balance)
    summary["rejections"] = len(result.rejections)
    summary["kill_reason"] = result.kill_reason
    return summary, result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forexbot")
    ap.add_argument("--mode", choices=["backtest", "paper", "live"], required=True)
    ap.add_argument("--config", default="config/config.yaml")
    ap.add_argument("--data", default="data/csv")
    ap.add_argument("--from", dest="start", type=_date)
    ap.add_argument("--to", dest="end", type=_date)
    ap.add_argument("--log-level", default="INFO")
    a = ap.parse_args(argv)
    logging.basicConfig(level=a.log_level.upper(), stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if a.mode != "backtest":
        print(f"mode {a.mode} is not implemented yet (Phase 3+)", file=sys.stderr)
        return 1
    try:
        cfg = settings.load(a.config)
        summary, result = run_backtest(cfg, a.data, a.start, a.end)
    except (ValueError, FileNotFoundError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = report.write(f"{cfg.reports_dir}/{run_id}", summary, result.trades)
    print("\n=== Backtest summary ===")
    for k, v in summary.items():
        print(f"{k:>17}: {v}")
    print(f"report: {out}")
    return 3 if result.kill_reason else 0


if __name__ == "__main__":
    sys.exit(main())
