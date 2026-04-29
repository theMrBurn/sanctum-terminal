"""TCP client for the brain manifest stream.

Mirrors the wire protocol Godot uses (godot/main.gd:2186-2306):
non-blocking TCP socket, line-buffered JSON, bidirectional. No
registration handshake — connect, then start sending camera updates.
"""
from __future__ import annotations

import json
import socket
from typing import Any, Iterable


class ManifestClient:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._buf = b""

    def connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=2.0)
        sock.setblocking(False)
        self._sock = sock
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def send(self, msg: dict[str, Any]) -> None:
        if self._sock is None:
            return
        line = (json.dumps(msg) + "\n").encode("utf-8")
        try:
            self._sock.sendall(line)
        except (BlockingIOError, BrokenPipeError, OSError):
            pass

    def poll(self) -> list[dict[str, Any]]:
        """Drain any complete JSON lines available right now."""
        if self._sock is None:
            return []
        try:
            while True:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                self._buf += chunk
        except BlockingIOError:
            pass
        except OSError:
            return []
        return list(parse_lines(self._buf_drain()))

    def _buf_drain(self) -> bytes:
        if b"\n" not in self._buf:
            return b""
        head, sep, tail = self._buf.rpartition(b"\n")
        full = head + sep
        self._buf = tail
        return full


def parse_lines(blob: bytes) -> Iterable[dict[str, Any]]:
    """Yield decoded JSON objects from a buffer of newline-delimited records.

    Tolerates trailing partial lines (caller is expected to retain them).
    Skips empty lines and JSON decode errors silently — the brain may emit
    keepalives or partial chunks during socket pressure.
    """
    for raw in blob.split(b"\n"):
        if not raw.strip():
            continue
        try:
            yield json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
