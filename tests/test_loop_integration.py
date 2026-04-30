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
TEST_PORT_PERSIST = 9879  # second port for the persistence-across-restart test


# --- Brain subprocess -------------------------------------------------------

class BrainProcess:
    """Spawns brain_server.py as a subprocess and waits for 'ready'.

    Stdout is consumed in a background thread so the pipe doesn't fill up.
    Lines are kept in self.stdout_lines for post-mortem inspection.
    """

    READY_MARKER = "ready on"
    BOOT_TIMEOUT_S = 15.0

    def __init__(self, biome: str = "outdoor", port: int = TEST_PORT,
                 save_path: Path | None = None):
        env = os.environ.copy()
        env["SANCTUM_STAMP"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT)
        if save_path is not None:
            env["SANCTUM_SAVE_PATH"] = str(save_path)
        self.proc = subprocess.Popen(
            [str(REPO_ROOT / ".venv/bin/python"), "brain_server.py", biome, str(port)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._port = port
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


def test_equip_holster_wire(brain):
    """The equip/holster TCP path: holster the auto-equipped torch, re-equip."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        # Auto-equipped at boot for UAT.
        assert m["player"]["equipped"] == "torch_handcrafted"

        # Holster.
        client.send({"cmd": "holster_request"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["equipped"] is None, \
            f"expected None after holster, got {m['player']['equipped']}"

        # Re-equip.
        client.send({"cmd": "equip_request", "name": "torch_handcrafted"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["equipped"] == "torch_handcrafted"
    finally:
        client.close()


def test_equip_non_inventory_item_rejected(brain):
    """Equipping something not in inventory must not change equipped state."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        original = m["player"]["equipped"]

        # 'magic_sword' is not in inventory — brain should reject.
        client.send({"cmd": "equip_request", "name": "magic_sword"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["equipped"] == original, \
            f"rejection should leave equipped unchanged (was {original}, got {m['player']['equipped']})"
    finally:
        client.close()


def test_mission_complete_outside_in_mission_ignored(brain):
    """Trigger fired at HUB should silently no-op — no loot, no state change."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "HUB"
        original_inv_size = len(m["player"]["inventory"])

        # Fire trigger from HUB — brain handler gates on IN_MISSION, ignores.
        client.send({"cmd": "mission_complete_trigger", "trigger_kind": "clay_pot"})
        client.send_camera()
        m = client.recv_full_manifest()

        assert m["game_state"]["state"] == "HUB", "state should not transition from HUB"
        assert len(m["player"]["inventory"]) == original_inv_size, \
            "no loot should drop outside IN_MISSION"
    finally:
        client.close()


def test_save_load_persists_across_brain_restart(tmp_path):
    """L5 — autosave on RESULTS → HUB persists; the next brain boot loads
    the saved state. This is the core promise: tomorrow morning your
    inventory is still there.

    Spins two brains back-to-back with a shared SANCTUM_SAVE_PATH:
      brain #1: complete a mission, return to HUB (autosave fires)
      brain #2: should boot loading the saved inventory + completed_missions
    """
    save_path = tmp_path / "test_save.json"
    assert not save_path.exists()

    # ---- Brain #1 ----
    b1 = BrainProcess(biome="outdoor", port=TEST_PORT_PERSIST, save_path=save_path)
    try:
        c1 = BrainClient(port=TEST_PORT_PERSIST)
        try:
            c1.send_camera()
            m = c1.recv_full_manifest()
            initial_inv = len(m["player"]["inventory"])
            assert m["player"]["completed_missions"] == [], \
                "fresh brain should have no completed missions"

            # Run one full cycle
            c1.send({"cmd": "state_transition_request", "target": "MISSION_SELECT"})
            c1.send_camera()
            c1.recv_full_manifest()
            c1.send({"cmd": "state_transition_request", "target": "IN_MISSION"})
            c1.send_camera()
            c1.recv_full_manifest()
            c1.send({"cmd": "mission_complete_trigger", "trigger_kind": "clay_pot"})
            c1.send_camera()
            c1.recv_full_manifest()
            c1.send({"cmd": "state_transition_request", "target": "HUB"})
            c1.send_camera()
            m = c1.recv_full_manifest()

            assert m["game_state"]["state"] == "HUB"
            # Mission should be in completed list
            assert "anomaly_hunt_01" in m["player"]["completed_missions"]
            inv_after_mission = len(m["player"]["inventory"])
            assert inv_after_mission > initial_inv, "loot should have dropped"
        finally:
            c1.close()
    finally:
        b1.stop()

    # ---- Save file should exist now ----
    assert save_path.exists(), "autosave should have written during RESULTS → HUB"
    saved_data = json.loads(save_path.read_text())
    assert saved_data["version"] == 1
    assert "anomaly_hunt_01" in saved_data["player"]["completed_missions"]

    # ---- Brain #2 — fresh boot, same save path ----
    b2 = BrainProcess(biome="outdoor", port=TEST_PORT_PERSIST, save_path=save_path)
    try:
        c2 = BrainClient(port=TEST_PORT_PERSIST)
        try:
            c2.send_camera()
            m = c2.recv_full_manifest()
            # Inventory size should match what was saved (not reset to 3 fixtures)
            assert len(m["player"]["inventory"]) == inv_after_mission, \
                f"loaded inventory should match saved (saved={inv_after_mission}, " \
                f"loaded={len(m['player']['inventory'])})"
            # Completed missions persisted
            assert "anomaly_hunt_01" in m["player"]["completed_missions"]
            # Brain log should mention the load
            log_text = "\n".join(b2.stdout_lines)
            assert "loaded save" in log_text, \
                f"brain #2 should log 'loaded save' — got log:\n{log_text}"
        finally:
            c2.close()
    finally:
        b2.stop()


def test_picker_cycles_and_launch_uses_selection():
    """L6 — picker exposes available_missions, cycle command moves the
    selection with wrap-around, and launch consumes the current selection
    as mission_id. Uses cavern biome which exposes 2 active classes
    (outdoor only has 1, so wrap is observationally a no-op there)."""
    b = BrainProcess(biome="cavern", port=TEST_PORT)
    try:
        client = BrainClient()
        try:
            # Baseline at HUB — no selection until MISSION_SELECT is entered.
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["state"] == "HUB"
            assert m["game_state"]["selected_mission_id"] is None, \
                "no selection should be active outside MISSION_SELECT"
            available = m["game_state"]["available_missions"]
            assert len(available) >= 2, \
                f"cavern binding should expose 2+ missions for picker UAT, got {available}"

            # Open picker — selection initializes to available[0].
            client.send({"cmd": "state_transition_request", "target": "MISSION_SELECT"})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["state"] == "MISSION_SELECT"
            assert m["game_state"]["selected_mission_id"] == available[0], \
                f"first selection should default to {available[0]}, got {m['game_state']['selected_mission_id']}"

            # Cycle forward — moves to available[1].
            client.send({"cmd": "mission_select_cycle", "delta": 1})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["selected_mission_id"] == available[1]

            # Cycle past end — wraps back to available[0].
            client.send({"cmd": "mission_select_cycle", "delta": 1})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["selected_mission_id"] == available[0], \
                f"cycle should wrap, got {m['game_state']['selected_mission_id']}"

            # Cycle backward — wraps to last entry.
            client.send({"cmd": "mission_select_cycle", "delta": -1})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["selected_mission_id"] == available[-1]

            # Launch — brain consumes selected_mission_id, clears it.
            launched = m["game_state"]["selected_mission_id"]
            client.send({"cmd": "state_transition_request", "target": "IN_MISSION"})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["state"] == "IN_MISSION"
            assert m["game_state"]["mission_id"] == launched, \
                f"launched mission_id should match picker selection " \
                f"({launched}), got {m['game_state']['mission_id']}"
            assert m["game_state"]["selected_mission_id"] is None, \
                "selection should clear once mission launches"
        finally:
            client.close()
    finally:
        b.stop()


def test_picker_cycle_rejected_outside_mission_select():
    """Brain only honors mission_select_cycle while in MISSION_SELECT.
    Outside that state the command is a no-op — selected_mission_id stays
    None and game_state isn't mutated."""
    b = BrainProcess(biome="cavern", port=TEST_PORT)
    try:
        client = BrainClient()
        try:
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["state"] == "HUB"
            assert m["game_state"]["selected_mission_id"] is None

            # Cycle from HUB — brain rejects, selection stays None.
            client.send({"cmd": "mission_select_cycle", "delta": 1})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["state"] == "HUB", \
                "rejected cycle should not change state"
            assert m["game_state"]["selected_mission_id"] is None, \
                "selection must stay None outside MISSION_SELECT"
        finally:
            client.close()
    finally:
        b.stop()


def test_repeated_missions_do_not_crash_brain(brain):
    """Run the loop many times — brain should stay responsive, inventory
    should respect slot cap (full inventory triggers ValueError caught
    by the brain handler with 'loot drop skipped: ...' log)."""
    client = BrainClient()
    try:
        # 8 full cycles — enough to fill the 10-slot default inventory
        # (starts with 3 items, each mission drops 1-3, so saturation by ~5-6).
        for cycle in range(8):
            client.send({"cmd": "state_transition_request", "target": "MISSION_SELECT"})
            client.send_camera()
            client.recv_full_manifest()
            client.send({"cmd": "state_transition_request", "target": "IN_MISSION"})
            client.send_camera()
            client.recv_full_manifest()
            client.send({"cmd": "mission_complete_trigger", "trigger_kind": "clay_pot"})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["state"] == "RESULTS", \
                f"cycle {cycle}: expected RESULTS, got {m['game_state']['state']}"
            client.send({"cmd": "state_transition_request", "target": "HUB"})
            client.send_camera()
            m = client.recv_full_manifest()
            assert m["game_state"]["state"] == "HUB", \
                f"cycle {cycle}: expected return to HUB"

        # After 8 cycles brain still alive and answering. Inventory should
        # not exceed slots cap.
        slots_cap = 10  # PlayerState.new() default
        assert len(m["player"]["inventory"]) <= slots_cap, \
            f"inventory exceeded slot cap: {len(m['player']['inventory'])}"
    finally:
        client.close()
