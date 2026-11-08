#!/usr/bin/env bash
# Wrapper: sync live feed, then check trade watcher, output delivered to channel
python3 /home/ubuntu/forex-trend-bot/scripts/sync_live_feed.py >/dev/null 2>&1
OUT=$(python3 /home/ubuntu/forex-trend-bot/scripts/watch_forex_trades.py)
if [ -n "$OUT" ]; then
    echo "$OUT"
else
    echo "[SILENT]"
fi
