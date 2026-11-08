# Contract: MT5 Gateway (Windows side) ↔ Bot (Linux side)

Satu skema pesan JSON, dua transport:

- **REST**: `POST http://{host}:{port}/{command}` body = `params`, header `X-Gateway-Token: <GATEWAY_TOKEN>`. Response JSON.
- **ZeroMQ REQ/REP**: kirim `{"command": "...", "token": "...", "params": {...}}` ke `tcp://{host}:{port}`; balasan JSON sama.

Response sukses: `{"ok": true, "data": ...}`. Gagal: `{"ok": false, "error": {"code": "<CODE>", "message": "...", "retcode": <mt5 retcode|null>}}`. HTTP status selalu 200 kecuali auth (401) / command tak dikenal (404).

Error codes: `AUTH`, `NOT_CONNECTED` (terminal belum login), `UNKNOWN_SYMBOL`, `ORDER_REJECTED`, `TIMEOUT`, `INTERNAL`.

Gateway default bind `127.0.0.1`; akses jarak jauh lewat SSH tunnel/WireGuard. Semua panggilan MT5 diserialisasi (lock tunggal).

## Commands

| command | params | data |
|---|---|---|
| `health` | – | `{"connected": bool, "terminal": str, "version": str}` |
| `account` | – | `{"login", "server", "name", "currency", "balance", "equity", "margin", "trade_mode": "demo"\|"real"\|"contest"}` |
| `symbol_info` | `{"symbol"}` | `{"digits","point","contract_size","volume_min","volume_max","volume_step","swap_long","swap_short","swap_mode","swap_rollover3days","spread","trade_mode"}` |
| `tick` | `{"symbol"}` | `{"time": epoch_s, "bid", "ask"}` |
| `bars` | `{"symbol","timeframe":"M15","count"?:int,"from"?:epoch_s,"to"?:epoch_s}` | `[{"time","open","high","low","close","volume","spread"}]` (bar tertutup saja, naik) |
| `positions` | `{"magic"}` | `[{"ticket","symbol","side","volume","price_open","sl","tp","time","swap","profit","magic","comment"}]` |
| `order_send` | `{"symbol","side":"BUY"\|"SELL","volume","sl","tp","magic","comment","deviation_points"}` | `{"ticket","price","volume","retcode"}` |
| `order_modify` | `{"ticket","sl","tp"}` | `{"retcode"}` |
| `position_close` | `{"ticket","deviation_points"}` | `{"price","retcode","profit"}` |
| `history_deals` | `{"magic","from","to"}` | `[{"ticket","position_id","time","price","volume","profit","commission","swap","entry"}]` |

## Aturan

- `order_send` WAJIB menolak (`ORDER_REJECTED`) bila `sl` kosong/0 — pengaman ganda FR-016.
- `positions`/`position_close` hanya untuk `magic` yang diminta; `position_close` pada ticket dengan magic lain → `ORDER_REJECTED`.
- Filling mode dipilih gateway dari `symbol_info().filling_mode` (FOK → IOC → RETURN).
- Timeout klien: 10 s per panggilan; 3 kegagalan transport berturut → klien melaporkan `disconnected_since` ke kill-switch monitor.
