# Strategi dari TradingAgents untuk Bot Forex

*Disarikan dari kode TradingAgents v0.7.1 (TauricResearch, Apache 2.0) per 8 November 2026, lalu disesuaikan agar bisa dikerjakan oleh Claude Code sebagai tambahan untuk PROMPT_BOT_FOREX.md. Ini bahan riset, bukan saran investasi.*

---

## 1. Apa "strategi" yang sebenarnya ada di repo itu

TradingAgents **tidak punya aturan entry/exit yang tetap**. Strateginya adalah *proses pengambilan keputusan*:

1. **Analis teknikal** memilih maksimal 8 indikator dari daftar tetap: SMA 50, SMA 200, EMA 10, MACD (line, signal, histogram), RSI, Bollinger Bands (tengah, atas, bawah), ATR, dan VWMA.
2. **Analis berita & makro** membaca berita global, data makro (FRED), dan **probabilitas pasar prediksi (Polymarket)**.
3. **Analis sentimen** membaca Reddit dan StockTwits.
4. **Peneliti bullish vs bearish** berdebat, lalu Research Manager membuat rencana.
5. **Trader** mengubah rencana menjadi Buy/Hold/Sell, dengan entry dan stop loss **berdasarkan ATR dan support/resistance**.
6. **Tim risiko** (agresif, netral, konservatif) berdebat, lalu **Portfolio Manager** memberi rating 5 tingkat: **Buy, Overweight, Hold, Underweight, Sell**. Aturannya: konflik pendapat bukan alasan untuk Hold; pilih sisi yang lebih kuat dan sesuaikan ukuran posisi dengan seberapa kuat kasusnya.
7. **Memori & refleksi**: setiap keputusan dicatat. Setelah periode tahan (default 5 hari) lewat, hasilnya dihitung dan LLM menulis "pelajaran", yang dibaca oleh Portfolio Manager pada keputusan berikutnya.
8. **Disiplin point-in-time**: setiap data hanya boleh yang sudah terbit pada tanggal analisis, untuk mencegah look-ahead bias.

## 2. Bagian yang layak diambil (dan yang tidak)

| Ambil | Alasan |
|---|---|
| Rating 5 tingkat → ukuran posisi | Cara sederhana menghubungkan keyakinan dengan risiko |
| Stop loss berbasis ATR | Sudah sejalan dengan bot kamu |
| Lapisan berita/makro + Polymarket | Forex sangat dipengaruhi suku bunga dan rilis data; probabilitas keputusan bank sentral di Polymarket bisa jadi input bagus, dan kamu sudah punya bot Polymarket |
| Debat bull vs bear | Mengurangi bias satu arah dari LLM |
| Memori refleksi | Evaluasi diri otomatis |
| Disiplin point-in-time | Wajib untuk backtest yang jujur |

| Jangan diambil | Alasan |
|---|---|
| Analis fundamental & SEC EDGAR | Untuk saham, tidak relevan di forex |
| Sentimen Reddit/StockTwits | Sangat lemah untuk pair forex |
| Menjalankan seluruh pipeline setiap candle | Terlalu lambat dan mahal; hasilnya juga tidak deterministik |
| Data Yahoo untuk eksekusi | XAUUSD dipetakan ke futures GC=F, berbeda dengan harga broker; gunakan data MT5 |

## 3. Strategi yang diusulkan: "Bias Harian + Eksekusi Pullback"

Gabungan versi deterministik dari analis teknikal TradingAgents, lapisan LLM ringan untuk berita/makro, dan strategi pullback dari RISET_STRATEGI_FOREX.md.

### Lapisan A — Skor teknikal harian (tanpa LLM, deterministik)

Dihitung sekali sehari setelah candle D1 tutup, per pair. Setiap poin bernilai +1 (bullish) atau −1 (bearish):

| Komponen | Bullish (+1) | Bearish (−1) |
|---|---|---|
| Tren panjang | Close > SMA 200 | Close < SMA 200 |
| Struktur tren | SMA 50 > SMA 200 | SMA 50 < SMA 200 |
| Momentum | MACD histogram > 0 | MACD histogram < 0 |
| Momentum jangka pendek | Close > EMA 10 | Close < EMA 10 |
| RSI | RSI 50–70 | RSI 30–50 |

RSI di atas 70 atau di bawah 30 bernilai 0 (terlalu jenuh untuk mengejar). Skor total −5 sampai +5.

### Lapisan B — Bias makro dari LLM (opsional, sekali sehari)

Pipeline ringan yang meniru TradingAgents dengan biaya kecil, sekitar 4 panggilan LLM per pair per hari:

1. **Analis makro**: input berupa ringkasan berita 24 jam terakhir, kalender ekonomi hari ini, selisih suku bunga kedua mata uang, dan probabilitas Polymarket untuk keputusan bank sentral terkait.
2. **Bull** dan **Bear**: masing-masing satu argumen singkat.
3. **Hakim**: output JSON terstruktur `{"rating": "Buy|Overweight|Hold|Underweight|Sell", "alasan": "...", "risiko_utama": "..."}` dengan aturan TradingAgents: konflik bukan alasan Hold; Hold hanya jika bukti seimbang atau terlalu tipis.

