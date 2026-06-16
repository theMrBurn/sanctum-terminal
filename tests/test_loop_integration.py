"""End-to-end integration tests for the post-PR-5 game loop.

Spins up the brain in a subprocess on a non-default port, acts as a
fake vector terminal client over TCP, and exercises the surviving
loop surface:

  - boot at HUB with inventory + character sheet
  - damage_self / use_request mutate HP / inventory
  - illegal state transition rejected
  - kind_destroyed cmd (the PR 6 successor to mission_complete_trigger)
    publishes a tick event for async quests, no state change
  - equip/holster wire
  - save persistence across restart

The pre-PR-5 5-state mission loop (HUB → MISSION_SELECT → IN_MISSION →
RESULTS → HUB) and its picker / loot-drop / autosave-on-RESULTS path
were collapsed. Free exploration replaces "in a mission instance";
async quests handle progression. Reflective mode is the new natural
beat boundary (HUB ↔ REFLECTIVE) and where autosave fires now.

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


# --- TCP client (acts as vector terminal) -----------------------------------

class BrainClient:
    """Minimal TCP client that mirrors how vector_terminal talks to the
    brain. Each call to send_camera() or send() writes a JSON line; recv
    blocks until a full \\n-terminated message arrives. unchanged-only
    manifests are skipped automatically."""

    def __init__(self, port: int = TEST_PORT, timeout: float = 5.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
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


# --- Surviving loop surface -------------------------------------------------


def test_brain_boots_to_hub_with_inventory(brain):
    """Initial state at HUB; player has inventory and an equipped item.
    Save-content-agnostic — exact item counts depend on the user's live
    save and aren't part of the contract this test pins."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()

        assert m["game_state"]["state"] == "HUB", \
            f"expected HUB at boot, got {m['game_state']['state']}"
        # Post PR 6 the manifest's game_state is just `{state: ...}` —
        # mission ghost fields were dropped.
        assert "mission_id" not in m["game_state"]
        assert "mission_seed" not in m["game_state"]
        assert "results" not in m["game_state"]

        p = m["player"]
        assert p["hp"] > 0, f"player should boot with HP > 0, got {p['hp']}"
        assert p["hp"] <= p["max_hp"]
        assert len(p["inventory"]) > 0, "inventory should be non-empty post-creation"
    finally:
        client.close()


