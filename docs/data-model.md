# Data Model: Forex & Gold Trading Bot

Objek in-memory = `@dataclass(slots=True)` di `src/core/models.py`. Tabel SQLite di `src/storage/schema.sql`. Semua waktu UTC (ISO-8601 di SQLite). Uang dalam mata uang akun, `REAL` dibulatkan 2 desimal saat ditampilkan, tidak saat disimpan.

## Objek domain

### Bar
| Field | Type | Rules |
|---|---|---|
| symbol | str | terdaftar di config |
| time | datetime (UTC) | open time bar; naik ketat, unik |
| open, high, low, close | float | > 0; high ≥ max(open, close); low ≤ min(open, close) |
| volume | float | ≥ 0 |
| spread_points | int \| None | ≥ 0; None → pakai `symbols.<s>.default_spread_points` |

### SymbolSpec
`name, digits, point, pip_size, contract_size, volume_min, volume_max, volume_step, swap_long_points, swap_short_points, triple_swap_weekday (0=Mon), max_spread_points, commission_per_lot (round-turn, USD), slippage_points, trading_sessions (list of "HH:MM-HH:MM" waktu server, weekday Mon–Fri)`. Sumber: config; di live ditimpa `symbol_info` dari gateway.

### Signal
| Field | Type | Rules |
|---|---|---|
| symbol | str | |
| side | `BUY` \| `SELL` \| `CLOSE` | |
| sl | float \| None | wajib untuk BUY/SELL (FR-016); BUY: sl < entry; SELL: sl > entry |
| tp | float \| None | opsional |
| reason | str | non-empty |

### OrderRequest (output RiskManager → Broker)
`symbol, side, lots, sl, tp, reason, magic`

### Position
| Field | Type | Notes |
|---|---|---|
| id | str | paper: uuid4; live: ticket MT5 |
| symbol, side, lots | | |
| entry_price, sl, tp | float | |
| open_time | datetime | |
| magic | int | config `magic_number` |
| commission, swap | float | akumulasi, ≤0 untuk biaya |
| initial_risk | float | `abs(entry-sl)/pip_size × pip_value × lots` — basis R |
| entry_reason | str | |

### Trade (posisi tertutup)
Position + `exit_price, exit_time, exit_reason (TP|SL|SIGNAL|KILL|MANUAL|END_OF_DATA), gross_pnl, net_pnl (gross + commission + swap), r_multiple (net_pnl / initial_risk), mode`.

### AccountState
`balance, equity, margin_used, day_start_equity, day (tanggal trading waktu server), daily_locked (bool), consecutive_errors, kill_reason (str|None)`.

**Turunan**: `equity = balance + Σ floating_pnl(pos) + Σ pos.swap`(belum direalisasi) ; `daily_loss = day_start_equity − equity`; `daily_locked = daily_loss ≥ day_start_equity × daily_loss_limit_pct`.

## State transitions

```text
Position:  (OrderRequest accepted) → OPEN → CLOSED{TP|SL|SIGNAL|KILL|END_OF_DATA}
Bot:       STARTING → RUNNING ⇄ DAILY_LOCKED (reset di rollover hari)
           RUNNING|DAILY_LOCKED → KILLED (STOP file | errors ≥ N | disconnect > T) → exit
Live start: STARTING → (flag && live_enabled) → SHOW_ACCOUNT → (operator "yes") → RUNNING ; else ABORT
```

## Tabel SQLite

```sql
meta(key TEXT PRIMARY KEY, value TEXT)                      -- schema_version, run_id, mode
account(id INTEGER PRIMARY KEY CHECK(id=1), balance REAL, day_start_equity REAL,
        day TEXT, daily_locked INTEGER, updated_at TEXT)
positions(id TEXT PRIMARY KEY, symbol TEXT, side TEXT, lots REAL, entry_price REAL,
          sl REAL, tp REAL, open_time TEXT, magic INTEGER, commission REAL, swap REAL,
          initial_risk REAL, entry_reason TEXT)
trades(id TEXT PRIMARY KEY, run_id TEXT, mode TEXT, symbol TEXT, side TEXT, lots REAL,
       entry_price REAL, exit_price REAL, sl REAL, tp REAL, open_time TEXT, exit_time TEXT,
       commission REAL, swap REAL, slippage_cost REAL, gross_pnl REAL, net_pnl REAL,
       r_multiple REAL, entry_reason TEXT, exit_reason TEXT)
equity(run_id TEXT, time TEXT, balance REAL, equity REAL, PRIMARY KEY(run_id, time))
events(id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, level TEXT, kind TEXT, message TEXT)
       -- kind: error|reject|kill|daily_lock|notify_failed|start|stop
```

Close posisi = satu transaksi: `DELETE positions` + `INSERT trades` + `UPDATE account`. Backtest memakai DB baru per run (`data/backtest_{run_id}.db`) — tidak ada state restore.
