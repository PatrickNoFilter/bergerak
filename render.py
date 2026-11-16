#!/usr/bin/env python3
"""Render animasi.html to video: headless Chrome records the page while the
narration MP3 plays; visuals are driven by the audio clock for inherent sync."""
import subprocess, time, os, sys
from playwright.sync_api import sync_playwright

WORK = os.path.dirname(os.path.abspath(__file__))
CHROME = os.path.join(WORK, "chrome-linux64", "chrome")
URL = "http://127.0.0.1:8901/animasi.html"

# start a local server
server = subprocess.Popen(
    [sys.executable, "-m", "http.server", "8901", "--bind", "127.0.0.1"],
    cwd=WORK, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            args=["--autoplay-policy=no-user-gesture-required",
                  "--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(
            viewport={"width": 1080, "height": 1920},
            device_scale_factor=1,
            record_video_dir=os.path.join(WORK, "rec"),
            record_video_size={"width": 1080, "height": 1920},
        )
        page = ctx.new_page()
        page.goto(URL)
        page.wait_for_function("typeof window.start === 'function' && typeof TOTAL !== 'undefined'")
        page.wait_for_function("document.getElementById('nar').readyState >= 2", timeout=30000)
        total = page.evaluate("window.duration()")
        print(f"audio duration in page: {total:.2f}s", flush=True)
        # start playback; the promise resolves when audio ends
        page.evaluate("window.start()")
        # wait for finish with margin
        page.wait_for_function(
            "document.getElementById('nar').ended", timeout=int((total + 30) * 1000))
        time.sleep(2.5)  # tail
        video_path = page.video.path()
        ctx.close()
        browser.close()
    print("raw video:", video_path, flush=True)
    # mux with narration audio
    out = os.path.join(WORK, "penyadapan-edukasi.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", os.path.join(WORK, "narasi.mp3"),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", out,
    ], check=True)
    print("DONE:", out, flush=True)
finally:
    server.terminate()
