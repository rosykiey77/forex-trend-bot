# Feature Specification: Forex & Gold Trading Bot (Backtest / Paper / Live)

**Feature Branch**: `001-forex-gold-bot` (dokumen di `docs/`, branch kerja: `main`)

**Created**: 2026-11-08

**Status**: Draft

**Input**: User description: "Bot trading Forex & Emas (EURUSD, XAUUSD) Python 3.11+ — 3 mode (Backtest CSV, Paper realistis spread/slippage/swap, Live via MT5 gateway REST/ZeroMQ karena MetaTrader5 lib hanya Windows), CSV feed & paper broker offline native Linux, risk mgmt (lot dinamis pip value + SL ATR, daily loss 3%, max 2 posisi, kill switch file STOP), SQLite journal & state, notifikasi Telegram." Sumber detail: `PROMPT_BOT_FOREX.md`, `docs/requirements.md`.

## User Scenarios & Testing *(mandatory)*

Aktor utama: **Operator** — satu orang trader ritel yang menjalankan bot di VPS Linux (dan opsional Windows VPS/Wine yang menjalankan terminal MetaTrader 5). Prioritas produk: **keamanan modal dan keandalan**, bukan banyaknya fitur.

### User Story 1 - Backtest strategi dengan data historis offline (Priority: P1)

Operator menyiapkan file data candle historis (EURUSD, XAUUSD, M15), menjalankan bot dalam mode backtest di Linux tanpa terminal MT5, lalu menerima laporan performa (total trade, win rate, profit factor, max drawdown, rata-rata R) dan grafik equity curve.

**Why this priority**: Tanpa backtest, operator tidak bisa menilai strategi sebelum mempertaruhkan uang. Ini juga satu-satunya mode yang 100% jalan di Linux tanpa ketergantungan eksternal, jadi menjadi MVP.

**Independent Test**: Jalankan mode backtest pada file data contoh; laporan dan grafik equity terbentuk, dan seluruh transaksi tercatat di jurnal.

**Acceptance Scenarios**:

1. **Given** file data historis valid untuk EURUSD dan XAUUSD, **When** operator menjalankan mode backtest, **Then** bot memproses semua candle secara berurutan dan menghasilkan laporan metrik + grafik equity curve.
2. **Given** sinyal masuk dari strategi, **When** order disimulasikan, **Then** eksekusi memakai harga beli di ask dan jual di bid (spread), ditambah slippage, komisi, dan swap sesuai konfigurasi.
3. **Given** candle yang membuka (gap) di luar level stop loss, **When** posisi dicek, **Then** posisi ditutup pada harga open candle tersebut (bukan pada level SL), dan kerugian aktual tercatat.
4. **Given** file data dengan baris rusak/hilang atau urutan waktu salah, **When** backtest dimulai, **Then** bot menolak file dengan pesan error yang menyebut baris/masalahnya.

---

### User Story 2 - Paper trading realistis dengan state yang bertahan restart (Priority: P2)

Operator menjalankan bot dalam mode paper: bot memproses candle baru secara berkala, membuka/menutup posisi simulasi dengan biaya realistis (spread, slippage, komisi, swap), menegakkan semua aturan risiko, dan menyimpan state sehingga bot dapat dilanjutkan setelah restart.

**Why this priority**: Paper trading membuktikan bot berperilaku benar dalam kondisi waktu-nyata sebelum uang sungguhan dipakai.

**Independent Test**: Jalankan mode paper dengan sumber harga (gateway MT5 bila ada, atau replay data offline), hentikan proses di tengah posisi terbuka, jalankan lagi — balance dan posisi terbuka sama persis seperti sebelum dihentikan.

**Acceptance Scenarios**:

1. **Given** mode paper aktif dan sinyal valid, **When** order dibuka, **Then** ukuran lot dihitung dari equity × risiko% ÷ (jarak SL dalam pip × nilai pip), dibulatkan ke bawah sesuai langkah volume, dan dibatasi volume minimum/maksimum simbol.
2. **Given** posisi terbuka melewati pergantian hari trading (rollover), **When** rollover terjadi, **Then** swap long/short dibebankan/dikreditkan sesuai konfigurasi simbol (termasuk triple swap pada hari yang dikonfigurasi).
3. **Given** bot dihentikan paksa dengan posisi terbuka, **When** bot dijalankan kembali, **Then** balance, equity, posisi terbuka, dan status batas harian dipulihkan dari penyimpanan.
4. **Given** bot berjalan di Linux tanpa akses MT5, **When** mode paper dijalankan dengan sumber data offline, **Then** bot tetap berjalan penuh (replay data) tanpa error terkait MT5.

