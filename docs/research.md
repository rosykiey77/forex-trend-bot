# Research: Forex & Gold Trading Bot

Semua unknown di Technical Context sudah diputuskan di bawah. Format: Decision / Rationale / Alternatives.

## R1. Akses MT5 dari Linux

- **Decision**: Gateway kecil `gateway/mt5_gateway.py` berjalan di mesin Windows (Windows VPS, atau Wine di Linux) dengan Python Windows + paket `MetaTrader5`. Bot Linux bicara ke gateway lewat **REST/JSON (httpx)** sebagai transport default; **ZeroMQ REQ/REP (pyzmq)** sebagai transport alternatif opsional dengan pesan JSON identik (lihat `contracts/gateway.md`).
- **Rationale**: `MetaTrader5` hanya ada wheel Windows dan berkomunikasi lewat IPC ke `terminal64.exe` lokal. Satu kontrak pesan + dua transport tipis = logika klien tunggal. REST gampang di-debug (`curl`), ZMQ latensi rendah & tanpa overhead HTTP.
- **Alternatives**: `mt5linux`/rpyc (expose seluruh modul via RPC — permukaan serangan besar, versi rapuh); MQL5 EA + socket (butuh kode MQL5 terpisah, lebih sulit diuji); bridge berbayar (MetaApi — ketergantungan cloud pihak ketiga).

## R2. Server gateway (sisi Windows)

- **Decision**: stdlib `http.server.ThreadingHTTPServer` + JSON, autentikasi header `X-Gateway-Token` (shared secret dari env), bind default `127.0.0.1`; akses jarak jauh lewat SSH tunnel / WireGuard. Mode ZMQ di file yang sama, aktif bila `--transport zmq`.
- **Rationale**: tanpa dependensi web framework di Windows; ~10 endpoint saja. Panggilan `MetaTrader5` tidak thread-safe → semua panggilan diserialisasi dengan satu `threading.Lock`.
- **Alternatives**: FastAPI/uvicorn (dependensi + overhead tak perlu untuk 10 endpoint); TLS di gateway (lebih rumit daripada tunnel).

## R3. Konfigurasi

- **Decision**: `config/config.yaml` dimuat `PyYAML` → divalidasi `pydantic` v2 (model `AppConfig`). Rahasia dari env (`python-dotenv` memuat `.env`).
- **Rationale**: validasi tipe + pesan error jelas saat start (fail fast), default terdokumentasi di satu tempat.
- **Alternatives**: dataclass + validasi manual (lebih banyak kode); pydantic-settings (tidak perlu, env hanya untuk rahasia).

## R4. Data & indikator

- **Decision**: `pandas` untuk muat/validasi CSV dan hitung EMA (`ewm(adjust=False)`) serta ATR (Wilder, `ewm(alpha=1/14)`). Format CSV: `time,open,high,low,close,volume[,spread]`, `time` UTC ISO-8601 atau epoch detik; `spread` dalam points.
- **Rationale**: sudah diminta; indikator 2 baris tanpa TA-Lib (TA-Lib butuh build C).
- **Alternatives**: TA-Lib, pandas-ta (dependensi tambahan untuk 2 indikator).

## R5. Model eksekusi backtest

- **Decision**: event loop bar-by-bar. Sinyal dihitung pada **close bar t**, dieksekusi pada **open bar t+1** (bid = open, ask = open + spread). SL/TP dicek per bar pada bar t+1 dst. memakai high/low (sisi bid untuk posisi buy, sisi ask untuk sell). Gap: bila open sudah melewati SL/TP → isi di open. SL & TP kena dalam bar sama → SL (konservatif). Slippage = `slippage_points` konfigurasi, selalu merugikan, untuk entry dan exit stop (TP limit tanpa slippage).
- **Rationale**: tanpa look-ahead bias, deterministik (SC-002), konservatif.
- **Alternatives**: eksekusi di close bar sinyal (look-ahead ringan); simulasi tick sintetis (kompleks, tanpa data tick nyata tidak lebih akurat).

## R6. Nilai pip & sizing

