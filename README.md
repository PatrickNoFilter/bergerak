# Bergerak

Pipeline video infografis vertikal gratis — dari naskah jadi MP4 9:16 siap Reels / Shorts / TikTok.

Cara kerjanya: naskah dipecah jadi beat → tiap beat dibacakan Edge-TTS (suara Indonesia `id-ID-ArdiNeural`, gratis, tanpa API key) dengan penanda kata-per-kata → animasi HTML 1080×1920 digerakkan oleh jam audio → frame di-render deterministik lalu digabung dengan narasi via FFmpeg, lengkap dengan subtitle per kata yang menyala mengikuti suara.

Video pertama yang dibuat dengan pipeline ini: **penyadapan edukasi** (80 detik, 6 beat, 4 Nov 2026) — file contohnya ada di repo ini (`beats.txt` + `animasi.html`).

Semua alatnya gratis: Edge-TTS, Playwright + Chromium, FFmpeg. Tidak ada API key berbayar, tidak ada SaaS.

## Isi repo

| File | Fungsi |
|---|---|
| `beats.txt` | Naskah, satu beat per baris: `B1\|teks narasi…` (contoh: penyadapan edukasi) |
| `ws_tts.py` | **Utama.** TTS per beat → `beatN.mp3` + `beatN.srt` + `beatN.words.json` (timing kata). Klien WebSocket manual untuk Edge-TTS. |
| `gen_tts.py` | Alternatif TTS via `edge-tts` + aiohttp (dengan patch handshake WebSocket). |
| `concat.txt` | Daftar `beatN.mp3` untuk digabung jadi `narasi.mp3` |
| `build_timing.py` | Gabung semua `beatN.words.json` + durasi ffprobe → `timing.js` (`WORDS`, `BEATS`, `TOTAL`) |
| `animasi.html` | Template animasi 1080×1920: 6 scene (`data-beat="0"–"5"`), progress bar, subtitle per kata. **Contoh ini spesifik untuk video penyadapan** — untuk video baru, ganti isi scene-nya, pertahankan struktur `data-beat`, `window.start()`, dan `window.renderFrame(t)`. |
| `render_frames.py` | **Render yang dipakai.** Tangkap tiap frame di waktu `t` via `window.renderFrame(t)`, lalu rakit dengan FFmpeg. Sinkron audio/video dijamin, tidak tergantung kecepatan render headless. |
| `render.py` | Alternatif: rekam halaman headless Chromium sambil narasi diputar (real-time). |
| `examples/bps-q3-2026/beats.txt` | Naskah contoh kedua: infografis PDB Q3 2026 (BPS, 5 Nov 2026), 6 beat, ~90 detik. |

## Prasyarat

- Python 3.12
- FFmpeg + ffprobe (`ffmpeg -version`)
- Playwright + Chromium: `pip install -r requirements.txt` lalu `playwright install chromium`
- Chromium/Chrome untuk Playwright: skrip render memakai `chrome-linux64/chrome` di folder ini (tidak ikut di-commit, ukurannya ~300 MB). Unduh Chrome for Testing ke `chrome-linux64/`, atau ubah konstanta `CHROME` di `render.py` / `render_frames.py` ke path Chromium Playwright kamu.

## Cara pakai (video baru)

```bash
# 1. Tulis naskah di beats.txt — satu beat per baris, format B1|teks…
# 2. TTS per beat (pakai ws_tts.py; jeda 5 detik antar beat menghindari rate limit)
python ws_tts.py

# 3. Gabung jadi satu narasi
ffmpeg -y -f concat -safe 0 -i concat.txt -c copy narasi.mp3

# 4. Bangun timing subtitle dari word timing + durasi tiap beat
python build_timing.py   # → timing.js

# 5. Edit animasi.html: ganti isi tiap <section class="scene" data-beat="N">
#    sesuai beat-mu. Jangan ubah id="nar", window.start(), window.renderFrame(t).

# 6. Render (deterministik, direkomendasikan)
python render_frames.py  # → <nama-video>.mp4  (ubah nama output di skrip)
```

Output: MP4 1080×1920, 30 fps, H.264 + AAC, subtitle per kata dibakar di animasi (bukan trek subtitle terpisah).

## Catatan

- `ws_tts.py` dan `gen_tts.py` berisi patch khusus untuk egress proxy / CA bundle di mesin build asal (`/run/hatch/egress-tls/ca-bundle.pem`). Di mesin biasa, Edge-TTS standar tanpa patch itu sudah jalan — hapus bagian patch CA/proxy bila tidak dibutuhkan.
- `build_timing.py` saat ini mengasumsikan 6 beat (`range(1, 7)`). Kalau beat-mu bukan 6, sesuaikan angka itu dan jumlah `<section>` di `animasi.html`.
- File hasil (`*.mp3`, `*.srt`, `*.words.json`, `timing.js`, `*.mp4`, `frames/`, `rec/`, `chrome-linux64/`, `venv/`) sengaja tidak di-commit — semuanya bisa dibuat ulang dari `beats.txt` + `animasi.html`. Lihat `.gitignore`.

## Lisensi

Belum ada lisensi — semua hak dilindungi untuk saat ini. Kalau mau dibuka (mis. MIT), tinggal tambah file `LICENSE`.
