# Contract: CLI

Entry point: `python -m src.main` (juga `forexbot` via `[project.scripts]`).

```text
forexbot --mode {backtest,paper,live} [--config config/config.yaml]
         [--data DIR]            # backtest / paper replay: folder CSV {SYMBOL}_{TF}.csv
         [--from YYYY-MM-DD] [--to YYYY-MM-DD]   # backtest window
         [--feed {replay,gateway}]               # paper only; default: gateway jika gateway.url ada, else replay
         [--confirm-live]                        # wajib untuk live
         [--reset-state]                         # paper: mulai dari initial_balance (minta konfirmasi)

forexbot-download --symbol EURUSD --timeframe M15 --from 2025-01-01 --to 2025-12-31 --out data/
                  # tarik data historis lewat gateway → CSV (FR-006)

forexbot-report --db data/paper.db [--run RUN_ID]   # cetak metrik + simpan PNG equity
```

## Exit codes

| Code | Arti |
|---|---|
| 0 | selesai normal (backtest selesai / Ctrl-C bersih) |
| 1 | error konfigurasi / data tidak valid |
| 2 | penolakan pengaman live (flag/config/konfirmasi) |
| 3 | kill switch aktif (STOP file, error berulang, disconnect) |
| 4 | instance lain sedang berjalan (lock) |

## Output

- stdout: log baris `time level kind message` (level INFO default, `--log-level`).
- Backtest: `reports/{run_id}/summary.json`, `reports/{run_id}/equity.png`, `data/backtest_{run_id}.db`.
- Ringkasan metrik dicetak di akhir: `trades, win_rate, profit_factor, max_drawdown_pct, avg_r, net_pnl`.

## Live start dialog

```text
Account : 12345678 (Demo)   Server : Broker-Demo   Balance : 1000.00 USD
Type 'yes' to start LIVE trading: _
```
Selain persis `yes` → exit 2.
