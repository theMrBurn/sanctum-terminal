"""
brain_server.py

Live brain server: generates world, streams manifests to Godot via TCP.

Protocol:
    Godot connects to localhost:9877
    Godot sends: JSON line with {"cam_x", "cam_y", "cam_z", "heading", "pitch", "dt"}\n
    Server sends: JSON line with full manifest (entities, fog, ambient)\n

    Manifest only updates when wake set changes or tension state changes.
    Otherwise sends {"unchanged": true}\n to save bandwidth.

Usage:
    PYTHONPATH=. ./.venv/bin/python brain_server.py [outdoor|cavern]
    make brain
"""

import json
import math
import random
import select
import socket
import sys
import time

from core.systems.biome_data import (
    BIOME_REGISTRY,
    OUTDOOR_LIGHT_STATES, CAVERN_LIGHT_STATES,
    HARD_OBJECTS,
)
from core.systems.spatial_wake import SpatialHash, WakeChain, WAKE_CHAINS
from core.systems.world_gen import generate_tile
from core.systems.tension_cycle import TensionCycle, OUTDOOR_CYCLE, CAVERN_CYCLE


# -- Kind properties (same as godot_export.py) --------------------------------

KIND_PROPS = {
    "mega_column":     {"scale": [3.0, 3.0, 12.0], "color": [0.28, 0.22, 0.16], "emissive": 0.0},
    "column":          {"scale": [1.8, 1.8, 8.0],  "color": [0.30, 0.25, 0.18], "emissive": 0.0},
    "boulder":         {"scale": [4.0, 3.5, 2.5],  "color": [0.25, 0.42, 0.16], "emissive": 0.0},
    "stalagmite":      {"scale": [0.8, 0.8, 3.0],  "color": [0.28, 0.24, 0.18], "emissive": 0.0},
    "crystal_cluster": {"scale": [1.5, 1.2, 2.0],  "color": [0.35, 0.29, 0.19], "emissive": 1.0},
    "giant_fungus":    {"scale": [2.0, 2.0, 3.5],  "color": [0.20, 0.36, 0.15], "emissive": 0.8},
    "dead_log":        {"scale": [3.0, 0.8, 0.6],  "color": [0.19, 0.27, 0.12], "emissive": 0.0},
    "moss_patch":      {"scale": [1.5, 1.5, 0.15], "color": [0.14, 0.33, 0.09], "emissive": 0.9},
    "bone_pile":       {"scale": [0.6, 0.6, 0.3],  "color": [0.14, 0.13, 0.11], "emissive": 0.0},
    "grass_tuft":      {"scale": [0.3, 0.3, 0.25], "color": [0.18, 0.33, 0.11], "emissive": 0.0},
    "rubble":          {"scale": [0.8, 0.8, 0.4],  "color": [0.28, 0.24, 0.19], "emissive": 0.0},
    "leaf_pile":       {"scale": [0.5, 0.5, 0.1],  "color": [0.30, 0.23, 0.12], "emissive": 0.0},
    "twig_scatter":    {"scale": [0.6, 0.4, 0.05], "color": [0.25, 0.21, 0.14], "emissive": 0.0},
    "cave_gravel":     {"scale": [0.2, 0.2, 0.05], "color": [0.24, 0.22, 0.16], "emissive": 0.0},
    "firefly":         {"scale": [0.06, 0.06, 0.06],"color": [0.95, 0.75, 0.30], "emissive": 1.0},
    "leaf":            {"scale": [0.08, 0.06, 0.01],"color": [0.22, 0.30, 0.10], "emissive": 0.0},
    "beetle":          {"scale": [0.04, 0.03, 0.02],"color": [0.10, 0.08, 0.06], "emissive": 0.0},
    "rat":             {"scale": [0.12, 0.06, 0.06],"color": [0.14, 0.11, 0.08], "emissive": 0.0},
    "spider":          {"scale": [0.05, 0.05, 0.03],"color": [0.08, 0.07, 0.06], "emissive": 0.0},
    "ceiling_moss":    {"scale": [1.0, 1.0, 0.8],  "color": [0.12, 0.18, 0.08], "emissive": 0.9},
    "hanging_vine":    {"scale": [0.3, 0.3, 2.5],  "color": [0.10, 0.16, 0.07], "emissive": 0.0},
    "filament":        {"scale": [0.05, 0.05, 3.0], "color": [0.30, 0.40, 0.55], "emissive": 1.0},
    "horizon_form":    {"scale": [6.0, 4.0, 10.0], "color": [0.08, 0.10, 0.05], "emissive": 0.0},
    "horizon_mid":     {"scale": [4.0, 3.0, 7.0],  "color": [0.10, 0.12, 0.06], "emissive": 0.0},
    "horizon_near":    {"scale": [3.0, 2.0, 5.0],  "color": [0.12, 0.14, 0.08], "emissive": 0.0},
    "exit_lure":       {"scale": [1.0, 1.0, 2.0],  "color": [0.60, 0.45, 0.20], "emissive": 1.0},
}

