# Prompt untuk Claude Code: Bot Forex/Emas dengan Paper Trading

> Cara pakai: buat folder proyek baru, simpan file ini di dalamnya, lalu di Claude Code ketik:
> "Baca PROMPT_BOT_FOREX.md dan kerjakan sesuai fase. Mulai dari Fase 1, tanyakan dulu kalau ada yang belum jelas."
>
> Ubah bagian **[ISI SENDIRI]** sesuai kebutuhanmu sebelum dijalankan.

---

## Tujuan

Bangun bot trading forex dan emas dalam **Python** yang terhubung ke **MetaTrader 5** lewat library resmi `MetaTrader5`. Bot harus punya tiga mode dengan logika strategi yang sama persis:

1. **backtest**: menguji strategi dengan data historis.
2. **paper**: trading simulasi memakai harga live, tanpa mengirim order sungguhan.
3. **live**: order sungguhan ke akun MT5 (demo atau real).

Prioritas utama: **keamanan modal dan keandalan**, bukan fitur sebanyak-banyaknya.

## Parameter awal [ISI SENDIRI]

- Instrumen: `EURUSD`, `XAUUSD`
- Timeframe: `M15`
- Modal paper trading awal: `1000 USD`
- Risiko per transaksi: `1%` dari equity
- Batas rugi harian: `3%` dari equity awal hari
- Maksimal posisi terbuka bersamaan: `2`
- Strategi awal: contoh sederhana EMA 20/50 crossover + stop loss berbasis ATR(14) x 1.5, take profit 2R (hanya sebagai placeholder; strategi harus mudah diganti)
- Notifikasi: Telegram (opsional)

## Arsitektur yang diinginkan

```
forex-bot/
├── config/
│   └── config.yaml          # semua parameter, tanpa hardcode
├── .env.example             # login MT5, token Telegram (jangan commit .env)
├── src/
│   ├── main.py              # entry point: --mode backtest|paper|live
│   ├── data/
│   │   ├── mt5_feed.py      # ambil candle & tick dari MT5
│   │   └── csv_feed.py      # data historis dari file CSV
│   ├── strategy/
│   │   ├── base.py          # interface Strategy: on_bar() -> Signal
│   │   └── ema_atr.py       # contoh strategi
│   ├── broker/
│   │   ├── base.py          # interface Broker: open, close, modify, positions, account
│   │   ├── paper_broker.py  # simulasi eksekusi
│   │   └── mt5_broker.py    # eksekusi sungguhan via MT5
│   ├── risk/
│   │   └── risk_manager.py  # position sizing, batas harian, kill switch
│   ├── storage/
│   │   └── db.py            # SQLite: trades, equity curve, log event
│   └── notify/
│       └── telegram.py
├── tests/
└── README.md
```

Prinsip penting: **Strategy tidak boleh tahu sedang di mode apa.** Strategi hanya menerima data candle dan mengeluarkan sinyal; Broker yang berbeda per mode.

## Spesifikasi Paper Broker

Paper trading harus realistis, bukan sekadar mencatat harga:

- Eksekusi memakai harga **bid/ask** live dari MT5 (beli di ask, jual di bid).
- Simulasikan **spread** sebenarnya dari tick, plus **slippage** yang bisa diatur di config.
- Hitung **komisi** per lot (bisa diatur).
- Cek stop loss dan take profit setiap tick/candle, termasuk kasus harga gap melewati SL.
- Hitung nilai pip dan ukuran kontrak per simbol dengan benar (XAUUSD berbeda dengan EURUSD); ambil dari `mt5.symbol_info()` bila tersedia.
- Lacak balance, equity, margin terpakai, dan floating PnL.
- State paper (posisi terbuka, balance) disimpan ke SQLite agar bisa dilanjutkan setelah bot di-restart.

## Manajemen risiko (wajib, berlaku di semua mode)

- Ukuran lot dihitung dari: equity × risiko% ÷ (jarak SL dalam pip × nilai pip), dibulatkan ke bawah sesuai `volume_step`, dan dibatasi `volume_min`/`volume_max`.
- Tolak order tanpa stop loss.
- Hentikan buka posisi baru jika batas rugi harian tercapai, sampai hari berikutnya.
- **Kill switch**: tutup semua posisi dan berhenti jika terjadi error berulang, koneksi MT5 putus terlalu lama, atau file `STOP` dibuat di folder proyek.
- Hindari trading menjelang rilis berita besar (siapkan hook-nya dulu; implementasi kalender berita bisa menyusul).
- Jangan trading di luar jam pasar atau saat spread melebar di atas batas config.

## Mode live: pengaman ekstra

- Mode live hanya berjalan jika ada flag `--confirm-live` **dan** `live_enabled: true` di config.
- Saat start, tampilkan nama akun, server, jenis akun (demo/real), dan balance, lalu minta konfirmasi.
- Gunakan `magic number` khusus agar bot hanya mengelola posisi miliknya sendiri.

## Logging & laporan

- Semua transaksi tersimpan di SQLite: waktu, simbol, arah, lot, harga masuk/keluar, SL, TP, PnL, alasan masuk/keluar.
- Laporan backtest dan paper: total trade, win rate, profit factor, max drawdown, rata-rata R, dan grafik equity curve (simpan sebagai PNG/HTML).
- Notifikasi Telegram saat buka/tutup posisi, batas harian tercapai, dan error.

## Fase pengerjaan

Kerjakan satu fase per satu, jalankan test, lalu tunjukkan hasilnya sebelum lanjut.

1. **Fondasi**: struktur proyek, config, interface Strategy & Broker, koneksi MT5 untuk ambil data candle.
2. **Backtest**: csv_feed, paper_broker dipakai untuk backtest, strategi contoh, laporan + equity curve. Sediakan skrip untuk mengunduh data historis dari MT5 ke CSV.
3. **Paper trading live**: loop utama yang memproses candle baru, risk manager, penyimpanan state, logging.
4. **Notifikasi & kill switch**: Telegram, file STOP, penanganan reconnect.
5. **Mode live**: mt5_broker dengan semua pengaman di atas. Uji hanya di **akun demo** dulu.

## Catatan teknis

- Library `MetaTrader5` hanya berjalan di **Windows** dengan terminal MT5 terpasang dan login. Jika saya sedang di Mac/Linux, beri tahu saya dan buat agar mode backtest tetap bisa jalan dengan data CSV.
- Tulis unit test untuk perhitungan lot, nilai pip, PnL, dan pengecekan SL/TP di paper broker, karena di sinilah bug paling mahal.
- Jangan pernah menyimpan password atau token di kode; pakai `.env`.
- Buat README berisi cara instalasi, cara menjalankan tiap mode, dan cara menambahkan strategi baru.
