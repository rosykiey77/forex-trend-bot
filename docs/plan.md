# Implementation Plan: Forex & Gold Trading Bot (Backtest / Paper / Live)

**Branch**: `main` (feature dir `docs/`) | **Date**: 2026-11-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `docs/spec.md`

## Summary

Bot Python 3.11+ untuk EURUSD & XAUUSD (M15) dengan tiga mode berbagi satu strategi & satu RiskManager. Inti berjalan native di Linux: `CsvFeed`/`ReplayFeed` + `PaperBroker` (spread bid/ask, slippage, komisi, swap, gap SL/TP) untuk backtest dan paper offline. Akses MT5 (hanya Windows) dipisah ke **gateway** kecil di Windows VPS/Wine yang membungkus paket `MetaTrader5` dan diekspos lewat REST/JSON (default) atau ZeroMQ (opsional) dengan kontrak pesan yang sama; di Linux dipakai oleh `GatewayFeed` + `GatewayBroker`. State & jurnal di SQLite, notifikasi Telegram non-blocking. Detail keputusan: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11+ (bot, Linux); Python 3.11 Windows untuk gateway

**Primary Dependencies**: pydantic v2, PyYAML, python-dotenv, pandas, numpy, httpx, matplotlib; opsional `pyzmq` (extra `zmq`); gateway: `MetaTrader5` (Windows only, bukan dependensi bot)

**Storage**: SQLite (`sqlite3` stdlib, WAL) — `data/{mode}.db`

**Testing**: pytest (+ fake MT5 module untuk test gateway di Linux)

**Target Platform**: Linux VPS (Ubuntu 22.04+); gateway: Windows Server/10+ atau Wine

**Project Type**: CLI / long-running daemon (single project) + companion gateway script

**Performance Goals**: backtest 1 tahun M15 × 2 simbol (~50k bar) < 2 menit; siklus loop paper/live ≤ 5 s; notifikasi ≤ 10 s

**Constraints**: offline-capable di Linux (backtest/paper replay tanpa MT5); deterministik; tanpa rahasia di kode; satu instance per DB; RAM < 500 MB

**Scale/Scope**: 1 operator, 2 simbol (dapat ditambah via config), ≤ 2 posisi bersamaan, ~20 modul

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` masih berupa template kosong (belum diratifikasi) → tidak ada gate formal. Plan ini memakai prinsip dari `PROMPT_BOT_FOREX.md` sebagai gate pengganti:

| Gate | Status |
|---|---|
| Strategi tidak tahu mode (FR-002) — Strategy hanya menerima bar, Broker beda per mode | ✅ `contracts/interfaces.md` |
| Risk berlaku di semua mode — satu `RiskManager` di jalur tunggal `Engine` | ✅ |
| Tanpa hardcode / rahasia di kode — config YAML + `.env` | ✅ |
| Unit test untuk lot, pip value, PnL, SL/TP sebelum fitur lanjutan | ✅ tasks test-first di Phase 2/3 |
| Live hanya dengan flag + config + konfirmasi; diuji di demo | ✅ |

Re-check pasca desain: tetap lulus; tidak ada pelanggaran → Complexity Tracking kosong.

## Architecture

```text
                 ┌────────────── Linux VPS ───────────────────────────────┐
 config.yaml ──► │ main.py ─► Engine (satu loop untuk semua mode)          │
 .env            │            │                                           │
                 │   Feed ────┤  CsvFeed | ReplayFeed | GatewayFeed       │
                 │   Strategy ┤  EmaAtrStrategy (via registry)            │
                 │   Risk ────┤  RiskManager + KillSwitch(STOP/err/disc)  │
                 │   Broker ──┤  PaperBroker | GatewayBroker              │
                 │   Storage ─┤  SQLite (state, trades, equity, events)   │
                 │   Notifier ┘  Telegram (queue + thread)               │
                 │                    │ GatewayClient (httpx | zmq)       │
                 └────────────────────┼──────────────────────────────────┘
                                      │ SSH tunnel / WireGuard (JSON, token)
                 ┌────── Windows VPS / Wine ─────┐
                 │ gateway/mt5_gateway.py ─► MetaTrader5 ─► terminal64.exe │
                 └───────────────────────────────┘
