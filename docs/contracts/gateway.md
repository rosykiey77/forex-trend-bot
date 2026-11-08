# Contract: MT5 Gateway (Windows side) ↔ Bot (Linux side)

REST (stdlib `http.server`, `gateway/mt5_gateway.py`), header `Authorization: Bearer <MT5_GATEWAY_TOKEN>`. GET params = query string, POST params = JSON body. Klien: `src/broker/mt5_broker.py` `GatewayClient` (urllib).

Response sukses: `{"ok": true, "data": ...}`. Gagal: `{"ok": false, "error": {"code": "<CODE>", "message": "...", "retcode": <mt5 retcode|null>}}`. HTTP status selalu 200 kecuali auth (401) / endpoint tak dikenal (404).

Error codes: `AUTH`, `NOT_FOUND`, `NOT_CONNECTED` (paket MetaTrader5 tak ada / terminal belum login), `UNKNOWN_SYMBOL`, `ORDER_REJECTED`, `BAD_REQUEST`, `INTERNAL`; klien menambah `UNAVAILABLE` untuk kegagalan transport.

Gateway default bind `127.0.0.1`; akses jarak jauh lewat SSH tunnel/WireGuard. Semua panggilan MT5 diserialisasi (lock tunggal).

## Endpoints

| endpoint | params | data |
|---|---|---|
| `GET /health` | – | `{"connected","broker","server","login","name","currency","trade_mode":"demo"\|"contest"\|"real","demo","leverage","balance","equity","margin","margin_free"}` |
| `GET /candles` | `symbol, timeframe=M15, count=500, start=0` (`copy_rates_from_pos`; `start=1` = tanpa bar berjalan) | `[{"time","open","high","low","close","tick_volume","spread"}]` naik |
| `GET /tick` | `symbol` | `{"time","bid","ask","spread_points"}` |
| `GET /symbol_info` | `symbol` | `{"name","point","digits","contract_size","volume_min","volume_max","volume_step","spread"}` |
| `GET /positions` | `magic` (opsional) | `[{"ticket","symbol","side","volume","price_open","sl","tp","time","profit","swap","magic","comment"}]` |
| `GET /deals` | `position` | `[{"ticket","position_id","time","price","volume","profit","commission","swap","fee","magic","entry":"IN"\|"OUT","reason":"SL"\|"TP"\|"STOP_OUT"\|"OTHER"}]` |
| `POST /order` | `{"symbol","side":"BUY"\|"SELL","volume","sl","tp","magic","deviation","comment"}` | `{"ticket","price","volume","retcode"}` |
| `POST /modify` | `{"ticket","magic","sl","tp"}` (`null` = tetap) | `{"retcode","sl","tp"}` |
| `POST /close` | `{"ticket","magic","deviation"}` | `{"price","retcode","profit"}` |

## Aturan

- `POST /order` WAJIB menolak (`ORDER_REJECTED`) bila `sl` kosong/0 — pengaman ganda FR-016.
- `/modify` dan `/close` pada ticket dengan magic lain → `ORDER_REJECTED`; bot selalu memfilter `/positions` dengan magic-nya.
- Filling mode dipilih gateway dari `symbol_info().filling_mode` (FOK → IOC → RETURN).
- Timeout klien: `live.timeout_seconds` (10 s); kegagalan transport menggagalkan siklus → dihitung ke kill switch error berulang.
