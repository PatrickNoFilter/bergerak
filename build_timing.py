#!/usr/bin/env python3
"""Build timing.js: word-level subtitles with global offsets + beat ranges."""
import json, os, subprocess

WORK = os.path.dirname(os.path.abspath(__file__))

def duration(p):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(out.stdout.strip())

WORDS, BEATS = [], []
offset = 0.0
for i in range(1, 7):
    dur = duration(os.path.join(WORK, f"beat{i}.mp3"))
    with open(os.path.join(WORK, f"beat{i}.words.json"), encoding="utf-8") as f:
        wds = json.load(f)
    for w in wds:
        WORDS.append({"t0": round(offset + w["t"], 3),
                      "t1": round(offset + w["t"] + w["d"], 3),
                      "w": w["w"], "beat": i - 1})
    BEATS.append({"t0": round(offset, 3), "t1": round(offset + dur, 3)})
    offset += dur

with open(os.path.join(WORK, "timing.js"), "w", encoding="utf-8") as f:
    f.write("var WORDS=" + json.dumps(WORDS, ensure_ascii=False) + ";\n")
    f.write("var BEATS=" + json.dumps(BEATS) + ";\n")
    f.write("var TOTAL=" + str(round(offset, 3)) + ";\n")

print(f"words={len(WORDS)} beats={len(BEATS)} total={offset:.2f}s")
# sanity: check word coverage vs beat ranges
for i, b in enumerate(BEATS):
    ws = [w for w in WORDS if w["beat"] == i]
    if ws:
        print(f"beat{i+1}: range {b['t0']}-{b['t1']}, first word @{ws[0]['t0']}, last word ends @{ws[-1]['t1']}")
