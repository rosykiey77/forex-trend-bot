#!/usr/bin/env python3
"""Watch forex-trend-bot trades table for new closed trades and print Telegram alerts."""
import os
import sqlite3
import sys

STATE_FILE = "/home/ubuntu/forex-trend-bot/data/last_trade_id.txt"
DB_PATH = "/home/ubuntu/forex-trend-bot/data/paper.db"

last_id = 0
if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE) as f:
            last_id = int(f.read().strip() or "0")
    except Exception:
        last_id = 0

if not os.path.exists(DB_PATH):
    sys.exit(0)

try:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    cur = con.cursor()
    cur.execute(
        "SELECT id, symbol, side, lots, entry_time, entry_price, exit_time, exit_price, pnl, exit_reason "
        "FROM trades WHERE id > ? ORDER BY id ASC",
        (last_id,),
    )
    rows = cur.fetchall()
    con.close()
except Exception:
    sys.exit(0)

if not rows:
    sys.exit(0)

max_id = last_id
for r in rows:
    t_id, sym, side, lots, e_time, e_price, x_time, x_price, pnl, reason = r
    max_id = max(max_id, t_id)
    emoji = "🟢" if pnl >= 0 else "🔴"
    print(
        f"{emoji} *FOREX PAPER TRADE EXIT*\n"
        f"📊 *Symbol:* `{sym}` | *Direction:* `{side}`\n"
        f"📦 *Volume:* `{lots:.2f} lots`\n"
        f"💵 *Entry:* `{e_price:.5f}` ➔ *Exit:* `{x_price:.5f}`\n"
        f"💰 *Realized PnL:* `${pnl:+.2f}` | *Reason:* `{reason}`"
    )

with open(STATE_FILE, "w") as f:
    f.write(str(max_id))
