"""Phase 4 migration: inject behavior block into kind_config for the 7
creatures in main.gd CREATURE_KINDS. Idempotent.

Behavior fields:
  speed, flee_radius, destructible, scatter_speed, scatter_gravity,
  mote_arrangement, mote_color (RGB tuple), mote_size

Source: hardcoded literal lifted from main.gd:1572 — these are the values
the orb pipeline has been using all session.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "kind_config.json"


CREATURE_BEHAVIOR = {
    "rat": {"speed": 4.0, "flee_radius": 8.0, "destructible": False,
            "mote_arrangement": "rat_15", "mote_color": [0.55, 0.42, 0.30], "mote_size": 0.15},
    "rat_ice": {"speed": 3.0, "flee_radius": 10.0, "destructible": False,
                "mote_arrangement": "rat_15", "mote_color": [0.45, 0.55, 0.75], "mote_size": 0.15},
    "rat_fire": {"speed": 5.0, "flee_radius": 6.0, "destructible": False,
                 "mote_arrangement": "rat_15", "mote_color": [0.75, 0.35, 0.12], "mote_size": 0.15},
    "treasure_chest": {"speed": 0.0, "flee_radius": 0.0, "destructible": False,
                       "mote_arrangement": "chest_8", "mote_color": [0.50, 0.35, 0.18], "mote_size": 0.20},
    "clay_pot": {"speed": 0.0, "flee_radius": 0.0, "destructible": True,
                 "scatter_speed": 3.0, "scatter_gravity": 6.0,
                 "mote_arrangement": "pot_10", "mote_color": [0.60, 0.42, 0.25], "mote_size": 0.15},
    "beetle": {"speed": 2.0, "flee_radius": 5.0, "destructible": False,
               "mote_arrangement": "solo", "mote_color": [0.08, 0.06, 0.05], "mote_size": 0.03},
    "spider": {"speed": 3.0, "flee_radius": 6.0, "destructible": False,
               "mote_arrangement": "solo", "mote_color": [0.06, 0.05, 0.04], "mote_size": 0.04},
}


def main() -> None:
    with CONFIG_PATH.open() as f:
        cfg = json.load(f)

    kinds = cfg["kinds"]
    added = 0
    skipped = 0
    for name, behavior in CREATURE_BEHAVIOR.items():
        if name not in kinds:
            print(f"  WARN: {name} not in kind_config — skipping")
            continue
        kind = kinds[name]
        if "behavior" in kind:
            skipped += 1
            continue
        kind["behavior"] = behavior
        added += 1
        print(f"  + {name}: behavior block added")

    with CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    print(f"\nDone. Added: {added}  Already present: {skipped}")


if __name__ == "__main__":
    main()
