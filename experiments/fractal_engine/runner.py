"""Tiny CLI: dump a DrawLine stream as JSONL for any consumer.

Each line: {"a": [x, y], "b": [x, y], "color": [r, g, b, a]}

Usage:
    python runner.py --depth 2 --seed 1337 > frame.jsonl

The Godot demo (godot_demo/main.gd) reads frame.jsonl and draws line
segments. A terminal consumer could just as easily render to ANSI.
That's the point of streaming primitives: zero rendering policy in
the engine.
"""

from __future__ import annotations

import argparse
import json
import sys

from engine import FractalEngine
from grid_node import GridNode
from primitives import Camera, Vec3
from world_state import Delta, WorldState


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--depth", type=int, default=2,
                        help="0=galaxy, 1=solar, 2=overworld, 3=dungeon")
    parser.add_argument("--steps", type=int, default=0,
                        help="zoom 'in' N times into the same tile (1, 1)")
    parser.add_argument("--cam-x", type=float, default=0.0)
    parser.add_argument("--cam-y", type=float, default=0.65)
    parser.add_argument("--cam-z", type=float, default=1.4)
    parser.add_argument("--with-deltas", action="store_true",
                        help="seed a few demo deltas to show ledger overlay")
    args = parser.parse_args()

    node = GridNode(seed=args.seed, depth=0)
    for _ in range(args.depth):
        node = node.child(1, 1)
    for _ in range(args.steps):
        node = node.child(1, 1)

    engine = FractalEngine(state=WorldState())
    if args.with_deltas:
        engine.state.record(node, Delta(kind="place", tile=(2, 3)))
        engine.state.record(node, Delta(kind="remove", tile=(7, 5)))

    cam = Camera(position=Vec3(args.cam_x, args.cam_y, args.cam_z))

    for line in engine.render(node, cam):
        sys.stdout.write(json.dumps({
            "a": [line.a.x, line.a.y],
            "b": [line.b.x, line.b.y],
            "color": [line.color.r, line.color.g, line.color.b, line.color.a],
        }) + "\n")


if __name__ == "__main__":
    main()
