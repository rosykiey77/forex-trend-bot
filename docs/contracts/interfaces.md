# Contract: Internal Python interfaces

Interface = `typing.Protocol` / ABC di `src/*/base.py`. Tipe data: lihat `../data-model.md`.

## Strategy (`src/strategy/base.py`)

```python
class Strategy(ABC):
    name: str
    warmup_bars: int                       # bar minimum sebelum boleh bersinyal
    def __init__(self, params: dict): ...
    @abstractmethod
    def on_bar(self, symbol: str, bars: pd.DataFrame, position: Position | None) -> Signal | None:
        """bars = histori bar TERTUTUP s/d sekarang (index waktu UTC, kolom open/high/low/close/volume).
        Tidak tahu mode, tidak memanggil broker. Deterministik."""
```
Registri: `config.strategy.name` → kelas lewat dict `STRATEGIES` di `src/strategy/__init__.py`.

## Feed (`src/data/base.py`)

```python
class Feed(ABC):
    def symbol_spec(self, symbol) -> SymbolSpec
    def history(self, symbol, count) -> pd.DataFrame        # bar tertutup terakhir
    def next_event(self) -> Bar | Tick | None               # None = data habis (backtest/replay)
```
Implementasi: `CsvFeed` (backtest, iterasi bar semua simbol berurutan waktu), `ReplayFeed` (paper offline, CsvFeed + pacing), `GatewayFeed` (paper/live, polling `tick` + `bars`).

## Broker (`src/broker/base.py`)

```python
class Broker(ABC):
    def account(self) -> AccountState
    def positions(self) -> list[Position]                    # milik magic bot saja
    def open(self, req: OrderRequest) -> Position            # raise OrderRejected
    def close(self, position_id: str, reason: str) -> Trade
    def modify(self, position_id: str, sl: float | None, tp: float | None) -> None
    def on_price(self, event: Bar | Tick) -> list[Trade]     # paper: cek SL/TP/gap, swap, mark-to-market; live: sinkron posisi & deteksi close oleh server
```
Implementasi: `PaperBroker` (backtest & paper, persist via `Storage`), `GatewayBroker` (live, via `GatewayClient`).

## RiskManager (`src/risk/risk_manager.py`)

```python
class RiskManager:
    def evaluate(self, signal: Signal, price: Tick, spec: SymbolSpec,
                 account: AccountState, open_positions: list[Position], now: datetime) -> OrderRequest | Rejection
    def lot_size(self, equity, sl_distance_price, spec, conv_rate=1.0) -> float   # 0.0 = skip
    def on_new_day(self, account, now) -> None
    def check_kill(self, now) -> str | None                  # alasan kill atau None
```
Urutan cek `evaluate`: kill → sl ada & valid → daily lock → max posisi → jam pasar → spread → news hook → lot ≥ min.

## Notifier (`src/notify/telegram.py`)

`notify(kind: str, text: str) -> None` — non-blocking, tidak pernah raise. `NullNotifier` bila token kosong.

## Storage (`src/storage/db.py`)

`load_state() / save_account() / upsert_position() / close_position(trade) / append_equity() / log_event() / trades(run_id)` — setiap mutasi satu transaksi.
