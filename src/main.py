"""CLI: python -m src.main --mode backtest --data tests/fixtures (see docs/contracts/cli.md)."""
import argparse
import logging
import os
import signal
import sys
from datetime import datetime, timezone

from config import settings
from src.broker.paper_broker import PaperBroker
from src.data.csv_feed import CsvFeed
from src.engine import report
from src.engine.backtest import BacktestEngine
from src.engine.paper_runner import PaperRunner, PollingCsvFeed
from src.broker.mt5_broker import GatewayClient, GatewayError, Mt5Broker
from src.data.mt5_feed import Mt5Feed
from src.engine.live_runner import LiveRunner
from src.notify.telegram import TelegramNotifier, load_dotenv
from src.risk.risk_manager import RiskManager
from src.storage.db import Storage
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


def run_paper(cfg, data_dir=None, db=None, max_cycles=None) -> int:
    """Live paper loop until Ctrl-C/SIGTERM (exit 0, state kept) or kill switch (exit 3)."""
    storage = Storage(db or cfg.paper.db, mode="paper")
    notifier = TelegramNotifier.from_env(on_fail=lambda m: storage.log_event("notify_failed", m, "WARNING"))
    runner = PaperRunner(cfg, PollingCsvFeed(data_dir or cfg.paper.data_dir, cfg.symbols, cfg.timeframe),
                         storage, notifier, cfg.paper.poll_seconds)
    return _run(runner, storage, max_cycles)


def run_live(cfg, confirm_live: bool, db=None, max_cycles=None, input_fn=input, client=None) -> int:
    """Exit 2 = refused by a live guard, 1 = gateway unreachable, else like run_paper."""
    if not confirm_live or not cfg.live.live_enabled:
        print("refusing live mode: needs BOTH `live.live_enabled: true` in the config AND the --confirm-live flag",
              file=sys.stderr)
        return 2
    load_dotenv()
    try:
        client = client or GatewayClient(cfg.live.gateway_url, os.getenv("MT5_GATEWAY_TOKEN", ""), cfg.live.timeout_seconds)
        acc = client.get("/health")
    except (ValueError, GatewayError) as e:
        print(f"error: MT5 gateway {cfg.live.gateway_url} not usable ({e}).\n"
              "Start it next to the MT5 terminal: set MT5_GATEWAY_TOKEN=... && python gateway/mt5_gateway.py "
              "--port 8765, tunnel the port, and put the same token in .env. Backtest/paper still work offline.",
              file=sys.stderr)
        return 1
    kind = "DEMO" if acc["demo"] else f"*** {acc['trade_mode'].upper()} MONEY ***"
    print(f"Account : {acc['login']} ({kind})   Name : {acc['name']}   Broker : {acc['broker']}\n"
          f"Server  : {acc['server']}   Balance : {acc['balance']:.2f} {acc['currency']}   "
          f"Equity : {acc['equity']:.2f}   Magic : {cfg.live.magic}")
    try:
        answer = input_fn("Type 'yes' to start LIVE trading: ")
    except EOFError:
        answer = ""
    if answer.strip() != "yes":
        print("live start cancelled", file=sys.stderr)
        return 2
    feed = Mt5Feed(client, cfg.symbols, cfg.timeframe, cfg.live.history_bars)
    feed.symbols = feed.specs()
    broker = Mt5Broker(client, feed.symbols, cfg.live.magic, cfg.live.deviation_points)
    storage = Storage(db or cfg.live.db, run_id="live", mode="live")
    storage.log_event("account", f"{acc['login']} {acc['server']} {acc['trade_mode']} balance {acc['balance']:.2f}")
    notifier = TelegramNotifier.from_env(on_fail=lambda m: storage.log_event("notify_failed", m, "WARNING"))
    runner = LiveRunner(cfg, feed, storage, notifier, cfg.live.poll_seconds, broker=broker)
    return _run(runner, storage, max_cycles)


def _run(runner, storage, max_cycles) -> int:
    old = {s: signal.signal(s, lambda *_: runner.stop()) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        return runner.run(max_cycles)
    finally:
        for s, h in old.items():
            signal.signal(s, h)
        storage.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forexbot")
    ap.add_argument("--mode", choices=["backtest", "paper", "live"], required=True)
    ap.add_argument("--config", default="config/config.yaml")
    ap.add_argument("--data", help="CSV folder (backtest default data/csv, paper default paper.data_dir)")
    ap.add_argument("--db", help="state DB (default paper.db / live.db from config)")
    ap.add_argument("--confirm-live", action="store_true", help="required for --mode live")
    ap.add_argument("--from", dest="start", type=_date)
    ap.add_argument("--to", dest="end", type=_date)
    ap.add_argument("--log-level", default="INFO")
    a = ap.parse_args(argv)
    logging.basicConfig(level=a.log_level.upper(), stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        cfg = settings.load(a.config)
        if a.mode == "live":
            return run_live(cfg, a.confirm_live, a.db)
        if a.mode == "paper":
            return run_paper(cfg, a.data, a.db)
        summary, result = run_backtest(cfg, a.data or "data/csv", a.start, a.end)
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