Masukkan 5 pelajaran terbaru dari memori ke prompt hakim.

### Penggabungan menjadi rating akhir

- Ubah skor teknikal menjadi rating: +4/+5 = Buy, +2/+3 = Overweight, −1 sampai +1 = Hold, −2/−3 = Underweight, −4/−5 = Sell.
- Jika Lapisan B aktif:
  - Arah sama → pakai rating yang lebih kuat.
  - Satu Hold, satu berarah → turunkan satu tingkat (misalnya Buy menjadi Overweight).
  - Arah berlawanan → **Hold** (tidak ada posisi baru hari itu).

### Ukuran risiko dari rating

| Rating akhir | Arah yang diizinkan | Risiko per transaksi |
|---|---|---|
| Buy | Hanya buy | 1% |
| Overweight | Hanya buy | 0,5% |
| Hold | Tidak buka posisi baru | 0% |
| Underweight | Hanya sell | 0,5% |
| Sell | Hanya sell | 1% |

### Lapisan C — Eksekusi di H1 (deterministik)

Hanya searah bias harian:
- **Entry**: harga koreksi ke area EMA 20–50 H1, lalu candle H1 tutup kembali searah bias.
- **Stop loss**: ATR(14) H1 × 1,5 dari entry, atau di balik swing terdekat (pilih yang lebih jauh, tetap dibatasi maksimal ATR × 2,5).
- **Take profit**: 2R, atau setengah posisi di 1R lalu sisanya trailing ATR.
- **Time stop**: tutup posisi yang belum mencapai TP/SL setelah 5 hari trading (sama dengan periode tahan default TradingAgents).
- Jika bias harian berbalik ke arah berlawanan, tutup posisi yang masih terbuka.

### Filter tambahan
- Tidak membuka posisi 30 menit sebelum sampai 30 menit setelah rilis berdampak tinggi untuk mata uang terkait.
- Maksimal 1 posisi per pair dan total risiko terbuka maksimal 2%.

## 4. Memori & refleksi

- Setiap hari simpan: tanggal, pair, skor teknikal, rating LLM, rating akhir, dan alasan.
- Setelah 5 hari, hitung hasil arah bias (pergerakan harga searah atau tidak, dalam satuan ATR) dan hasil transaksi yang diambil.
- Minta LLM menulis satu paragraf pelajaran singkat; simpan di SQLite dan tampilkan 5 terbaru ke hakim.
- Laporan mingguan: akurasi bias per pair, per tingkat rating, dan apakah Lapisan B menambah nilai.

## 5. Cara menguji dengan jujur

1. **Backtest Lapisan A + C saja** dengan data MT5 (deterministik dan murah). Lihat apakah skor teknikal dan pullback punya edge setelah biaya.
2. **Jangan backtest Lapisan B di masa lalu.** LLM sudah "mengetahui" peristiwa sebelum tanggal batas pengetahuannya, jadi backtest historis akan terlalu optimis. TradingAgents berusaha menutup celah data, tetapi pengetahuan di dalam model sendiri tetap tidak bisa dihapus.
3. **Uji Lapisan B hanya secara forward**, lewat paper trading:
   - Varian 1: A + C (tanpa LLM)
   - Varian 2: A + B + C
   Jalankan paralel minimal 2–3 bulan. Pertahankan Lapisan B hanya jika hasilnya lebih baik secara nyata setelah biaya LLM.

## 6. Instruksi untuk Claude Code

Tambahkan ke proyek bot forex sebagai fase setelah Fase 3 (paper trading berjalan):

- `src/strategy/daily_bias.py` — skor teknikal Lapisan A dan pemetaan ke rating.
- `src/strategy/pullback_h1.py` — eksekusi Lapisan C yang membaca rating harian dan risiko per rating.
- `src/llm/macro_judge.py` — Lapisan B (analis makro → bull → bear → hakim, output JSON tervalidasi Pydantic). Penyedia LLM dan model diatur di config; matikan dengan `llm_bias_enabled: false`.
- `src/data/news_calendar.py` dan `src/data/polymarket_probs.py` — input untuk Lapisan B; jika sumber gagal, catat dan lanjutkan dengan rating Hold dari Lapisan B (jangan menebak).
- `src/memory/reflection.py` — log keputusan, penyelesaian setelah 5 hari, dan pelajaran.
- Mode paper harus bisa menjalankan dua varian (dengan dan tanpa LLM) secara paralel dengan akun virtual terpisah.
- Unit test untuk skor teknikal, pemetaan rating, aturan penggabungan, dan ukuran risiko.
- Setiap pemanggilan LLM mencatat token dan biaya, supaya laporan bisa membandingkan hasil dengan biayanya.

## Sumber

- Kode TradingAgents: https://github.com/TauricResearch/TradingAgents (terutama `agents/analysts/market_analyst.py`, `agents/trader/trader.py`, `agents/managers/portfolio_manager.py`, `agents/rating.py`)
- Paper: Xiao dkk., *TradingAgents: Multi-Agents LLM Financial Trading Framework*, arXiv:2412.20138
