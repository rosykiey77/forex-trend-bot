---
description: "Task list for Forex & Gold Trading Bot"
---

# Tasks: Forex & Gold Trading Bot (Backtest / Paper / Live)

**Input**: Design documents from `docs/` — [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Diminta eksplisit (PROMPT_BOT_FOREX.md "Catatan teknis" + user): **test-first** untuk lot sizing, pip value, PnL, swap, dan SL/TP di paper broker. Tulis test → pastikan GAGAL → implementasi.

**Organization**: Dikelompokkan per user story; urutan fase mengikuti roadmap plan.md (Fondasi → Backtest → Paper → Risk/Kill → Notifikasi → Gateway/Live).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: bisa paralel (file berbeda, tanpa dependensi ke task yang belum selesai)
- **[Story]**: US1..US5 sesuai spec.md

## Path Conventions

Single project: `src/`, `tests/`, `config/`, `gateway/` di root repo.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Inisialisasi proyek

- [ ] T001 Create `pyproject.toml` (name `forex-trend-bot`, `requires-python = ">=3.11"`, deps: pydantic>=2, PyYAML, python-dotenv, pandas, numpy, httpx, matplotlib; extras `dev = [pytest]`, `zmq = [pyzmq]`; scripts `forexbot = "src.main:main"`, `forexbot-download = "src.data.download:main"`, `forexbot-report = "src.report:main"`; pytest `testpaths = ["tests"]`)
- [ ] T002 [P] Create package skeleton with empty `__init__.py` in `src/`, `src/core/`, `src/data/`, `src/strategy/`, `src/broker/`, `src/risk/`, `src/storage/`, `src/notify/`, and dirs `tests/unit/`, `tests/integration/`, `tests/fixtures/`, `tests/fakes/`, `gateway/`
- [ ] T003 [P] Create `.gitignore` (`.venv/`, `.env`, `data/*.db*`, `data/*.lock`, `reports/`, `STOP`, `__pycache__/`) and `.env.example` (`GATEWAY_TOKEN=`, `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`)
- [ ] T004 [P] Create `config/config.example.yaml` with all keys: `account{currency: USD, initial_balance: 1000}`, `timeframe: M15`, `symbols{EURUSD{pip_size: 0.0001, point: 0.00001, digits: 5, contract_size: 100000, volume_min: 0.01, volume_max: 100, volume_step: 0.01, default_spread_points: 10, max_spread_points: 30, slippage_points: 2, commission_per_lot: 7.0, swap_long_points: -7.0, swap_short_points: 2.0, triple_swap_weekday: 2, sessions: ["00:05-23:55"]}, XAUUSD{pip_size: 0.1, point: 0.01, digits: 2, contract_size: 100, volume_min: 0.01, volume_max: 50, volume_step: 0.01, default_spread_points: 25, max_spread_points: 60, slippage_points: 5, commission_per_lot: 7.0, swap_long_points: -50.0, swap_short_points: 20.0, triple_swap_weekday: 2, sessions: ["01:05-23:55"]}}`, `risk{risk_per_trade_pct: 1.0, daily_loss_limit_pct: 3.0, max_open_positions: 2, max_consecutive_errors: 5, max_disconnect_seconds: 120, stop_file: STOP}`, `strategy{name: ema_atr, params{fast: 20, slow: 50, atr_period: 14, atr_mult: 1.5, rr: 2.0}}`, `broker_time{server_tz: "Etc/GMT-2", rollover: "00:00"}`, `engine{poll_seconds: 5, replay_speed: 0}`, `gateway{url: null, transport: rest, timeout_seconds: 10}`, `live{live_enabled: false, magic_number: 20261108, deviation_points: 20}`, `storage{dir: data}`, `reports{dir: reports}`

---

## Phase 2: Foundational (Blocking Prerequisites) — Roadmap Fase 1

**Purpose**: Config, model, perhitungan uang (test-first), storage, interface. **Tidak ada story yang boleh dimulai sebelum fase ini selesai.**

### Tests first (harus GAGAL dulu)

- [ ] T005 [P] Write `tests/unit/test_pricing.py`: pip value per lot EURUSD = 10.0 USD (0.0001×100000), XAUUSD = 10.0 USD (0.1×100); gross PnL BUY EURUSD 1.0 lot 1.10000→1.10200 = +200.00; SELL XAUUSD 0.10 lot 2000.00→1990.00 = +100.00; swap EURUSD long 1 lot −7 points = −7.00 USD/malam, ×3 pada `triple_swap_weekday`; konversi non-USD quote memakai `conv_rate`
- [ ] T006 [P] Write `tests/unit/test_sizing.py`: equity 1000, risk 1%, EURUSD SL 20 pips → 0.05 lot; XAUUSD SL 15.0 USD (150 pips) → 0.0066→ **0.00 → skip** (di bawah `volume_min` 0.01, return 0.0, tidak dibulatkan ke atas); hasil selalu kelipatan `volume_step` dibulatkan ke BAWAH; clamp ke `volume_max`; `sl_distance` 0 → 0.0
- [ ] T007 [P] Write `tests/unit/test_config.py`: example config valid; `risk_per_trade_pct` ≤ 0 atau > 5 ditolak; simbol tanpa `pip_size` ditolak; rahasia hanya dari env (`GATEWAY_TOKEN`, `TELEGRAM_*`)
- [ ] T008 [P] Write `tests/unit/test_clock.py`: UTC→server tz `Etc/GMT-2`; deteksi rollover saat melewati `00:00` server; `in_session()` false di Sabtu/Minggu dan di luar `sessions`

### Implementation

- [ ] T009 [P] Implement dataclasses in `src/core/models.py` per data-model.md: `Bar`, `Tick`, `SymbolSpec`, `Signal` (`side` ∈ `BUY|SELL|CLOSE`; `sl` wajib untuk BUY/SELL; BUY: sl < entry; SELL: sl > entry; `reason` non-empty), `OrderRequest`, `Position`, `Trade` (`exit_reason` ∈ `TP|SL|SIGNAL|KILL|MANUAL|END_OF_DATA`), `AccountState`, `Rejection(reason)`
- [ ] T010 Implement `src/config.py`: pydantic v2 models mirroring T004 keys, `load(path) -> AppConfig` (YAML + `dotenv` for secrets), `symbol_spec(name) -> SymbolSpec` — make T007 pass
- [ ] T011 Implement pure functions in `src/core/pricing.py`: `pip_value_per_lot(spec, conv_rate=1.0)`, `gross_pnl(side, entry, exit, lots, spec, conv_rate)`, `swap_charge(side, lots, spec, weekday, conv_rate)`, `lot_size(equity, risk_pct, sl_distance_price, spec, conv_rate)` per research R6 (floor to `volume_step`, clamp `volume_max`, <`volume_min` → 0.0) — make T005, T006 pass
- [ ] T012 [P] Implement `src/core/clock.py`: `to_server(dt)`, `trading_day(dt)`, `crossed_rollover(prev, now)`, `in_session(dt, sessions)` (Mon–Fri only) — make T008 pass
- [ ] T013 Write `src/storage/schema.sql` exactly as data-model.md tables (`meta`, `account` with `CHECK(id=1)`, `positions`, `trades`, `equity`, `events`) and implement `src/storage/db.py` `Storage(path)`: WAL, `executescript(schema)`, `load_state()`, `save_account()`, `upsert_position()`, `close_position(trade)` (DELETE position + INSERT trade + UPDATE account in ONE transaction), `append_equity()`, `log_event(level, kind, msg)`, `trades(run_id)`
- [ ] T014 [P] Write `tests/unit/test_storage.py`: round-trip account/positions; `close_position` atomic (simulated exception → no partial write); reopen file → state identical
- [ ] T015 [P] Define ABCs per contracts/interfaces.md: `Strategy` in `src/strategy/base.py`, `Feed` in `src/data/base.py`, `Broker` + `OrderRejected` in `src/broker/base.py`
- [ ] T016 [P] Implement logging setup (`time level kind message` to stdout, `--log-level`) in `src/logging_setup.py`

**Checkpoint**: `pytest tests/unit` hijau untuk pricing/sizing/config/clock/storage.

---

## Phase 3: User Story 1 — Backtest offline (Priority: P1) 🎯 MVP — Roadmap Fase 2

**Goal**: Backtest EURUSD & XAUUSD M15 dari CSV di Linux tanpa MT5, menghasilkan jurnal, metrik, dan equity PNG.

**Independent Test**: `forexbot --mode backtest --data tests/fixtures/` → exit 0, `reports/<run_id>/summary.json` + `equity.png`; dua run identik (quickstart V2).

### Tests for User Story 1 (tulis dulu, harus GAGAL)

- [ ] T017 [P] [US1] Create deterministic fixtures `tests/fixtures/EURUSD_M15.csv` and `tests/fixtures/XAUUSD_M15.csv` (~3000 bar each, generated once by `tests/fixtures/make_fixtures.py` with fixed seed; columns `time,open,high,low,close,volume,spread`) plus tiny hand-made `tests/fixtures/gap_sl.csv` where a bar opens beyond SL
- [ ] T018 [P] [US1] Write `tests/unit/test_paper_broker.py`: BUY fills at ask = open + spread×point + slippage; SELL fills at bid − slippage; SL hit via bar low (BUY) closes at SL − slippage; TP closes at TP exactly; **gap**: open beyond SL → fill at open; SL & TP in same bar → SL; commission charged `commission_per_lot × lots`; balance/equity/floating PnL/margin updated; `net_pnl` and `r_multiple` correct
- [ ] T019 [P] [US1] Write `tests/unit/test_csv_feed.py`: rejects missing columns, non-increasing/duplicate time, price ≤ 0, high < low with message naming row number; merges two symbols in time order; missing `spread` → `default_spread_points`
- [ ] T020 [P] [US1] Write `tests/unit/test_indicators.py`: `ema` matches `pandas.ewm(adjust=False)` reference values; `atr` Wilder on hand-computed 5-bar example
- [ ] T021 [P] [US1] Write `tests/integration/test_backtest.py`: run engine on fixtures twice → identical trades & summary; no trade without SL; signal at bar t executed at open of bar t+1

### Implementation for User Story 1

- [ ] T022 [P] [US1] Implement `src/data/csv_feed.py` `CsvFeed(data_dir, symbols, timeframe, start, end)`: load `{SYMBOL}_{TF}.csv` (time ISO-8601 UTC or epoch s), validate per FR-008, `history()`, `next_event()` yields `Bar` across symbols ordered by time — make T019 pass
- [ ] T023 [P] [US1] Implement `ema(series, n)` and `atr(df, n)` (Wilder, `ewm(alpha=1/n, adjust=False)`) in `src/strategy/indicators.py` — make T020 pass
- [ ] T024 [US1] Implement `EmaAtrStrategy` in `src/strategy/ema_atr.py` (`warmup_bars = slow + atr_period`; BUY on fast crossing above slow, SELL on crossing below; SL = close ∓ ATR×atr_mult; TP = close ± rr×SL distance; `CLOSE` on opposite cross if position open; reason text e.g. `"EMA20>EMA50 cross, ATR=…"`) and register in `STRATEGIES` dict in `src/strategy/__init__.py`
- [ ] T025 [US1] Implement `PaperBroker` in `src/broker/paper_broker.py` per contracts/interfaces.md and research R5: `open`, `close`, `modify`, `positions`, `account`, `on_price(bar)` (SL/TP/gap check, mark-to-market), uses `src/core/pricing.py`, persists every mutation through `Storage` — make T018 pass
- [ ] T026 [US1] Implement minimal `RiskManager.evaluate` in `src/risk/risk_manager.py`: reject signal without valid SL (FR-016), compute lots via `pricing.lot_size`, reject when lots == 0 with reason `"lot below volume_min"`; return `OrderRequest | Rejection`
- [ ] T027 [US1] Implement `Engine` in `src/engine.py` per plan.md "Engine loop" steps 2–5 (kill check stubbed until US3): pending-signal queue so execution happens on next bar open; on data end close all with `END_OF_DATA`; equity snapshot per bar; log rejections via `Storage.log_event(kind="reject")`
- [ ] T028 [US1] Implement `src/report.py`: metrics from `trades`/`equity` (total trades, win rate, profit factor, max drawdown %, avg R, net PnL), `equity.png` via matplotlib `Agg`, `summary.json`; `main()` for `forexbot-report --db --run`
- [ ] T029 [US1] Implement `src/main.py` CLI per contracts/cli.md for `--mode backtest` (`--config --data --from --to --log-level`), new DB `data/backtest_{run_id}.db`, print summary, exit codes 0/1 — make T021 pass

**Checkpoint**: quickstart V2 lulus. MVP selesai.

---

## Phase 4: User Story 2 — Paper trading realistis + restart (Priority: P2) — Roadmap Fase 3

**Goal**: Paper mode dengan replay offline (Linux), swap rollover, state persist & restore, satu instance.

**Independent Test**: quickstart V3 — hentikan dengan posisi terbuka, start ulang → balance & posisi identik.

### Tests for User Story 2

- [ ] T030 [P] [US2] Write `tests/unit/test_swap_rollover.py`: position held across `00:00` server time charged swap once per rollover; Wednesday (weekday 2) ×3; no charge for positions opened after rollover
- [ ] T031 [P] [US2] Write `tests/integration/test_paper_restart.py`: run paper replay N bars, stop with open position, new Engine on same DB → positions, balance, `day_start_equity`, `daily_locked` restored exactly (SC-006)
- [ ] T032 [P] [US2] Write `tests/unit/test_instance_lock.py`: second lock on `data/paper.lock` fails → exit code 4

### Implementation for User Story 2

- [ ] T033 [US2] Add swap on rollover to `PaperBroker.on_price` in `src/broker/paper_broker.py` using `clock.crossed_rollover` + `pricing.swap_charge` (accumulate into `Position.swap`, persist) — make T030 pass
- [ ] T034 [P] [US2] Implement `ReplayFeed(CsvFeed)` in `src/data/csv_feed.py` with `replay_speed` pacing (0 = no sleep) and resume from last processed bar time stored in `meta` table
- [ ] T035 [US2] Add state restore to `PaperBroker.__init__` (load from `Storage.load_state()`, else `initial_balance`) and `--reset-state` (with confirmation prompt) in `src/main.py`
- [ ] T036 [US2] Add instance lock (`fcntl.flock` on `{storage.dir}/{mode}.lock`, exit 4) and `--mode paper --feed replay` wiring in `src/main.py`; Ctrl-C → graceful stop (state saved, exit 0) — make T031, T032 pass

**Checkpoint**: quickstart V3 lulus.

---

## Phase 5: User Story 3 — Pengaman risiko & kill switch (Priority: P2) — Roadmap Fase 3–4

**Goal**: Max 2 posisi, daily loss 3%, jam pasar, batas spread, news hook, kill switch (STOP / error berulang / disconnect) di semua mode.

**Independent Test**: quickstart V4 + `tests/integration/test_risk_limits.py`.

### Tests for User Story 3

- [ ] T037 [P] [US3] Write `tests/unit/test_risk.py`: evaluate order of checks per contracts/interfaces.md (kill → SL → daily lock → max positions → session → spread → news hook → lot); 3rd position rejected; loss (realized+floating) ≥ 3% of `day_start_equity` → `daily_locked` and rejections until `on_new_day`; spread > `max_spread_points` rejected; out of session rejected; news hook returning True rejects
- [ ] T038 [P] [US3] Write `tests/unit/test_kill_switch.py`: `STOP` file present → reason `"stop_file"`; `max_consecutive_errors` reached → `"errors"`; disconnected > `max_disconnect_seconds` → `"disconnect"`; STOP present at startup → no trading
- [ ] T039 [P] [US3] Write `tests/integration/test_risk_limits.py`: scripted losing bars drive equity −3% → no new positions same day, resumes next trading day; never >2 open positions across full fixture run (SC-004)

### Implementation for User Story 3

- [ ] T040 [P] [US3] Implement `KillSwitch` in `src/risk/kill_switch.py`: `check(now) -> str | None`, `record_error()`, `record_success()`, `set_disconnected(since)` — make T038 pass
- [ ] T041 [US3] Extend `RiskManager` in `src/risk/risk_manager.py`: full `evaluate` order, `on_new_day` (reset `day_start_equity = equity`, `daily_locked = False`), daily-lock evaluation on every price update, `news_filter: Callable[[str, datetime], bool]` hook default `lambda *_: False` — make T037 pass
- [ ] T042 [US3] Wire kill switch & daily lock into `src/engine.py` (step 1 and per-cycle error handling): on kill → close all positions (`exit_reason=KILL`), `log_event(kind="kill")`, exit 3; on daily lock → `log_event(kind="daily_lock")` once per day — make T039 pass

**Checkpoint**: quickstart V4 lulus.

---

## Phase 6: User Story 4 — Notifikasi Telegram & jurnal (Priority: P3) — Roadmap Fase 4

**Goal**: Pesan entry/exit(TP/SL)/daily lock/kill/error; jurnal lengkap.

**Independent Test**: quickstart V5.

### Tests for User Story 4

- [ ] T043 [P] [US4] Write `tests/unit/test_telegram.py` with `httpx.MockTransport`: correct URL/payload; failure/timeout → no exception, `notify_failed` event logged; empty token → `NullNotifier`
- [ ] T044 [P] [US4] Write `tests/unit/test_journal.py`: closed trade row contains every field of FR-025 (times, symbol, side, lots, entry/exit, SL, TP, commission, swap, slippage_cost, gross/net PnL, R, entry/exit reason, mode)

### Implementation for User Story 4

- [ ] T045 [US4] Implement `TelegramNotifier` + `NullNotifier` in `src/notify/telegram.py` (queue + daemon thread, timeout 5 s, 2 retries, never raises) — make T043 pass
- [ ] T046 [US4] Add message formatters (entry: symbol, side, lots, entry, SL, TP; exit: exit price, net PnL, R, exit reason) and call notifier from `src/engine.py` on open/close/daily_lock/kill/error
- [ ] T047 [US4] Ensure `slippage_cost` is tracked in `PaperBroker` and written to `trades` in `src/broker/paper_broker.py` — make T044 pass

**Checkpoint**: quickstart V5 lulus.

---

## Phase 7: User Story 5 — Gateway MT5 & live trading (Priority: P3) — Roadmap Fase 5

**Goal**: Gateway Windows (REST + ZMQ opsional), klien Linux, GatewayFeed/GatewayBroker, downloader, pengaman live.

**Independent Test**: quickstart V6 di akun **demo**; di CI memakai fake MT5.

### Tests for User Story 5

- [ ] T048 [P] [US5] Create `tests/fakes/fake_mt5.py`: in-memory stand-in for the `MetaTrader5` functions used by the gateway (`initialize`, `account_info`, `symbol_info`, `symbol_info_tick`, `copy_rates_range`, `copy_rates_from_pos`, `positions_get`, `order_send`, `history_deals_get`, constants)
- [ ] T049 [P] [US5] Write `tests/integration/test_gateway.py`: start gateway with fake MT5 on localhost random port; every command in contracts/gateway.md returns `{"ok": true, "data": ...}` shape; wrong token → 401; `order_send` without SL → `ORDER_REJECTED`; `position_close` on foreign magic → `ORDER_REJECTED`; same tests over ZMQ transport skipped if `pyzmq` missing
- [ ] T050 [P] [US5] Write `tests/unit/test_live_guards.py`: live without `--confirm-live` → exit 2; without `live_enabled: true` → exit 2; confirmation input other than exact `yes` → exit 2; account banner shows login, server, demo/real, balance

### Implementation for User Story 5

- [ ] T051 [US5] Implement `gateway/mt5_gateway.py` (runs on Windows; `import MetaTrader5 as mt5` with `--fake` option importing `tests/fakes/fake_mt5.py`): `ThreadingHTTPServer` POST `/{command}`, `X-Gateway-Token` from env `GATEWAY_TOKEN`, single `threading.Lock` around MT5 calls, commands & error codes per contracts/gateway.md, filling mode FOK→IOC→RETURN, `--transport zmq` REP loop with identical messages, default bind `127.0.0.1` — make T049 pass
- [ ] T052 [P] [US5] Write `gateway/README.md`: Windows install (Python 3.11, `pip install MetaTrader5 pyzmq`), run as service (NSSM/Task Scheduler), SSH tunnel / WireGuard example, Wine notes
- [ ] T053 [US5] Implement `GatewayClient` in `src/broker/gateway_client.py`: `call(command, **params)`; REST via `httpx.Client` and ZMQ via `pyzmq` (lazy import), timeout `gateway.timeout_seconds`, raise `GatewayError(code, message)`, report transport failures to `KillSwitch.set_disconnected`
- [ ] T054 [P] [US5] Implement `GatewayFeed` in `src/data/gateway_feed.py`: `symbol_spec()` from `symbol_info` overriding config values, `history()` via `bars`, `next_event()` polls `tick` every `poll_seconds` and emits new closed bars
- [ ] T055 [US5] Implement `GatewayBroker` in `src/broker/gateway_broker.py`: maps Broker ABC to `order_send/order_modify/position_close/positions/account` with `magic_number` & `deviation_points`; `on_price` syncs positions and detects server-side SL/TP closes via `history_deals` → `Trade` written to journal
- [ ] T056 [US5] Implement `src/data/download.py` `forexbot-download` (paged `bars` requests → CSV `time,open,high,low,close,volume,spread`, validated by CsvFeed rules)
- [ ] T057 [US5] Add `--mode live` and `--mode paper --feed gateway` wiring to `src/main.py`: guards (flag + `live_enabled`), account banner + exact `yes` prompt, `GatewayFeed` + `GatewayBroker`/`PaperBroker` — make T050 pass

**Checkpoint**: T049/T050 hijau di Linux; quickstart V6 dijalankan manual di akun demo.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T058 [P] Write `README.md`: install, config, each mode, gateway setup link, how to add a strategy (subclass `Strategy`, register in `STRATEGIES`, set `strategy.name`)
- [ ] T059 [P] Add `tests/integration/test_perf.py` (marked `slow`): 1 year M15 × 2 symbols synthetic data backtest < 120 s (SC-001)
- [ ] T060 Add `systemd` unit example `deploy/forexbot-paper.service` (Restart=on-failure, but NOT when exit code 3 kill switch: `RestartPreventExitStatus=2 3 4`)
- [ ] T061 Run full quickstart.md V1–V5 on Linux and record results in `docs/quickstart.md` notes section

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup (P1) → Foundational (P2) → **blocks all stories**
- US1 (Phase 3) → MVP; US2, US3 depend on US1's `PaperBroker` + `Engine`
- US2 and US3 independent of each other (different files except `src/engine.py`/`src/main.py` — do sequentially there)
- US4 depends on Engine (US1); independent of US2/US3
- US5 depends on Broker/Feed ABCs (Phase 2), RiskManager & KillSwitch (US3), Engine (US1)
- Polish after desired stories

### Story graph

```text
Setup → Foundational → US1 ─┬─► US2 ─┐
                            ├─► US3 ─┼─► US5 → Polish
                            └─► US4 ─┘
```

### Within Each Story

Tests (FAIL) → models/pure functions → broker/feed → engine/CLI wiring → checkpoint.

## Parallel Example: Foundational

```text
T005 test_pricing.py | T006 test_sizing.py | T007 test_config.py | T008 test_clock.py   (parallel)
T009 models.py | T012 clock.py | T015 ABCs | T016 logging                               (parallel)
```

## Parallel Example: User Story 1

```text
T017 fixtures | T018 test_paper_broker | T019 test_csv_feed | T020 test_indicators | T021 test_backtest
T022 csv_feed.py | T023 indicators.py                                             (parallel)
then T024 → T025 → T026 → T027 → T028 → T029
```

## Parallel Example: User Story 5

```text
T048 fake_mt5 | T049 test_gateway | T050 test_live_guards | T052 gateway README | T054 gateway_feed
```

## Implementation Strategy

### MVP First (US1)

1. Phase 1 + 2 (money math tested first).
2. Phase 3 → validate quickstart V2 → **STOP & review backtest results** before paper.

### Incremental Delivery (per PROMPT_BOT_FOREX.md phases — show results before continuing)

1. Fondasi (Phase 1–2) → 2. Backtest (US1) → 3. Paper (US2 + US3 limits) → 4. Notif & kill switch (US3 kill + US4) → 5. Gateway & live (US5, **demo account only**).

## Notes

- Never commit `.env`, `data/*.db`, or `STOP`.
- `src/engine.py` and `src/main.py` are touched by several stories — no [P] across stories there.
- Commit after each task or logical group.
