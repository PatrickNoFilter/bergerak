#!/usr/bin/env python3
"""Generate per-beat Indonesian TTS with word-level SRT via edge-tts,
through the egress proxy with the Hatch CA bundle."""
import asyncio, os, ssl, sys
import aiohttp
from edge_tts import Communicate, SubMaker
import edge_tts.communicate as _comm

CA = "/run/hatch/egress-tls/ca-bundle.pem"
VOICE = "id-ID-ArdiNeural"
WORK = os.path.dirname(os.path.abspath(__file__))

# edge-tts hardcodes its own SSL ctx (certifi bundle) in ws_connect;
# patch it to also trust the egress proxy's CA.
_comm._SSL_CTX = ssl.create_default_context(cafile=CA)

# The egress proxy rewrites the 101 response's "Connection: upgrade" header
# to "Connection: close", which trips aiohttp's strict handshake validation.
# Patch _ws_connect to accept 101 when "Upgrade: websocket" is present
# (Sec-WebSocket-Accept key validation still runs).
def _patch_ws_handshake():
    import inspect
    import textwrap
    import aiohttp.client as _client
    src = textwrap.dedent(inspect.getsource(_client.ClientSession._ws_connect))
    old = '''        if resp.headers.get(hdrs.CONNECTION, "").lower() != "upgrade":
            raise WSServerHandshakeError(
                resp.request_info,
                resp.history,
                message="Invalid connection header",
                status=resp.status,
                headers=resp.headers,
            )'''
    new = '''        # patched: accept 101 with Upgrade: websocket even if the
        # egress proxy rewrote the Connection header
        pass'''
    assert old in src, "ws handshake patch target not found"
    src = src.replace(old, new)
    ns = dict(_client.__dict__)
    exec(compile(src, "<ws_handshake_patch>", "exec"), ns)
    _client.ClientSession._ws_connect = ns["_ws_connect"]

_patch_ws_handshake()

def parse_srt_time(t):
    # "00:00:01.2340000" -> seconds float
    h, m, rest = t.split(":")
    s = rest.replace(",", ".")
    return int(h) * 3600 + int(m) * 60 + float(s)

async def synth(idx, text):
    mp3 = os.path.join(WORK, f"beat{idx}.mp3")
    srt = os.path.join(WORK, f"beat{idx}.srt")
    ctx = ssl.create_default_context(cafile=CA)
    connector = aiohttp.TCPConnector(ssl=ctx)
    comm = Communicate(
        text, VOICE, boundary="WordBoundary",
        proxy=os.environ.get("HTTPS_PROXY"), connector=connector,
    )
    submaker = SubMaker()
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.create_sub(
                    (chunk["offset"], chunk["duration"]), chunk["text"]
                )
    with open(srt, "w", encoding="utf-8") as f:
        f.write(submaker.generate_subs())
    print(f"beat{idx}: mp3={os.path.getsize(mp3)}B srt={os.path.getsize(srt)}B", flush=True)

async def main():
    beats = []
    with open(os.path.join(WORK, "beats.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                tag, text = line.split("|", 1)
                beats.append((tag, text))
    for i, (tag, text) in enumerate(beats, 1):
        await synth(i, text)
    print("ALL DONE")

if __name__ == "__main__":
    asyncio.run(main())
