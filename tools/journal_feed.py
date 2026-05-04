"""Hand-feed harness — send a journal entry to the live brain.

Stand-in for the J7 planner UI: opens a TCP connection, sends a
`journal_entry` cmd, prints the ack. Use this to walk through the
J3-min bridge end-to-end:

    python tools/journal_feed.py "Lost my keys at the back door."

The brain logs the entry id + synthesized quest id; the manifest's
`quests` payload reflects the new available quest on the next frame.
Send a second entry mentioning the same head term to complete the
journal_followup predicate:

    python tools/journal_feed.py "Found the keys."

Defaults to localhost:9877 (vector_terminal config). Override with
--host / --port if running the brain elsewhere.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys


def send_entry(host: str, port: int, raw_note: str, timeout: float = 5.0) -> dict:
    payload = json.dumps({"cmd": "journal_entry", "raw_note": raw_note}) + "\n"
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload.encode("utf-8"))
        # Read until newline — single ack frame from the handler.
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    if not buf.strip():
        return {"error": "no ack received"}
    return json.loads(buf.strip())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("raw_note", help="Free-text journal entry (in her voice).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9877)
    args = p.parse_args()

    try:
        ack = send_entry(args.host, args.port, args.raw_note)
    except (ConnectionRefusedError, socket.timeout) as exc:
        print(f"could not reach brain at {args.host}:{args.port} — {exc}",
              file=sys.stderr)
        return 1

    print(json.dumps(ack, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
