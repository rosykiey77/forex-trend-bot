# Quickstart & Validation Guide

Rujukan: [CLI](contracts/cli.md), [Gateway](contracts/gateway.md), [Data model](data-model.md).

## Prasyarat

- Linux VPS, Python 3.11+.
- (Live / paper-live) Mesin Windows atau Wine dengan terminal MT5 login + Python Windows + `pip install MetaTrader5`.

## Setup (Linux)

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # ".[zmq]" bila transport ZeroMQ
cp .env.example .env               # isi TELEGRAM_*, MT5_GATEWAY_TOKEN bila dipakai
cp config/config.example.yaml config/config.yaml
```

## V1 — Unit test (bug termahal)

```bash
pytest -q
```
Expected: lulus semua, termasuk `test_sizing.py`, `test_pip_value.py`, `test_paper_broker.py` (PnL, SL/TP, gap, swap), `test_risk.py`, `test_storage.py`.

## V2 — Backtest offline (US1, SC-001/002)

```bash
forexbot --mode backtest --data tests/fixtures/ --from 2024-01-01 --to 2024-12-31
```
Expected: exit 0, `reports/<run_id>/summary.json` + `equity.png`. Jalankan dua kali → `summary.json` identik (kecuali `run_id`).

## V3 — Paper offline replay + restart (US2, SC-006)

```bash
forexbot --mode paper --feed replay --data tests/fixtures/   # Ctrl-C saat ada posisi terbuka
sqlite3 data/paper.db 'select id,symbol,lots from positions; select balance from account;'
forexbot --mode paper --feed replay --data tests/fixtures/   # log "restored N positions, balance X"
```

## V4 — Kill switch & batas risiko (US3, SC-004/005)

```bash
touch STOP     # saat paper berjalan
```
Expected: semua posisi ditutup (`exit_reason=KILL`), event `kill`, notifikasi, exit code 3. Hapus `STOP` sebelum start ulang. Batas harian & max posisi dibuktikan oleh `tests/integration/test_risk_limits.py`.

## V5 — Telegram (US4)

Isi `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; jalankan V3 → pesan entry/exit masuk. Kosongkan token → bot tetap jalan.

## V6 — Gateway & live demo (US5)

Windows:
```bat
pip install MetaTrader5
set MT5_GATEWAY_TOKEN=...  &&  python gateway\mt5_gateway.py --host 127.0.0.1 --port 8765
```
Linux (tunnel): `ssh -N -L 8765:127.0.0.1:8765 user@winvps`, lalu:
```bash
curl -s -H "Authorization: Bearer $MT5_GATEWAY_TOKEN" localhost:8765/health
forexbot --mode live                     # expected: exit 2 (tanpa flag)
forexbot --mode live --confirm-live      # live_enabled:true, akun DEMO → tampil info akun, ketik yes
```
Expected: posisi muncul di terminal MT5 dengan magic bot; posisi manual tidak tersentuh.
