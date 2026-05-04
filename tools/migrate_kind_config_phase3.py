"""Phase 3 migration: inject render.scale/color/emissive into kind_config
from bucket_world.KIND_PROPS (the live source — brain_server.py duplicate
is dead in STAMP_MODE). Idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.systems.bucket_world import KIND_PROPS

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "kind_config.json"


def main() -> None:
    with CONFIG_PATH.open() as f:
        cfg = json.load(f)

    kinds = cfg["kinds"]
    added = 0
    skipped = 0
    missing_kinds = []
    for kind_name, props in KIND_PROPS.items():
        if kind_name not in kinds:
            missing_kinds.append(kind_name)
            continue
        kind = kinds[kind_name]
        render = kind.setdefault("render", {})
        if "scale" in render and "color" in render and "emissive" in render:
            skipped += 1
            continue
        render["scale"] = list(props["scale"])
        render["color"] = list(props["color"])
        render["emissive"] = float(props["emissive"])
        added += 1
        print(f"  + {kind_name}: scale={render['scale']} color={render['color']} emissive={render['emissive']}")

    with CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    print(f"\nDone. Added: {added}  Already present: {skipped}")
    if missing_kinds:
        print(f"  WARN: kinds in KIND_PROPS but not kind_config: {missing_kinds}")


if __name__ == "__main__":
    main()