COLLISION_RADII = {k: v for k, v in HARD_OBJECTS.items()}


# -- Multi-tile world ---------------------------------------------------------

class BrainWorld:
    """Manages multiple tiles, spatial hash, wake chain, and tension cycle."""

    def __init__(self, biome_name, base_seed=42, tile_size=288.0):
        self.biome_name = biome_name
        self.base_seed = base_seed
        self.tile_size = tile_size

        # Spatial indexing
        chain_key = biome_name if biome_name in WAKE_CHAINS else "outdoor"
        self.wake_chain = WakeChain(WAKE_CHAINS[chain_key])
        self.spatial = SpatialHash(cell_size=20.0)

        # Tension cycle — board immediately for live atmosphere
        cycle_cfg = OUTDOOR_CYCLE if biome_name == "outdoor" else CAVERN_CYCLE
        self.tension = TensionCycle(cycle_cfg)
        self.tension.board()

        # Light states
        self.light_states = OUTDOOR_LIGHT_STATES if biome_name == "outdoor" else CAVERN_LIGHT_STATES
        self.light_state_names = list(self.light_states.keys())
        self.light_state_idx = 1 if biome_name == "outdoor" else 0  # dusk / cave

        # Entity storage
        self.entities = {}       # eid → entity dict (for manifest)
        self.spawns = {}         # eid → (kind, x, y, z, heading, seed)
        self.loaded_tiles = set()
        self.next_eid = 0

        # Generate center tile
        self._generate_tile(0, 0)

    def _tile_key(self, cam_x, cam_y):
        return (int(math.floor(cam_x / self.tile_size)),
                int(math.floor(cam_y / self.tile_size)))

    def _generate_tile(self, tx, ty):
        if (tx, ty) in self.loaded_tiles:
            return
        self.loaded_tiles.add((tx, ty))

        # Deterministic seed per tile
        seed = self.base_seed + tx * 7919 + ty * 6271
        rng = random.Random(seed)

        tile_spawns = generate_tile(
            seed=seed, biome_name=self.biome_name, tile_size=self.tile_size)

        offset_x = tx * self.tile_size
        offset_y = ty * self.tile_size
        half = self.tile_size / 2.0

        for kind, (lx, ly), heading, kseed in tile_spawns:
            props = KIND_PROPS.get(kind)
            if not props:
                continue

            # World-space position (centered tiles)
            x = lx - half + offset_x
            y = ly - half + offset_y
            z = 0.0
            if kind == "leaf":
                z = 3.0
            elif kind == "ceiling_moss":
                z = rng.uniform(5.0, 8.0)
            elif kind == "hanging_vine":
                z = rng.uniform(4.0, 7.0)
            elif kind == "filament":
                z = rng.uniform(1.0, 4.0)
            elif kind == "firefly":
                z = rng.uniform(0.5, 2.5)

            # Per-seed variation
            srng = random.Random(kseed)
            sv = srng.uniform(0.75, 1.25)
            sx, sy_s, sz = props["scale"]
            r, g, b = props["color"]

            # Light hue index — which color from LIGHT_LAYERS this emissive rolls
            light_hue_idx = srng.randint(0, 3)

            ent = {
                "kind": kind,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "heading": round(heading, 1),
                "sv": round(sv, 3),
                "light_hue": light_hue_idx,
                "sx": round(sx * sv, 3),
                "sy": round(sy_s * sv, 3),
                "sz": round(sz * srng.uniform(0.80, 1.20), 3),
                "r": round(r * srng.uniform(0.85, 1.15), 3),
                "g": round(g * srng.uniform(0.85, 1.15), 3),
                "b": round(b * srng.uniform(0.85, 1.15), 3),
                "emissive": props["emissive"],
                "collision_radius": COLLISION_RADII.get(kind, 0.0),
            }

            eid = self.next_eid
            self.next_eid += 1
            self.entities[eid] = ent
            self.spawns[eid] = (kind, x, y, z, heading, kseed)

            chain_idx = self.wake_chain.chain_index(kind)
            self.spatial.insert(eid, x, y, chain_index=chain_idx)

    def ensure_tiles_around(self, cam_x, cam_y, radius=1):
        """Generate tiles in a grid around camera position."""
        ctx, cty = self._tile_key(cam_x, cam_y)
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                self._generate_tile(ctx + dx, cty + dy)

    def get_manifest(self, cam_x, cam_y, cam_z, heading, pitch, dt):
        """Compute visible entities and atmosphere for current camera."""
        # Generate nearby tiles
        self.ensure_tiles_around(cam_x, cam_y, radius=1)

        # Wake set — visible entities by priority
        # Skeleton kinds (mega_column, column) render at extended range
        # so they're always visible as dark silhouettes through fog
        wake_set = self.wake_chain.compute_wake_set(self.spatial, cam_x, cam_y)

        # Add skeleton entities from extended range (2x normal)
        extended = self.spatial.query(cam_x, cam_y, radius=60.0)
        wake_ids = {eid for eid, _ in wake_set}
        for eid, chain_idx in extended:
            if chain_idx == 0 and eid not in wake_ids:  # chain 0 = skeleton
                wake_set.append((eid, chain_idx))
                wake_ids.add(eid)

        # Tension cycle tick
        entity_count = len(wake_set)
        budget_max = self.tension._config.get("budget_max", 800)
        envelope = self.tension.tick(dt, entity_count, budget_max)

        # Current light state (base values)
        ls = self.light_states[self.light_state_names[self.light_state_idx]]

        # Tension envelope overrides fog/ambient when active
        if self.tension.active and envelope:
            fog_near = envelope.fog[0]
            fog_far = envelope.fog[1]
            ambient = list(envelope.ambient)
        else:
            fog_near = ls["fog_near"]
            fog_far = ls["fog_far"]
            ambient = list(ls["ambient"])

        # Build entity list with baked light tints
        EMISSIVE_LIGHT_COLORS = {
            "crystal_cluster": (0.25, 0.30, 0.55),
            "giant_fungus":    (0.15, 0.25, 0.08),
            "moss_patch":      (0.08, 0.30, 0.06),
            "firefly":         (0.50, 0.40, 0.15),
            "filament":        (0.20, 0.30, 0.40),
            "ceiling_moss":    (0.40, 0.28, 0.10),
        }

        visible = []
        emissives = []
        for eid, _ in wake_set:
            ent = self.entities.get(eid)
            if ent:
                visible.append(ent)
                if ent["kind"] in EMISSIVE_LIGHT_COLORS:
                    emissives.append((ent["x"], ent["y"], EMISSIVE_LIGHT_COLORS[ent["kind"]]))

        # Bake light influence: tint non-emissive entities from nearby emissives
        for i in range(len(visible)):
            ent = visible[i]
            if ent.get("emissive", 0) > 0:
                continue
            lr, lg, lb = 0.0, 0.0, 0.0
            ex, ey = ent["x"], ent["y"]
            for lx, ly, (cr, cg, cb) in emissives:
                dx, dy = ex - lx, ey - ly
                dist = (dx*dx + dy*dy) ** 0.5
                if dist < 12.0:
                    influence = (1.0 - dist / 12.0) ** 2 * 0.35
                    lr += cr * influence
                    lg += cg * influence
                    lb += cb * influence
            if lr > 0.001 or lg > 0.001 or lb > 0.001:
                tinted = dict(ent)
                tinted["r"] = round(min(1.0, ent["r"] + lr), 3)
                tinted["g"] = round(min(1.0, ent["g"] + lg), 3)
                tinted["b"] = round(min(1.0, ent["b"] + lb), 3)
                visible[i] = tinted

        return {
            "camera": {"x": cam_x, "y": cam_y, "z": cam_z,
                       "heading": heading, "pitch": pitch},
            "fog": {
                "near": fog_near,
                "far": fog_far,
                "color": list(ls["fog_color"]),
            },
            "ambient": ambient,
            "bg_color": list(ls["bg_color"]),
            "sun": {
                "color": list(ls.get("sun_color", [0, 0, 0])),
                "scale": ls.get("sun_scale", 0.0),
            },
            "moon": {
                "color": list(ls.get("moon_color", [0, 0, 0])),
                "scale": ls.get("moon_scale", 0.0),
            },
            "entities": visible,
            "tension_state": self.tension.state,
            "tension_budget": round(self.tension.budget, 3),
            "stats": {
                "visible": len(visible),
                "total": len(self.entities),
                "tiles": len(self.loaded_tiles),
            },
        }

    def cycle_light_state(self):
        """Advance to next light state (L key)."""
        self.light_state_idx = (self.light_state_idx + 1) % len(self.light_state_names)
        name = self.light_state_names[self.light_state_idx]
        print(f"  Light state: {name}", flush=True)
        return name