---

### User Story 3 - Pengaman risiko & kill switch berlaku di semua mode (Priority: P2)

Operator yakin bahwa apapun sinyal strateginya, bot tidak akan melampaui batas risiko: maksimal 2 posisi terbuka, berhenti membuka posisi setelah rugi harian 3%, menolak order tanpa stop loss, dan berhenti total bila file `STOP` muncul atau terjadi error berulang.

**Why this priority**: Ini inti tujuan "keamanan modal"; harus ada sebelum mode live.

**Independent Test**: Simulasikan rangkaian kerugian hingga 3% dan buat file `STOP`; verifikasi tidak ada order baru dan semua posisi ditutup.

**Acceptance Scenarios**:

1. **Given** sudah ada 2 posisi terbuka, **When** strategi mengeluarkan sinyal baru, **Then** sinyal ditolak dan alasannya dicatat.
2. **Given** kerugian (realized + floating) hari ini mencapai 3% dari equity awal hari, **When** sinyal baru muncul, **Then** tidak ada posisi baru dibuka sampai hari trading berikutnya, dan notifikasi "batas harian tercapai" dikirim sekali.
3. **Given** file `STOP` dibuat di folder proyek, **When** bot memeriksa kondisi pada siklus berikutnya, **Then** bot menutup semua posisi miliknya, mengirim notifikasi, dan berhenti.
4. **Given** sinyal tanpa stop loss, **When** diteruskan ke eksekusi, **Then** order ditolak.
5. **Given** spread saat ini melebihi batas konfigurasi atau pasar tutup, **When** sinyal muncul, **Then** order tidak dibuka dan alasannya dicatat.
6. **Given** error berturut-turut melebihi ambang konfigurasi atau koneksi ke gateway terputus lebih lama dari batas waktu, **When** ambang terlampaui, **Then** kill switch aktif (tutup semua posisi bila masih memungkinkan, notifikasi, berhenti).

---

### User Story 4 - Notifikasi & jurnal transaksi (Priority: P3)

Operator menerima pesan Telegram saat posisi dibuka, ditutup (termasuk kena TP atau SL), batas harian tercapai, kill switch aktif, dan error; serta dapat meninjau semua transaksi di jurnal.

**Why this priority**: Pemantauan jarak jauh penting, tetapi bot tetap berfungsi tanpanya.

**Independent Test**: Dengan kredensial Telegram terisi, buka dan tutup posisi paper; pesan diterima. Tanpa kredensial, bot tetap jalan tanpa error.

**Acceptance Scenarios**:

1. **Given** notifikasi aktif, **When** posisi dibuka, **Then** pesan berisi simbol, arah, lot, harga masuk, SL, TP terkirim.
2. **Given** posisi ditutup karena TP/SL/sinyal/kill switch, **When** penutupan terjadi, **Then** pesan berisi harga keluar, PnL, R, dan alasan keluar terkirim.
3. **Given** layanan Telegram tidak dapat dihubungi, **When** notifikasi gagal, **Then** trading tidak terganggu dan kegagalan dicatat di log.
4. **Given** transaksi apapun di mode manapun, **When** ditutup, **Then** jurnal menyimpan waktu, simbol, arah, lot, harga masuk/keluar, SL, TP, biaya (spread/slippage/komisi/swap), PnL, dan alasan masuk/keluar.

---

### User Story 5 - Live trading via gateway MT5 dengan konfirmasi ganda (Priority: P3)

Operator di VPS Linux menghubungkan bot ke terminal MT5 yang berjalan di Windows VPS atau Wine melalui gateway jaringan, lalu menjalankan mode live (diuji di akun demo dulu). Bot hanya mengelola posisi miliknya sendiri.

