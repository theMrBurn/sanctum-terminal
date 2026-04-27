"""End-to-end integration test for the loop completion track (L1-L8).

Spins up the brain in a subprocess on a non-default port, acts as a fake
Godot client over TCP, and drives the full mini-DRG loop:

  HUB → damage_self → use_request → MISSION_SELECT → IN_MISSION →
  mission_complete_trigger → RESULTS → HUB

At each step the test asserts on:
  - game_state.state
  - player.hp / max_hp / inventory
  - world_revision (bumps on world regen)
  - results payload (trigger_kind, loot)

This is the closest thing to a manual UAT we can run unattended. Replaces
the "press M then ENTER then F then..." sequence with deterministic
assertions. Catches things like the KEY_L conflict that took a manual
trace to spot, plus inventory mutation bugs that would otherwise slip
through unit tests.

Marked slow (~5s end-to-end). Run via:
    PYTHONPATH=. ./.venv/bin/python -m pytest tests/test_loop_integration.py -v -s
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_PORT = 9878  # offset from the default 9877 so we don't fight a live brain


# --- Brain subprocess -------------------------------------------------------

class BrainProcess:
    """Spawns brain_server.py as a subprocess and waits for 'ready'.

    Stdout is consumed in a background thread so the pipe doesn't fill up.
    Lines are kept in self.stdout_lines for post-mortem inspection.
    """

    READY_MARKER = "ready on"
    BOOT_TIMEOUT_S = 15.0

    def __init__(self, biome: str = "outdoor"):
        env = os.environ.copy()
        env["SANCTUM_STAMP"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT)
        self.proc = subprocess.Popen(
            [str(REPO_ROOT / ".venv/bin/python"), "brain_server.py", biome, str(TEST_PORT)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.stdout_lines: list[str] = []
        self._ready = threading.Event()
        self._stdout_thread = threading.Thread(
            target=self._consume_stdout, daemon=True
        )
        self._stdout_thread.start()
        if not self._ready.wait(timeout=self.BOOT_TIMEOUT_S):
            self.stop()
            raise RuntimeError(
                f"brain didn't reach 'ready' in {self.BOOT_TIMEOUT_S}s. "
                f"stdout tail: {self.stdout_lines[-10:]}"
            )

    def _consume_stdout(self) -> None:
        if self.proc.stdout is None:
            return
        for line in self.proc.stdout:
            line = line.rstrip()
            self.stdout_lines.append(line)
            if self.READY_MARKER in line:
                self._ready.set()

    def stop(self) -> None:
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


# --- TCP client (acts as Godot) ---------------------------------------------

class BrainClient:
    """Minimal TCP client that mirrors how Godot talks to the brain.

    Each call to send_camera() or send_cmd() writes a JSON line; recv
    blocks until a full \\n-terminated message arrives. unchanged-only
    manifests are skipped automatically since we want to assert on
    state-bearing payloads.
    """

    def __init__(self, port: int = TEST_PORT, timeout: float = 5.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        # Brain may need a moment after 'ready' before accept() runs.
        for _ in range(20):
            try:
                self.sock.connect(("127.0.0.1", port))
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError(f"could not connect to brain on :{port}")
        self.buf = b""

    def send(self, payload: dict) -> None:
        self.sock.sendall((json.dumps(payload) + "\n").encode())

    def send_camera(self, x: float = 0.0, y: float = -14.0, z: float = 2.5,
                    heading: float = 0.0, pitch: float = 0.0,
                    dt: float = 0.05) -> None:
        self.send({
            "cam_x": x, "cam_y": y, "cam_z": z,
            "heading": heading, "pitch": pitch, "dt": dt,
        })

    def recv_line(self) -> dict:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("brain closed connection")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def recv_full_manifest(self, max_skip: int = 20) -> dict:
        """Drain unchanged-only messages, return the next state-bearing one."""
        for _ in range(max_skip):
            m = self.recv_line()
            if not m.get("unchanged"):
                return m
        raise RuntimeError("no full manifest received in time")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# --- Fixture ----------------------------------------------------------------

@pytest.fixture
def brain():
    b = BrainProcess(biome="outdoor")
    yield b
    b.stop()


# --- The end-to-end loop ----------------------------------------------------

def test_full_loop_end_to_end(brain):
    """One assertion per step in the L1-L8 sequence the UAT keys exercise."""
    client = BrainClient()
    try:
        # ---- Initial state at HUB ----
        client.send_camera()
        m = client.recv_full_manifest()

        assert m["game_state"]["state"] == "HUB", \
            f"expected HUB at boot, got {m['game_state']['state']}"
        p = m["player"]
        assert p["hp"] == p["max_hp"] == 6, \
            f"expected hp=max_hp=6 at boot, got hp={p['hp']} max_hp={p['max_hp']}"
        inv_names = [i["name"] for i in p["inventory"]]
        assert "torch_handcrafted" in inv_names
        assert inv_names.count("healing_potion") == 2, \
            f"expected 2 pre-filled potions, got {inv_names.count('healing_potion')}"
        assert p["equipped"] == "torch_handcrafted", \
            f"expected torch auto-equipped, got {p['equipped']}"
        boot_revision = m["world_revision"]

        # ---- damage_self → hp drops ----
        client.send({"cmd": "damage_self", "amount": 2})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["hp"] == 4, f"expected hp=4 after damage_self(2), got {m['player']['hp']}"

        # ---- use_request → consume potion, hp restored ----
        client.send({"cmd": "use_request"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["hp"] == 6, f"expected hp=6 (heal+3 capped at max), got {m['player']['hp']}"
        inv_names = [i["name"] for i in m["player"]["inventory"]]
        assert inv_names.count("healing_potion") == 1, \
            f"expected 1 potion left after use, got {inv_names.count('healing_potion')}"

        # ---- HUB → MISSION_SELECT (no regen) ----
        client.send({"cmd": "state_transition_request", "target": "MISSION_SELECT"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "MISSION_SELECT"
        assert m["world_revision"] == boot_revision, "MISSION_SELECT should not regen"

        # ---- MISSION_SELECT → IN_MISSION (world regenerates) ----
        client.send({"cmd": "state_transition_request", "target": "IN_MISSION"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "IN_MISSION"
        assert m["game_state"]["mission_id"] is not None
        assert m["game_state"]["mission_seed"] is not None
        assert m["world_revision"] > boot_revision, \
            f"world should regen on launch (was {boot_revision}, got {m['world_revision']})"
        mission_revision = m["world_revision"]

        # ---- mission_complete_trigger → loot drops, RESULTS ----
        client.send({"cmd": "mission_complete_trigger", "trigger_kind": "clay_pot"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "RESULTS"
        results = m["game_state"]["results"]
        assert results["trigger_kind"] == "clay_pot"
        assert "pot_shard" in results["loot"], \
            f"expected guaranteed pot_shard drop, got {results['loot']}"
        # Inventory grew by at least one (the shard); potentially more if
        # the weighted ember/healing_potion rolls hit.
        inv_names = [i["name"] for i in m["player"]["inventory"]]
        assert "pot_shard" in inv_names, \
            f"shard should land in inventory, got {inv_names}"

        # ---- RESULTS → HUB (regen back to hub seed) ----
        client.send({"cmd": "state_transition_request", "target": "HUB"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "HUB"
        assert m["game_state"]["mission_id"] is None, \
            "HUB return should clear mission context"
        assert m["world_revision"] > mission_revision, \
            "world should regen on hub return"
        # Inventory persists across the loop — pot_shard still there.
        inv_names = [i["name"] for i in m["player"]["inventory"]]
        assert "pot_shard" in inv_names, "loot should persist after HUB transition"
    finally:
        client.close()


def test_use_request_with_no_consumables(brain):
    """When inventory has no use_effects items, use_request is a no-op
    (brain logs and continues — no crash, no state corruption)."""
    client = BrainClient()
    try:
        # Drain the pre-filled potions
        client.send({"cmd": "use_request"})
        client.send_camera()
        client.recv_full_manifest()
        client.send({"cmd": "use_request"})
        client.send_camera()
        client.recv_full_manifest()

        # Now no consumables. Use should no-op cleanly.
        prior_hp = 6
        client.send({"cmd": "damage_self", "amount": 1})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["hp"] == 5

        client.send({"cmd": "use_request"})
        client.send_camera()
        m = client.recv_full_manifest()
        # Brain should NOT have attempted to consume torch_handcrafted —
        # torch has no use_effects, so use_request finds nothing.
        assert m["player"]["hp"] == 5, "use should be no-op without consumables"
        inv_names = [i["name"] for i in m["player"]["inventory"]]
        assert "torch_handcrafted" in inv_names, "torch should not have been consumed"
    finally:
        client.close()


def test_illegal_state_transition_rejected_cleanly(brain):
    """HUB → IN_MISSION direct should be rejected without corrupting state."""
    client = BrainClient()
    try:
        client.send_camera()
        client.recv_full_manifest()  # baseline

        # Skip MISSION_SELECT — brain's L1 state machine should reject this.
        client.send({"cmd": "state_transition_request", "target": "IN_MISSION"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "HUB", \
            f"illegal transition should leave state at HUB, got {m['game_state']['state']}"
    finally:
        client.close()