```

**Engine loop** (sama untuk semua mode; backtest hanya beda sumber event & tanpa sleep):

1. `kill = risk.check_kill(now)` → jika ada: `broker.close` semua, notify, exit 3.
2. `event = feed.next_event()`; `None` → selesai (backtest/replay: tutup posisi `END_OF_DATA`, laporan).
3. `trades = broker.on_price(event)` → simpan/notify tiap trade; rollover hari → `risk.on_new_day`.
4. Jika bar baru tertutup untuk simbol: `signal = strategy.on_bar(...)` → `risk.evaluate(...)` → `broker.open(req)` atau log `reject`.
5. Snapshot equity (per bar) → Storage. Error ditangkap per siklus → `consecutive_errors++`; sukses → reset.

**Mode matrix**

| Mode | Feed | Broker | Butuh MT5? | Linux native |
|---|---|---|---|---|
| backtest | CsvFeed | PaperBroker (DB per run) | Tidak | ✅ |
| paper `--feed replay` | ReplayFeed | PaperBroker (persist `paper.db`) | Tidak | ✅ |
| paper `--feed gateway` | GatewayFeed | PaperBroker | Ya, via gateway (data saja) | ✅ |
| live | GatewayFeed | GatewayBroker | Ya, via gateway | ✅ (+ gateway Windows) |

## Project Structure

### Documentation (this feature)

```text
docs/
├── requirements.md      # input asli
├── spec.md              # /speckit-specify
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1: cli.md, gateway.md, interfaces.md
├── checklists/          # spec quality checklist
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml                 # deps, extras [dev] [zmq], scripts forexbot / forexbot-download / forexbot-report
config/config.example.yaml
.env.example
src/
├── main.py                    # CLI, mode wiring, live guards, instance lock
├── config.py                  # pydantic AppConfig + load()
├── engine.py                  # loop tunggal semua mode
├── report.py                  # metrik + equity PNG + summary.json
├── core/
│   ├── models.py              # Bar, Tick, SymbolSpec, Signal, OrderRequest, Position, Trade, AccountState
│   ├── pricing.py             # pip value, PnL, swap, konversi ccy (fungsi murni)
│   └── clock.py               # UTC↔server tz, rollover, jam pasar
├── data/
│   ├── base.py
│   ├── csv_feed.py            # CsvFeed + ReplayFeed + validasi CSV
│   ├── gateway_feed.py
│   └── download.py            # forexbot-download
├── strategy/
│   ├── __init__.py            # STRATEGIES registry
│   ├── base.py
│   ├── indicators.py          # ema, atr
│   └── ema_atr.py
├── broker/
│   ├── base.py
│   ├── paper_broker.py
│   ├── gateway_client.py      # REST (httpx) + ZMQ transport
│   └── gateway_broker.py
├── risk/
│   ├── risk_manager.py
│   └── kill_switch.py
├── storage/
│   ├── schema.sql
│   └── db.py
└── notify/
    └── telegram.py
gateway/
├── mt5_gateway.py             # Windows: http.server + optional zmq, wraps MetaTrader5
└── README.md
tests/
├── fixtures/                  # EURUSD_M15.csv, XAUUSD_M15.csv kecil (deterministik)
├── fakes/fake_mt5.py
├── unit/                      # pricing, sizing, paper broker, risk, kill, storage, csv, indicators, config
└── integration/               # backtest e2e, paper restart, risk limits, gateway(fake mt5)
```

**Structure Decision**: single project sesuai arsitektur di `PROMPT_BOT_FOREX.md`, dengan tambahan `core/` (model & perhitungan murni, agar mudah diuji), `engine.py` (satu loop untuk semua mode), dan `gateway/` terpisah karena berjalan di OS lain. `mt5_feed.py`/`mt5_broker.py` dari prompt asli diganti `gateway_feed.py`/`gateway_broker.py` karena bot jalan di Linux.

## Roadmap Implementasi

Mengikuti fase di `PROMPT_BOT_FOREX.md`; tiap fase diakhiri `pytest` hijau + demo hasil.

| Fase | Isi | Story | Selesai bila |
|---|---|---|---|
| 1 Fondasi | pyproject, config, models, pricing, storage, interfaces | – | unit test pricing/sizing/config lulus |
| 2 Backtest (MVP) | CsvFeed, indicators, EmaAtr, PaperBroker, RiskManager inti, Engine, report | US1 | V2 quickstart lulus, deterministik |
| 3 Paper | ReplayFeed, persist/restore, swap rollover, daily limit, instance lock | US2, US3 | V3 + V4 lulus |
| 4 Notifikasi & kill switch | Telegram, STOP/error/disconnect kill | US3, US4 | V4 + V5 lulus |
| 5 Gateway & live | mt5_gateway, GatewayClient, GatewayFeed, GatewayBroker, downloader, live guards | US5 | V6 lulus di akun **demo** |

**Risiko & mitigasi**

- Perbedaan spesifikasi simbol antar broker (contract size XAUUSD 100 vs 1, digit) → di live selalu ambil dari `symbol_info`; startup log spesifikasi efektif.
- Gateway terputus saat posisi terbuka → SL/TP sudah ada di server broker (order dikirim dengan SL/TP), jadi posisi tetap terlindungi; kill switch disconnect hanya menghentikan entry baru dan mencoba close bila koneksi pulih.
- Bias backtest → eksekusi bar t+1, SL-first, slippage merugikan (R5).
- Wine + MT5 tidak stabil → dokumentasikan Windows VPS sebagai jalur utama.

## Complexity Tracking

Tidak ada pelanggaran gate.