# -- TCP server ---------------------------------------------------------------

def run_server(biome_name, port=9877):
    world = BrainWorld(biome_name)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    sock.setblocking(False)

    stats = world.get_manifest(0, 0, 2.5, 0, 0, 0)["stats"]
    print(f"Brain server ready on :{port} | {biome_name} | "
          f"{stats['total']} entities, {stats['tiles']} tiles", flush=True)
    print("Waiting for Godot to connect...", flush=True)

    client = None
    buf = b""
    last_wake_ids = set()

    try:
        while True:
            # Accept new connections
            if client is None:
                try:
                    client, addr = sock.accept()
                    client.setblocking(False)
                    buf = b""
                    last_wake_ids = set()
                    print(f"  Godot connected from {addr}", flush=True)
                except BlockingIOError:
                    time.sleep(0.016)
                    continue

            # Read from client
            try:
                data = client.recv(8192)
                if not data:
                    print("  Godot disconnected", flush=True)
                    client.close()
                    client = None
                    continue
                buf += data
            except BlockingIOError:
                pass
            except (ConnectionResetError, BrokenPipeError):
                print("  Godot disconnected (reset)", flush=True)
                client.close()
                client = None
                continue

            # Process complete lines
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Handle commands
                if msg.get("cmd") == "light_cycle":
                    name = world.cycle_light_state()
                    # Force full update
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "tension_toggle":
                    if hasattr(world.tension, 'toggle'):
                        world.tension.toggle()
                    continue

                # Camera update → manifest
                cam_x = msg.get("cam_x", 0.0)
                cam_y = msg.get("cam_y", 0.0)
                cam_z = msg.get("cam_z", 2.5)
                heading = msg.get("heading", 0.0)
                pitch = msg.get("pitch", 0.0)
                dt = msg.get("dt", 0.016)

                manifest = world.get_manifest(
                    cam_x, cam_y, cam_z, heading, pitch, dt)

                # Check if wake set changed (by entity count + position hash)
                wake_ids = frozenset(
                    (e.get("kind",""), round(e.get("x",0),1), round(e.get("y",0),1))
                    for e in manifest["entities"])
                if wake_ids == last_wake_ids:
                    response = json.dumps({"unchanged": True}) + "\n"
                else:
                    last_wake_ids = wake_ids
                    response = json.dumps(manifest) + "\n"

                try:
                    client.sendall(response.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError):
                    print("  Godot disconnected (write)", flush=True)
                    client.close()
                    client = None
                    break

    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
    finally:
        if client:
            client.close()
        sock.close()


def main():
    biome_name = sys.argv[1] if len(sys.argv) > 1 else "outdoor"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9877
    run_server(biome_name, port)


if __name__ == "__main__":
    main()
