# Unified Fractal Engine (PoC)

A standalone proof-of-concept for a recursive, seed-deterministic
vector engine where **every depth of the world is a 10×10 grid**
sharing the same movement math.

> Status: experiment / sandbox. Not wired into `brain_server.py`,
> `kind_config.json`, or the live Godot project. Lives entirely
> under `experiments/fractal_engine/`.

## What this demonstrates

1. **Unified topology.** A `GridNode` at depth=0 is a galaxy; at
   depth=3, a dungeon floor. Same dataclass, same movement, same
   recursion rules.
2. **Seed determinism.** Any node is fully reconstructible from its
   parent seed plus its `(x, y)` coordinate via SHA-256-derived
   sub-seeds. Two runs produce byte-identical `DrawLine` streams.
3. **Floating origin.** Geometry is always rendered in *node-local*
   coordinates. A tile at depth=8 (≈1e-8 absolute world units) and
   one at depth=0 produce the same numeric range out of the
   projector — no vertex jitter from huge offsets.
4. **Delta-state ledger.** `WorldState` only stores user-driven
   changes, keyed by `GridNode.ledger_key()` (e.g.
   `G[2,3].S[7,1].O[5,5]`). Re-entering a region replays your
   modifications on top of fresh procedural generation.
5. **Stream output.** The engine emits `DrawLine(a, b, color)` only.
   Consumers (Godot, terminal, debug viewer) decide how to draw.

## Layout

```
experiments/fractal_engine/
├── primitives.py     # Vec2/3, Color, DrawLine, VectorGeometry, Camera
├── grid_node.py      # GridNode + transition_level + seed derivation
├── world_state.py    # Delta + WorldState (JSON-persistable ledger)
├── engine.py         # FractalEngine (move + render)
├── runner.py         # CLI: dump a frame as JSONL
├── tests/            # pytest suites
│   ├── test_scale_invariance.py
│   ├── test_floating_origin.py
│   └── test_seed_determinism.py
├── godot_demo/       # Godot 4 project consuming the line-stream
│   ├── project.godot
│   ├── main.tscn
│   ├── main.gd
│   └── frame.jsonl   # pre-generated sample frame
└── README.md
```

## Running

### Tests

From the repo root:

```bash
python3 -m pytest experiments/fractal_engine/tests/ -v
```

19 tests across three files: scale invariance (6), floating origin
(5), seed determinism + delta ledger (8).

### Generate a frame

```bash
cd experiments/fractal_engine
python3 runner.py --depth 2 --seed 1337 --with-deltas \
    > godot_demo/frame.jsonl
```

Flags:
- `--seed N`: root galaxy seed (default 1337)
- `--depth N`: how many levels to descend (0=galaxy, 3=dungeon)
- `--steps N`: extra zooms past `--depth` into tile (1, 1)
- `--cam-x/-y/-z`: camera position (defaults render the grid nicely)
- `--with-deltas`: seed two demo deltas (one "place", one "remove")

Each output line is a JSON object:

```json
{"a": [0.123, -0.45], "b": [0.231, -0.40], "color": [0.4, 0.9, 1.0, 1.0]}
```

NDC space, `[-1, 1]`. Y is up. The consumer maps that to its viewport.

### Godot demo

Open `godot_demo/project.godot` in Godot 4.x and press play.
`main.gd` reads `frame.jsonl` from the project root and draws each
line. Press **R** to reload the frame after regenerating it.

If you don't have Godot handy, the JSONL stream itself *is* the
demo — pipe it into any 2D drawing context.

## Surprises while building this

- **`parent()` has no inverse.** SHA-256 is one-way, so "zoom out"
  can't recover the same parent seed that produced you. The honest
  fix: zooming out *generates* a fresh parent and treats the
  current node as authoritative for its slot. This matches
  roguelike "leave the dungeon, the surface regenerates" semantics
  and makes the WorldState ledger the actual continuity mechanism,
  not parent-pointer chasing.
- **Floating origin came almost for free.** Once the rule was
  "render in node-local coordinates only", scale-invariance fell
  out of basic dataclass arithmetic. The hard part was *not*
  composing absolute world transforms — every time I caught myself
  reaching for one, the floating-origin test would've failed.
- **The 10×10 substrate is the engine.** Everything else
  (primitive picking, glyph density, delta overlays) is one tier
  of policy on top. If you change `GRID_SIZE` to 7 the whole
  engine still works — but every depth name shifts. The directive's
  "10×10 forever" choice is what locks the visual rhetoric.

## Comparison vs a production vector terminal

There is no `clients/vector_terminal/` in the live repo yet, so
this is a comparison against the *concept* of one rather than
real code:

| Concern | This PoC | A production vector terminal |
| --- | --- | --- |
| Output | Single `DrawLine` stream as JSONL | Batched draw lists, double-buffered, dirty-rect aware |
| Clipping | Trivial reject (both endpoints in frustum or skip) | Liang-Barsky / Cohen-Sutherland against near + screen edges |
| Persistence | One JSON file via `WorldState.save/load` | Append-only event log + periodic snapshot, schema-versioned |
| Determinism | SHA-256 seed derivation, no RNG state | Same, plus a content hash on emitted streams for replay tests |
| Coord system | NDC `[-1, 1]`, y-up | Same NDC, but with explicit `Viewport` abstraction and DPI scale |
| Generation | Per-tile noise threshold (single density knob) | Biome registry + kind_config + scoring/rosters per the live design notes |
| Parent traversal | Generative (re-hashed) | Same, plus optional ancestor cache for "warp back" UX |
| Threading | None | Stream emitted on a worker; consumer reads a ring buffer |
| LOD | Depth-based primitive switch only | Distance-based geometry tiers + dissolve, per the project's `dissolve beats LOD` rule |

The substrate is the same. A production vector terminal would
mostly add I/O ergonomics (batching, threading, persistence
robustness), clipping correctness, and gameplay integration —
none of which are needed to validate the topology.

## Stubs / deferred

- **Liang-Barsky clipping.** Lines straddling the near plane are
  trivially rejected today. A production renderer would clip the
  segment to the near plane and emit the visible portion.
- **`parent()` inverse.** As noted above, generative-parent is the
  intended semantics, but a more sophisticated game might cache
  the chain explicitly to allow "fly back through space".
- **Depth > 3 visuals.** `primitive_for_depth` falls back to
  dungeon walls for any depth ≥ 3. Adding new depth tiers is a
  config-as-code job (just extend the resolver).
- **`godot.md` reference.** The master prompt mentioned this
  artifact — it's not in the live repo. Per the sandbox directive,
  it's intentionally not chased.