**Why this priority**: Nilai akhir produk, tetapi berisiko tertinggi dan bergantung pada semua story sebelumnya.

**Independent Test**: Terhubung ke akun demo via gateway, jalankan mode live dengan konfirmasi; satu siklus buka-tutup posisi tercermin identik di terminal MT5 dan di jurnal.

**Acceptance Scenarios**:

1. **Given** mode live diminta tanpa flag konfirmasi live **atau** tanpa `live_enabled: true` di konfigurasi, **When** bot dijalankan, **Then** bot menolak start dengan pesan yang jelas.
2. **Given** kedua pengaman terpenuhi, **When** bot start, **Then** bot menampilkan nama akun, server, jenis akun (demo/real), dan balance, lalu meminta konfirmasi interaktif sebelum trading.
3. **Given** akun memiliki posisi manual atau dari EA lain, **When** bot mengelola posisi, **Then** hanya posisi dengan magic number bot yang disentuh.
4. **Given** gateway tidak tersedia, **When** mode live dijalankan, **Then** bot gagal start dengan pesan yang menjelaskan cara menjalankan gateway, dan mode backtest/paper offline tetap dapat dipakai.

---

### Edge Cases

- Data historis berisi gap akhir pekan/hari libur: dianggap normal, bukan error; swap tetap dihitung per rollover.
- Gap harga melewati SL atau TP: eksekusi pada harga open candle/tick pertama yang tersedia (lebih buruk untuk SL, tidak "lebih baik" dari TP).
- SL dan TP sama-sama tersentuh dalam satu candle (backtest bar-level): asumsi konservatif — SL dianggap kena lebih dulu.
- Lot hasil perhitungan di bawah volume minimum simbol: order dilewati (tidak dibulatkan ke atas) dan alasannya dicatat.
- Jarak SL nol atau ATR belum tersedia (warm-up indikator): tidak ada sinyal/order.
- Restart di tengah hari setelah batas harian tercapai: status "terkunci hari ini" tetap berlaku.
- Pergantian hari trading ditentukan oleh zona waktu server broker yang dikonfigurasi, bukan zona waktu VPS.
- Penyimpanan rusak/tidak dapat ditulis: bot berhenti aman alih-alih trading tanpa jurnal.
- File `STOP` sudah ada saat start: bot tidak memulai trading.
- Akun dengan mata uang deposit selain USD: nilai pip dikonversi ke mata uang akun.
- Dua instance bot berjalan pada penyimpanan yang sama: instance kedua menolak start.

## Requirements *(mandatory)*

### Functional Requirements

**Mode & lingkungan**

- **FR-001**: Sistem MUST menyediakan tiga mode — backtest, paper, live — yang dipilih saat start, memakai logika strategi dan aturan risiko yang identik.
- **FR-002**: Strategi MUST tidak mengetahui mode yang sedang berjalan; strategi hanya menerima data candle dan mengeluarkan sinyal (arah, SL, TP, alasan).
- **FR-003**: Strategi MUST dapat diganti melalui konfigurasi tanpa mengubah komponen lain. Strategi awal (placeholder): EMA 20/50 crossover, SL = ATR(14) × 1.5, TP = 2R.
- **FR-004**: Mode backtest dan mode paper dengan sumber data offline MUST berjalan penuh di Linux tanpa terminal MT5 dan tanpa pustaka yang hanya tersedia di Windows.
- **FR-005**: Sistem MUST dapat terhubung ke terminal MT5 jarak jauh (Windows VPS atau Wine) melalui gateway jaringan untuk mengambil data harga, info simbol, info akun, dan mengirim order. Protokol gateway (REST atau message-queue) dipilih di konfigurasi.
- **FR-006**: Sistem MUST menyediakan cara mengunduh data historis dari MT5 (via gateway) ke file data untuk backtest.

**Data & simbol**

- **FR-007**: Sistem MUST mendukung minimal EURUSD dan XAUUSD pada timeframe M15, dengan simbol dan timeframe dapat dikonfigurasi.
- **FR-008**: Sistem MUST memvalidasi file data historis (kolom wajib, urutan waktu naik, tanpa duplikat, harga positif, high ≥ low) dan menolak file tidak valid dengan pesan spesifik.
- **FR-009**: Sistem MUST menghitung nilai pip dan ukuran kontrak per simbol dengan benar (XAUUSD berbeda dari EURUSD); memakai spesifikasi dari terminal bila tersedia, jika tidak dari konfigurasi.

