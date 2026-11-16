#!/usr/bin/env python3
"""Manual WebSocket client for edge-tts through the MITM egress proxy.

Bypasses aiohttp (whose strict 101 header validation fails because the proxy
rewrites 'Connection: upgrade' -> 'Connection: close'). Reuses edge-tts's own
message builders and auth, implements minimal WS framing over a raw socket.
"""
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import uuid
from urllib.parse import urlparse
from xml.sax.saxutils import escape

from edge_tts import drm
from edge_tts.communicate import (
    WSS_URL, connect_id, date_to_string, get_headers_and_data,
    mkssml, ssml_headers_plus_data,
)
from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS
from edge_tts.data_classes import TTSConfig
from edge_tts import SubMaker

CA = "/run/hatch/egress-tls/ca-bundle.pem"
VOICE = "id-ID-ArdiNeural"
WORK = os.path.dirname(os.path.abspath(__file__))
HOST = "speech.platform.bing.com"


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def _read_http_response(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("socket closed during handshake")
        buf += chunk
    head, _, _ = buf.partition(b"\r\n\r\n")
    return head.decode("latin1")


def connect_ws():
    p = urlparse(os.environ["HTTPS_PROXY"])
    s = socket.create_connection((p.hostname, p.port), timeout=20)
    auth = ""
    if p.username:
        tok = base64.b64encode(f"{p.username}:{p.password}".encode()).decode()
        auth = f"Proxy-Authorization: Basic {tok}\r\n"
    s.sendall(f"CONNECT {HOST}:443 HTTP/1.1\r\nHost: {HOST}:443\r\n{auth}\r\n".encode())
    resp = _recv_exact_line(s)
    if "200" not in resp:
        raise ConnectionError(f"proxy CONNECT failed: {resp}")
    ctx = ssl.create_default_context(cafile=CA)
    t = ctx.wrap_socket(s, server_hostname=HOST)

    url = (f"{WSS_URL}&ConnectionId={connect_id()}"
           f"&Sec-MS-GEC={drm.DRM.generate_sec_ms_gec()}"
           f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}")
    path = url.split(HOST, 1)[1]
    key = base64.b64encode(os.urandom(16)).decode()
    headers = drm.DRM.headers_with_muid(WSS_HEADERS)
    req_lines = [f"GET {path} HTTP/1.1", f"Host: {HOST}",
                 "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}"]
    # NOTE: Sec-WebSocket-Version comes from WSS_HEADERS; do not duplicate it.
    for k, v in headers.items():
        req_lines.append(f"{k}: {v}")
    req_lines.append("\r\n")
    t.sendall("\r\n".join(req_lines).encode("latin1"))
    hs = _read_http_response(t)
    status = hs.split("\r\n")[0]
    if "101" not in status:
        raise ConnectionError(f"WS handshake failed: {status}\n{hs[:500]}")
    # verify accept key
    accept = None
    for line in hs.split("\r\n"):
        if line.lower().startswith("sec-websocket-accept:"):
            accept = line.split(":", 1)[1].strip()
    expect = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode()
    if accept != expect:
        raise ConnectionError("bad Sec-WebSocket-Accept")
    t.settimeout(90)
    return t


def _recv_exact_line(s):
    buf = b""
    while b"\r\n" not in buf:
        chunk = s.recv(1024)
        if not chunk:
            break
        buf += chunk
    return buf.decode("latin1", errors="replace").split("\r\n")[0]


def send_frame(sock, opcode, payload: bytes):
    mask = os.urandom(4)
    ln = len(payload)
    hdr = bytes([0x80 | opcode])
    if ln < 126:
        hdr += bytes([0x80 | ln])
    elif ln < 65536:
        hdr += bytes([0x80 | 126]) + struct.pack(">H", ln)
    else:
        hdr += bytes([0x80 | 127]) + struct.pack(">Q", ln)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(hdr + mask + masked)


def send_text(sock, text: str):
    send_frame(sock, 0x1, text.encode("utf-8"))


def recv_messages(sock):
    """Yield (kind, payload) where kind in {'text','binary'}."""
    frag_op, frag_buf = None, b""
    while True:
        b0, b1 = _recv_exact(sock, 2)
        fin = b0 & 0x80
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _recv_exact(sock, 8))[0]
        if masked:
            mask = _recv_exact(sock, 4)
        payload = _recv_exact(sock, length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x9:  # ping
            send_frame(sock, 0xA, payload)
            continue
        if opcode == 0x8:  # close
            try:
                send_frame(sock, 0x8, b"")
            except OSError:
                pass
            return
        if opcode == 0x0:  # continuation
            frag_buf += payload
            if fin:
                yield frag_op, frag_buf
                frag_op, frag_buf = None, b""
            continue
        if fin:
            yield ("text" if opcode == 0x1 else "binary"), payload
        else:
            frag_op = "text" if opcode == 0x1 else "binary"
            frag_buf = payload


def synth_beat(idx, text):
    mp3_path = os.path.join(WORK, f"beat{idx}.mp3")
    srt_path = os.path.join(WORK, f"beat{idx}.srt")
    tc = TTSConfig(voice=VOICE, rate="+0%", volume="+0%", pitch="+0Hz",
                 boundary="WordBoundary")
    ssml = mkssml(tc, escape(text))
    request_id = uuid.uuid4().hex

    sock = connect_ws()
    try:
        send_text(sock,
            f"X-Timestamp:{date_to_string()}\r\n"
            "Content-Type:application/json; charset=utf-8\r\n"
            "Path:speech.config\r\n\r\n"
            '{"context":{"synthesis":{"audio":{"metadataoptions":{'
            '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"true"},'
            '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n')
        send_text(sock, ssml_headers_plus_data(request_id, date_to_string(), ssml))

        submaker = SubMaker()
        words = []  # (offset_ticks, duration_ticks, text)
        audio = bytearray()
        for kind, payload in recv_messages(sock):
            if kind == "text":
                params, data = get_headers_and_data(
                    payload, payload.find(b"\r\n\r\n"))
                path = params.get(b"Path")
                if path == b"audio.metadata":
                    for meta in json.loads(data)["Metadata"]:
                        if meta["Type"] == "WordBoundary":
                            d = meta["Data"]
                            w = {"type": "WordBoundary",
                                 "offset": d["Offset"] + 0,
                                 "duration": d["Duration"],
                                 "text": d["text"]["Text"]}
                            submaker.feed(w)
                            words.append((d["Offset"], d["Duration"],
                                          d["text"]["Text"]))
                elif path == b"turn.end":
                    break
            else:  # binary
                if len(payload) < 2:
                    continue
                hlen = int.from_bytes(payload[:2], "big")
                _, data = get_headers_and_data(payload, hlen)
                if data:
                    audio.extend(data)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    with open(mp3_path, "wb") as f:
        f.write(audio)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(submaker.get_srt())
    # also save word timings as JSON for the animation timeline
    with open(os.path.join(WORK, f"beat{idx}.words.json"), "w", encoding="utf-8") as f:
        json.dump([{"t": o / 1e7, "d": d / 1e7, "w": w}
                   for o, d, w in words], f, ensure_ascii=False)
    print(f"beat{idx}: audio={len(audio)}B words={len(words)}", flush=True)
    return len(audio) > 0


def main():
    beats = []
    with open(os.path.join(WORK, "beats.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                tag, text = line.split("|", 1)
                beats.append(text)
    ok = True
    for i, text in enumerate(beats, 1):
        if i > 1:
            time.sleep(5)  # avoid rate limiting
        for attempt in range(3):
            try:
                if synth_beat(i, text):
                    break
            except Exception as e:
                print(f"beat{i} attempt {attempt+1} failed: {type(e).__name__}: {str(e)[:120]}",
                      flush=True)
                time.sleep(3)
        else:
            print(f"beat{i}: FAILED after 3 attempts", flush=True)
            ok = False
    print("ALL DONE" if ok else "SOME FAILED")


if __name__ == "__main__":
    main()