- **Decision**: `pip_size` per simbol di config (EURUSD 0.0001, XAUUSD 0.1 — dapat dioverride), `contract_size` (EURUSD 100000, XAUUSD 100). Nilai pip per lot dalam quote currency = `pip_size × contract_size`; dikonversi ke mata uang akun (USD) — untuk EURUSD/XAUUSD quote=USD sehingga faktor 1; selain itu pakai harga simbol konversi (mis. USDJPY) dari feed. Di live, `contract_size`, `volume_min/max/step`, `digits` diambil dari `symbol_info` via gateway dan menimpa config.
  `lots = floor((equity × risk%) / (sl_pips × pip_value_per_lot) / volume_step) × volume_step`, lalu clamp ke max; bila < `volume_min` → skip.
- **Rationale**: rumus sesuai spec FR-015; pembulatan ke bawah agar risiko tidak pernah melebihi target.
- **Alternatives**: `order_calc_profit` MT5 (tidak tersedia offline).

## R7. Swap

- **Decision**: swap dalam **points per lot per malam** (konvensi MT5 `SWAP_MODE_POINTS`): `swap = swap_points × point × contract_size × lots` (dalam quote ccy → konversi USD). Dibebankan saat bar pertama yang melewati `rollover_time` (default 00:00 waktu server broker, `server_tz` default `Etc/GMT-2`). Hari triple (default Rabu) ×3.
- **Rationale**: cocok dengan mayoritas broker MT5 untuk FX/emas; nilai config.
- **Alternatives**: swap mode lain (persen, money) — tambahkan bila broker membutuhkan.

## R8. Penyimpanan

- **Decision**: `sqlite3` stdlib, mode WAL, satu file per mode (`data/{mode}.db` default). Migrasi = skrip `schema.sql` idempoten (`CREATE TABLE IF NOT EXISTS`) + tabel `meta(schema_version)`. Setiap perubahan state dalam satu transaksi. Lock instance tunggal via `fcntl.flock` pada `data/{mode}.lock` (FR-031).
- **Rationale**: tanpa ORM; tabel sedikit. WAL aman terhadap crash.
- **Alternatives**: SQLAlchemy (berat untuk 6 tabel).

## R9. Notifikasi Telegram

- **Decision**: `httpx` POST ke `https://api.telegram.org/bot{token}/sendMessage`, timeout 5 s, 2 retry, dijalankan via antrean + thread daemon agar tidak memblokir loop trading. Gagal → log `notify_failed`, tidak raise.
- **Rationale**: tanpa library bot penuh; memenuhi FR-029 & SC-008.
- **Alternatives**: python-telegram-bot (dependensi besar, async framework).

## R10. Laporan & grafik

- **Decision**: metrik dihitung dari tabel `trades` + `equity`; grafik equity PNG via `matplotlib` (backend `Agg`, headless VPS). Ringkasan juga dicetak ke stdout dan disimpan `reports/{run_id}.json`.
- **Alternatives**: plotly HTML (dependensi lebih besar; PNG cukup untuk spec "PNG/HTML").

## R11. Loop paper/live & jam

- **Decision**: loop polling setiap `poll_seconds` (default 5 s): cek kill switch → ambil tick/bar terbaru → update posisi (SL/TP, swap) → jika bar M15 baru tertutup → strategi → risk → broker. Paper offline = `ReplayFeed` membaca CSV dengan kecepatan konfigurasi (`replay_speed`, 0 = secepatnya). Semua waktu internal UTC tz-aware; konversi ke waktu server hanya untuk rollover & jam pasar.
- **Alternatives**: asyncio (tidak perlu untuk 2 simbol).

## R12. Testing

- **Decision**: `pytest`. Unit test wajib untuk lot sizing, pip value, PnL, swap, SL/TP + gap, daily limit, kill switch, state restore. Integration test backtest dengan CSV fixture kecil (deterministik). Gateway diuji dengan fake MT5 module (`tests/fakes/fake_mt5.py`) yang di-inject — berjalan di Linux CI.
- **Alternatives**: hypothesis (boleh ditambah nanti untuk sizing).