**Simulasi eksekusi (backtest & paper)**

- **FR-010**: Eksekusi simulasi MUST membeli di harga ask dan menjual di harga bid, memakai spread aktual dari data bila ada atau spread konfigurasi bila tidak.
- **FR-011**: Eksekusi simulasi MUST menerapkan slippage dan komisi per lot yang dapat dikonfigurasi.
- **FR-012**: Eksekusi simulasi MUST membebankan/mengkreditkan swap long/short per simbol pada setiap rollover harian, termasuk triple swap pada hari yang dikonfigurasi.
- **FR-013**: Sistem MUST memeriksa SL dan TP setiap candle/tick, termasuk gap melewati SL/TP (eksekusi di harga gap).
- **FR-014**: Sistem MUST melacak balance, equity, margin terpakai, dan floating PnL.

**Manajemen risiko (semua mode)**

- **FR-015**: Ukuran lot MUST = equity × risiko% ÷ (jarak SL dalam pip × nilai pip per lot), dibulatkan ke bawah ke langkah volume dan dibatasi volume min/max. Risiko default 1%.
- **FR-016**: Sistem MUST menolak order tanpa stop loss.
- **FR-017**: Sistem MUST menolak posisi baru bila sudah ada 2 posisi terbuka (nilai dapat dikonfigurasi).
- **FR-018**: Sistem MUST berhenti membuka posisi baru setelah kerugian hari ini (realized + floating) mencapai 3% dari equity awal hari, hingga hari trading berikutnya.
- **FR-019**: Sistem MUST mengaktifkan kill switch — tutup semua posisi milik bot dan berhenti — bila: file `STOP` ada di folder proyek, error berturut-turut melewati ambang, atau koneksi gateway terputus lebih lama dari batas waktu.
- **FR-020**: Sistem MUST tidak membuka posisi di luar jam pasar atau ketika spread melebihi batas konfigurasi per simbol.
- **FR-021**: Sistem MUST menyediakan titik kaitan (hook) filter berita yang dapat memblokir entry; implementasi kalender berita di luar cakupan versi ini.

**Live**

- **FR-022**: Mode live MUST hanya berjalan bila flag konfirmasi live diberikan **dan** `live_enabled: true` di konfigurasi.
- **FR-023**: Saat start live, sistem MUST menampilkan nama akun, server, jenis akun (demo/real), dan balance, lalu meminta konfirmasi interaktif.
- **FR-024**: Sistem MUST menandai order dengan magic number khusus dan hanya mengelola posisi bermagic number tersebut.

**Penyimpanan & laporan**

- **FR-025**: Sistem MUST mencatat setiap transaksi ke jurnal lokal persisten: waktu masuk/keluar, simbol, arah, lot, harga masuk/keluar, SL, TP, biaya, PnL, R, alasan masuk/keluar, mode.
- **FR-026**: Sistem MUST menyimpan state (posisi terbuka, balance, status batas harian) dan memulihkannya saat restart.
- **FR-027**: Sistem MUST mencatat equity curve dan log event (error, kill switch, penolakan order beserta alasannya).
- **FR-028**: Laporan backtest dan paper MUST memuat total trade, win rate, profit factor, max drawdown, rata-rata R, dan grafik equity curve tersimpan sebagai file gambar/HTML.

**Notifikasi & konfigurasi**

- **FR-029**: Sistem MUST mengirim notifikasi Telegram saat entry, exit (termasuk TP dan SL), batas harian tercapai, kill switch, dan error — bila kredensial dikonfigurasi; kegagalan notifikasi tidak boleh menghentikan trading.
- **FR-030**: Semua parameter MUST berada di file konfigurasi (tanpa hardcode); kredensial (login MT5/gateway, token Telegram) MUST hanya dari variabel lingkungan / file env yang tidak di-commit.
- **FR-031**: Sistem MUST mencegah dua instance berjalan pada penyimpanan state yang sama.

### Key Entities *(include if feature involves data)*

