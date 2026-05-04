"""Phase 2 migration: inject physics.collision_radius into kind_config.json
from the HARD_OBJECTS dict. Idempotent — running twice is safe.

Run once: PYTHONPATH=. ./.venv/bin/python tools/migrate_kind_config_phase2.py
Then delete this file (one-shot script).
"""
from __future__ import annotations

import json
from pathlib import Path

from core.systems.biome_data import HARD_OBJECTS

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "kind_config.json"


def main() -> None:
    with CONFIG_PATH.open() as f:
        cfg = json.load(f)

    kinds = cfg["kinds"]
    added = 0
    skipped = 0
    for kind_name, radius in HARD_OBJECTS.items():
        if kind_name not in kinds:
            print(f"  WARN: {kind_name} in HARD_OBJECTS but not kind_config — skipping")
            continue
        kind = kinds[kind_name]
        physics = kind.setdefault("physics", {})
        if "collision_radius" in physics:
            skipped += 1
            continue
        physics["collision_radius"] = radius
        added += 1
        print(f"  + {kind_name}: collision_radius = {radius}")

    with CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")  # trailing newline for POSIX

    print(f"\nDone. Added: {added}  Already present: {skipped}")


if __name__ == "__main__":
    main()