def test_damage_then_use_restores_hp(brain):
    """damage_self / use_request mutate HP and inventory. Foundation for
    the HP=0 → REFLECTIVE forced path. Asserts on RELATIVE deltas, not
    specific HP values, so save state changes don't break the test."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        hp_start = m["player"]["hp"]
        max_hp = m["player"]["max_hp"]
        potions_start = sum(
            1 for i in m["player"]["inventory"]
            if i["name"] == "healing_potion"
        )
        if potions_start == 0:
            pytest.skip("save has no healing_potion to exercise use_request")

        client.send({"cmd": "damage_self", "amount": 2})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["hp"] == hp_start - 2, \
            f"damage_self(2) should drop hp by 2: {hp_start} → {m['player']['hp']}"

        client.send({"cmd": "use_request"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["hp"] > hp_start - 2, \
            f"use_request with potion should restore some HP, got {m['player']['hp']}"
        assert m["player"]["hp"] <= max_hp, "heal capped at max_hp"
        potions_after = sum(
            1 for i in m["player"]["inventory"]
            if i["name"] == "healing_potion"
        )
        assert potions_after == potions_start - 1, \
            f"one potion consumed: {potions_start} → {potions_after}"
    finally:
        client.close()


def test_illegal_state_transition_rejected_cleanly(brain):
    """Post PR 5: REFLECTIVE → CHARACTER_CREATION is not allowed
    (only REFLECTIVE → HUB). Brain rejects without corrupting state."""
    client = BrainClient()
    try:
        # Walk into REFLECTIVE first.
        client.send({"cmd": "engage_fridge"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "REFLECTIVE"

        # Try the illegal jump.
        client.send({"cmd": "state_transition_request", "target": "CHARACTER_CREATION"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "REFLECTIVE", \
            f"illegal transition should leave state at REFLECTIVE, " \
            f"got {m['game_state']['state']}"
    finally:
        client.close()


def test_kind_destroyed_publishes_event_no_state_change(brain):
    """PR 6: `kind_destroyed` (successor to legacy `mission_complete_trigger`)
    publishes a tick event for async quests but doesn't change state or
    roll loot. State stays HUB; inventory unchanged."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "HUB"
        inv_before = [i["name"] for i in m["player"]["inventory"]]

        client.send({"cmd": "kind_destroyed", "kind": "clay_pot"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "HUB"
        inv_after = [i["name"] for i in m["player"]["inventory"]]
        assert inv_after == inv_before, \
            f"inventory shouldn't grow on kind_destroyed event; " \
            f"before={inv_before} after={inv_after}"
    finally:
        client.close()


def _safe_int_id(ent: dict) -> int:
    """Some entities ship string ids (e.g. roaming orbs use `orb#N`).
    For smash-target / set-membership purposes we only care about
    numerically-keyed entities (the procedural pool). Returns -1 for
    non-int ids so they sort safely without colliding with real ids."""
    raw = ent.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def test_smash_with_entity_id_removes_entity_from_manifest(brain):
    """First inline ARPG combat verb. Mouse-left-on-pot in vector terminal
    sends `kind_destroyed` with an entity_id; brain adds id to
    destroyed_entity_ids ledger; subsequent manifests filter the entity
    out so the smashed pot disappears. Ledger clears on world regen."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        # Pick any entity id from the current manifest as a smash target.
        # We use a procedural entity (positive id) — hub fixtures have
        # negative ids and shouldn't be smashable in this test.
        candidates = [e for e in m["entities"] if _safe_int_id(e) >= 0]
        if not candidates:
            pytest.skip("no procedural entities to smash")
        target = candidates[0]
        target_id = int(target["id"])
        target_kind = str(target["kind"])

        client.send({
            "cmd": "kind_destroyed",
            "kind": target_kind,
            "entity_id": target_id,
            "x": target["x"],
            "y": target["y"],
        })
        # Wait a moment for the brain to process the command and update the ledger.
        time.sleep(0.1)
        client.send_camera()
        m = client.recv_full_manifest()

        ids_after = {_safe_int_id(e) for e in m["entities"]}
        assert target_id not in ids_after, \
            f"smashed entity id={target_id} should be filtered out of " \
            f"the manifest; still present in {sorted(ids_after)[:10]}..."


    finally:
        client.close()


def test_cast_event_accepted_for_each_element(brain):
    """KEYS 1-4 send cast_event with element fire/ice/electric/light. Brain
    validates trajectory + element via verbs.json and queues for the next
    manifest's reaction resolution. Verifies the wire — that brain
    accepts each of the 4 V1 elements without rejection."""
    client = BrainClient()
    try:
        client.send_camera()
        client.recv_full_manifest()

        for i, element in enumerate(("fire", "ice", "electric", "light"), start=1):
            client.send({
                "cmd": "cast_event",
                "cast": {
                    "tag_id": -i,
                    "element": element,
                    "trajectory": "straight",
                    "origin": [0.0, 0.0, 1.7],
                    "direction": [0.0, 1.0, 0.0],
                },
            })
            client.send_camera()
            m = client.recv_full_manifest()
            # Cast doesn't change game_state or HP — it's an event push.
            assert m["game_state"]["state"] == "HUB"
    finally:
        client.close()


def test_smash_without_entity_id_keeps_world_intact(brain):
    """`kind_destroyed` with no entity_id (e.g. quest-only event push)
    publishes the event but doesn't drop anything from the world."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        ids_before = {_safe_int_id(e) for e in m["entities"]}

        client.send({"cmd": "kind_destroyed", "kind": "clay_pot"})
        client.send_camera()
        m = client.recv_full_manifest()
        ids_after = {_safe_int_id(e) for e in m["entities"]}
        # Same entities; nothing dropped without an explicit entity_id.
        assert ids_before == ids_after
    finally:
        client.close()


def test_engage_fridge_enters_reflective(brain):
    """Voluntary REFLECTIVE entry — F-on-fridge (or `engage_fridge` cmd)
    transitions HUB → REFLECTIVE. Survives PR 5."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "HUB"

        client.send({"cmd": "engage_fridge"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["game_state"]["state"] == "REFLECTIVE", \
            f"engage_fridge should enter REFLECTIVE, got {m['game_state']['state']}"

        # Reflective overlay block populated.
        reflective = m.get("reflective", {})
        assert reflective.get("active") is True
    finally:
        client.close()


def test_equip_holster_wire(brain):
    """Equip / holster TCP commands mutate player.equipped without
    state transitions. Picks an inventory item to equip rather than
    assuming any specific one is auto-equipped."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        inv_names = [i["name"] for i in m["player"]["inventory"]]
        if not inv_names:
            pytest.skip("save has empty inventory; nothing to equip-cycle")
        target = inv_names[0]

        client.send({"cmd": "holster_request"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["equipped"] is None, \
            f"holster should clear equipped, got {m['player']['equipped']}"

        client.send({"cmd": "equip_request", "name": target})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["equipped"] == target, \
            f"equip_request should set equipped={target}, got {m['player']['equipped']}"
    finally:
        client.close()


def test_use_request_with_no_consumables(brain):
    """When inventory has no use_effects items, use_request is a no-op
    (brain logs and continues — no crash, no state corruption).
    Drains every potion regardless of count, then verifies HP doesn't
    move on a final use_request."""
    client = BrainClient()
    try:
        client.send_camera()
        m = client.recv_full_manifest()
        potions = sum(
            1 for i in m["player"]["inventory"]
            if i["name"] == "healing_potion"
        )
        for _ in range(potions):
            client.send({"cmd": "use_request"})
            client.send_camera()
            client.recv_full_manifest()

        client.send({"cmd": "damage_self", "amount": 1})
        client.send_camera()
        m = client.recv_full_manifest()
        hp_post_damage = m["player"]["hp"]

        client.send({"cmd": "use_request"})
        client.send_camera()
        m = client.recv_full_manifest()
        assert m["player"]["hp"] == hp_post_damage, \
            f"use should be no-op without consumables ({hp_post_damage} → {m['player']['hp']})"
    finally:
        client.close()


def test_save_persistence_across_restart(tmp_path):
    """Boot brain → mutate inventory → reflective commit → bounce →
    second brain reads same save path → state persisted. Save now fires
    on reflective commit (PR 5 collapse) instead of RESULTS → HUB.

    Pre-populates the test save_path with the live save so brain boots
    straight to HUB with a finalized character sheet (otherwise it
    spawns at CHARACTER_CREATION and the test would have to walk the
    7-pillar ritual programmatically)."""
    import shutil
    save_path = tmp_path / "test_save.json"
    live_save = REPO_ROOT / "save" / "player.json"
    if not live_save.exists():
        pytest.skip("no live save to seed the persistence test")
    shutil.copy(live_save, save_path)

    # ---- Brain #1 — fresh boot, autosave, then bounce ----
    b1 = BrainProcess(biome="outdoor", port=TEST_PORT_PERSIST, save_path=save_path)
    inv_after_use = 0
    try:
        c1 = BrainClient(port=TEST_PORT_PERSIST)
        try:
            # Mutate inventory: consume a potion so the saved state
            # diverges from defaults in a way we can check on reload.
            c1.send({"cmd": "damage_self", "amount": 2})
            c1.send_camera()
            c1.recv_full_manifest()
            c1.send({"cmd": "use_request"})
            c1.send_camera()
            m = c1.recv_full_manifest()
            inv_after_use = len(m["player"]["inventory"])

            # Engage fridge → commit (V1 dummy commit through the
            # rule). The reflective_commit handler triggers the
            # autosave on success.
            c1.send({"cmd": "engage_fridge"})
            c1.send_camera()
            m = c1.recv_full_manifest()
            assert m["game_state"]["state"] == "REFLECTIVE"

            # Place enough magnets to pass `compose_three`. Magnet is a
            # name STRING from the brain-side pool, not a dict — we pull
            # the pool from the manifest's reflective block.
            pool = m.get("reflective", {}).get("magnet_pool", [])
            assert pool, f"no magnet_pool in reflective manifest: {m.get('reflective')}"
            for i in range(3):
                c1.send({"cmd": "place_magnet", "magnet": pool[0]})
                c1.send_camera()
                c1.recv_full_manifest()

            c1.send({"cmd": "commit_reflective"})
            # Drain manifests until we're back at HUB (commit →
            # exit_reflective → HUB transition + autosave). Re-send
            # camera each tick so the brain emits a fresh manifest.
            settled = False
            for _ in range(10):
                c1.send_camera()
                m = c1.recv_full_manifest()
                if m["game_state"]["state"] == "HUB":
                    settled = True
                    break
            assert settled, \
                "commit_reflective chain didn't return to HUB within 10 ticks"
        finally:
            c1.close()
    finally:
        b1.stop()

    # Save file written?
    assert save_path.exists(), \
        f"autosave should have written {save_path} on reflective commit. " \
        f"brain log tail: {b1.stdout_lines[-15:]}"
    saved = json.loads(save_path.read_text())
    assert saved["version"] >= 1
    saved_inv = saved["player"]["inventory"]
    assert len(saved_inv) == inv_after_use, \
        f"saved inventory should match in-process state " \
        f"(in-process={inv_after_use}, saved={len(saved_inv)})"

    # ---- Brain #2 — fresh boot, same save path ----
    b2 = BrainProcess(biome="outdoor", port=TEST_PORT_PERSIST, save_path=save_path)
    try:
        c2 = BrainClient(port=TEST_PORT_PERSIST)
        try:
            c2.send_camera()
            m = c2.recv_full_manifest()
            assert len(m["player"]["inventory"]) == inv_after_use, \
                f"loaded inventory should match saved " \
                f"(saved={inv_after_use}, loaded={len(m['player']['inventory'])})"
            log_text = "\n".join(b2.stdout_lines)
            assert "loaded save" in log_text, \
                f"brain #2 should log 'loaded save' — got log:\n{log_text}"
        finally:
            c2.close()
    finally:
        b2.stop()