- **Candle/Bar**: simbol, timeframe, waktu, open/high/low/close, volume, spread (opsional).
- **Symbol Spec**: simbol, ukuran kontrak, digit, ukuran pip, nilai pip per lot, volume min/max/step, swap long/short, hari triple swap, batas spread, jam pasar.
- **Signal**: simbol, arah (buy/sell/close), SL, TP, alasan; dihasilkan strategi.
- **Order/Position**: id, simbol, arah, lot, harga masuk, SL, TP, waktu buka, magic number, akumulasi swap/komisi, floating PnL.
- **Trade (jurnal)**: posisi yang sudah ditutup + harga keluar, waktu keluar, PnL, R, alasan keluar, mode.
- **Account State**: balance, equity, margin terpakai, equity awal hari, kerugian hari ini, status terkunci-harian, status kill switch.
- **Event Log**: waktu, level, jenis (error, reject, kill switch, notifikasi gagal), pesan.
- **Equity Point**: waktu, balance, equity.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Backtest 1 tahun data M15 untuk 2 simbol selesai dalam waktu kurang dari 2 menit di VPS standar (2 vCPU) dan menghasilkan laporan + grafik.
- **SC-002**: Menjalankan backtest yang sama dua kali menghasilkan jurnal dan metrik yang identik (deterministik).
- **SC-003**: Perhitungan lot, nilai pip, PnL, swap, dan pengecekan SL/TP cocok dengan hasil hitung manual pada seluruh kasus uji (selisih 0 setelah pembulatan ke langkah volume / 2 desimal mata uang akun).
- **SC-004**: Dalam 100% skenario uji, bot tidak pernah memiliki lebih dari 2 posisi terbuka, tidak pernah membuka posisi setelah batas rugi harian tercapai, dan tidak pernah mengirim order tanpa SL.
- **SC-005**: Setelah file `STOP` dibuat, semua posisi milik bot ditutup dan bot berhenti dalam satu siklus pemrosesan (≤ 60 detik dalam mode paper/live).
- **SC-006**: Setelah restart paksa, state yang dipulihkan (balance, posisi, status harian) 100% sama dengan sebelum berhenti.
- **SC-007**: Operator baru dapat memasang dan menjalankan backtest pertama di VPS Linux mengikuti README dalam waktu kurang dari 15 menit.
- **SC-008**: Notifikasi entry/exit diterima operator dalam ≤ 10 detik setelah kejadian pada kondisi jaringan normal.
- **SC-009**: Bot paper berjalan 7 hari berturut-turut tanpa intervensi manual dan tanpa crash yang tidak tertangani.

## Assumptions

- **Batasan teknologi yang ditetapkan operator** (bukan pilihan desain spesifikasi): bahasa Python 3.11+, penyimpanan SQLite, notifikasi Telegram, terminal MetaTrader 5 sebagai broker live. Pustaka resmi MetaTrader 5 hanya native di Windows, sehingga di Linux akses MT5 harus lewat gateway yang berjalan di sisi Windows/Wine.
- Pengguna tunggal (operator), tidak ada antarmuka web atau multi-user di versi ini; interaksi lewat baris perintah, file konfigurasi, dan Telegram.
- Mata uang akun default USD; modal paper awal 1000 USD.
- Mode paper di Linux tanpa gateway memakai replay data offline; bila gateway tersedia, mode paper memakai harga live bid/ask dari gateway.
- Backtest bekerja pada level candle M15 (bukan tick); spread diambil dari kolom data bila ada, jika tidak dari konfigurasi.
- Hari trading berganti mengikuti rollover broker (default 00:00 waktu server broker, dapat dikonfigurasi).
- Ambang kill switch default: 5 error berturut-turut, koneksi putus > 120 detik.
- Kalender berita, strategi tambahan (mis. Donchian breakout seperti disebut README), multi-akun, dan optimisasi parameter berada di luar cakupan versi ini.
- Gateway sisi Windows (komponen kecil yang meneruskan permintaan ke terminal MT5) termasuk dalam cakupan sebagai komponen pendamping; operator bertanggung jawab memasang terminal MT5 dan login akun.
- Mode live diuji hanya di akun demo sebelum dipakai di akun real.
