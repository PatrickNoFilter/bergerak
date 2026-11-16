#!/usr/bin/env python3
"""Deterministic frame capture: render each frame at its audio-timeline time
via window.renderFrame(t), screenshot, then assemble with ffmpeg. Guarantees
perfect A/V sync regardless of headless render speed."""
import subprocess, time, os, sys
from playwright.sync_api import sync_playwright

WORK = os.path.dirname(os.path.abspath(__file__))
CHROME = os.path.join(WORK, "chrome-linux64", "chrome")
FPS = 30
FRAMES = os.path.join(WORK, "frames")
os.makedirs(FRAMES, exist_ok=True)

server = subprocess.Popen(
    [sys.executable, "-m", "http.server", "8905", "--bind", "127.0.0.1"],
    cwd=WORK, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)

# total duration from timing data
import re
m = re.search(r"var TOTAL=([\d.]+)", open(os.path.join(WORK, "timing.js")).read())
total = float(m.group(1))
n_frames = int(total * FPS) + 1
print(f"capturing {n_frames} frames @ {FPS}fps", flush=True)
t0 = time.time()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto("http://127.0.0.1:8905/animasi.html")
        page.wait_for_function("typeof window.renderFrame==='function' && typeof TOTAL!=='undefined'")
        for i in range(n_frames):
            t = i / FPS
            page.evaluate(f"window.renderFrame({t})")
            page.screenshot(path=os.path.join(FRAMES, f"f{i:04d}.png"))
            if (i + 1) % 300 == 0:
                el = time.time() - t0
                print(f"  {i+1}/{n_frames} ({el:.0f}s, {el/(i+1)*1000:.0f}ms/frame)", flush=True)
        browser.close()
    print("capture done", flush=True)
    out = os.path.join(WORK, "penyadapan-edukasi.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-framerate", str(FPS), "-i", os.path.join(FRAMES, "f%04d.png"),
        "-i", os.path.join(WORK, "narasi.mp3"),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart", out,
    ], check=True)
    print("DONE:", out, flush=True)
finally:
    server.terminate()
