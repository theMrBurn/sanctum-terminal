# Conformance Reference — spec 53 §9-A

Ground-truth golden vectors for the determinism substrate.
The Python engine (`core/systems/world_gen.py`) must reproduce every field
in `golden_vectors.json` byte-for-field-for-field before Phase A is closed.

---

## Files

| file | purpose |
|---|---|
| `gen_golden.c` | C harness — includes the real substrate, emits `golden_vectors.json` |
| `golden_vectors.json` | The reference; test files load this |
| `README.md` | This document |

The harness **includes the real source** at `../../flipper/sanctum_rpg/rng.{c,h}` and
`pool.{c,h}`. It never copies or reimplements them. Do not move either file without
updating the relative include paths in `gen_golden.c`.

---

## Build and run

```sh
# From tests/conformance/
cc -std=c11 -Wall -Wextra -Werror \
   -I../../flipper/sanctum_rpg \
   ../../flipper/sanctum_rpg/rng.c \
   ../../flipper/sanctum_rpg/pool.c \
   gen_golden.c -o gen_golden
./gen_golden > golden_vectors.json
```

`gen_golden` is a build artifact — do not commit it. `golden_vectors.json` IS
committed and is the source of truth.

**Re-run and re-commit `golden_vectors.json` whenever `rng.c` or `pool.c`
change.** If the file and the binary disagree, the binary wins — regenerate.
Never hand-edit `golden_vectors.json`.

---

## What the vectors cover

### `rng` section

**`sequences`** — 6 seeds × 20 calls to `rng_next`. Includes:
- seed 0 (promoted to 1 — `state_after_seed` must equal seed=1's value)
- seed 1 (minimum nonzero)
- `0xFFFFFFFF` (maximum)
- `state_after_seed` before any `rng_next` call, to verify promotion behavior

**`range_cases`** — 9 cases covering:
- span 1 (no rejection possible)
- small spans (typical gameplay values)
- degenerate cases: `hi == lo` returns `lo`; `hi < lo` returns `lo`
- `seed=0xAAAAAAAA, span=0xC0000000` — VERIFIED rejection fires (2 calls to
  `rng_next`). `state_after` pins stream position; any rejection-count
  divergence is caught here.
- Large-span cross-checks with different seeds/offsets

**`chunk_seed_cases`** — 8 cases covering all four coordinate quadrants,
zero base, and maximum values.

### `pool` section

**`at_prime`** — 6 `(prime_seed, biome)` pairs; the initial `pool_at_prime`
state for each. `last_drop_slot` must be 255 (`0xFF`) for every prime.

**`at_xy`** — same 6 pairs walked to `(chunk_x, chunk_y)` via the canonical
X-first-then-Y path. Includes negative X, negative Y, and both-negative to
cover all four walk directions.

**`step_sequences`** — one seed/biome pair stepped 5 times through the
direction sequence [EAST, SOUTH, WEST, NORTH, EAST]. The pool state after
**each individual step** is emitted so the Python port can verify transitions,
not just end state.

---

## Algorithm spec

### xorshift32 (`rng_next`)

```
state ^= state << 13    (mod 2^32)
state ^= state >> 17
state ^= state << 5     (mod 2^32)
return state
```

**Python gotcha:** Python integers are unbounded. EVERY shift-left and
every multiply MUST be masked with `& 0xFFFFFFFF`:

```python
def rng_next(state):
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= (state >> 17)
    state ^= (state <<  5) & 0xFFFFFFFF
    return state
```

Seed 0 is promoted to 1 before the first `rng_next` call. Never pass 0 to
`rng_seed` — the generator collapses on an all-zero state.

### `rng_range(r, lo, hi)` — rejection-sampled uniform

```
if hi <= lo: return lo
span = hi - lo
reject = (uint32_t)(-span) % span     # == (2^32) % span in C
do: x = rng_next(r) while x < reject
return lo + (x % span)
```

**Critical Python gotcha:** `(-span) % span` in Python is **0** for any
positive `span` (Python signed modulo). This silently disables rejection,
producing biased output AND a stream desync (fewer `rng_next` calls consumed).
Correct Python translation:

```python
reject = (0x100000000 - span) % span   # (2^32 - span) % span
```

`state_after` in the vector file pins the exact number of `rng_next` calls
consumed by the rejection loop. If your Python state diverges after
`rng_range`, check this first.

### `rng_chunk_seed(base, chunk_x, chunk_y)`

```
s = base
s ^= (uint32_t)chunk_x * 0x9E3779B1   (mod 2^32)
s ^= (uint32_t)chunk_y * 0x85EBCA77   (mod 2^32)
# fmix pass (NOT standard MurmurHash3 — see warning below):
s ^= s >> 16;  s *= 0x7FEB352D        (mod 2^32)
s ^= s >> 15;  s *= 0x846CA68B        (mod 2^32)
s ^= s >> 16
return s != 0 ? s : 1
```

**Transcription warning:** the comment in `rng.c` says "fmix32 from
MurmurHash3" but the constants differ from the canonical MurmurHash3 fmix32
(`0x85EBCA6B` / `0xC2B2AE35`, shifts 16/13/16). The constants here are
`0x7FEB352D` / `0x846CA68B` with shifts 16/15/16. Transcribe verbatim from
the source — do NOT substitute upstream MurmurHash3.

**Lookalike hazard:** `rng_chunk_seed` uses `0x846CA68B` in its fmix step;
`pool.c`'s `fnv1a_seed` avalanche uses `0x85EBCA6B`. One hex digit apart.

**Negative coords:** `chunk_x` and `chunk_y` are C `int` cast to `uint32_t`
before the multiply. Negative values wrap via two's-complement:

```python
s ^= (chunk_x & 0xFFFFFFFF) * 0x9E3779B1 & 0xFFFFFFFF
s ^= (chunk_y & 0xFFFFFFFF) * 0x85EBCA77 & 0xFFFFFFFF
```

Include all four coordinate quadrants in tests (the vector file does).

### FNV-1a 32-bit (`pool.c` internal)

Offset basis: `0x811C9DC5`. Prime: `16777619` (`0x01000193`).

`fnv1a_mix(h, v)` feeds each byte of `v` **low byte first**:
```
h ^= (v & 0xFF);        h *= 16777619
h ^= ((v>>8) & 0xFF);  h *= 16777619
h ^= ((v>>16) & 0xFF); h *= 16777619
h ^= ((v>>24) & 0xFF); h *= 16777619
```

`fnv1a_seed(a, b, c)` starts from the offset basis, mixes `a`, `b`, `c`
in order, then runs an avalanche pass: `h ^= h>>16; h *= 0x85EBCA6B; h ^= h>>13`.

### `pool_at_prime(prime_seed, biome, out)`

Sets the initial Pool state. Key points for the Python port:
- `last_drop_slot = 0xFF` always at prime (spec 50 addendum §F1.A.4)
- `intensity = 0`, `rotation_bias = 0`
- Theme weights: `fnv1a_seed(prime_seed, biome, 0xA00 | t) % 16` for t in 0..15
- Primitive bag: IDs from biome vocabulary; weights = `4 + (fnv1a_seed(prime_seed, biome, 0xB00 | slot) % 12)`, range [4..15]; slots beyond vocabulary filled with `id=0xFF, weight=0`
- Family bias: `fnv1a_seed(prime_seed, biome, 0xC00 | f) % 8` for f in 0..4
- Loot kind bias: `fnv1a_seed(prime_seed, biome, 0xD00 | k) % 6` for k in 0..6
- `pedigree = fnv1a_seed(prime_seed, biome, 0)`

### `pool_step(p, prime_seed, dir)`

Execution order (Python must match exactly):
1. `pedigree = fnv1a_mix(fnv1a_mix(pedigree, dir), prime_seed)`
2. `intensity = min(intensity + 1, 255)`  (saturating)
3. `rotation_bias = (rotation_bias + dir + 1) & 3`
4. Theme drift: 4 rounds, each `h = fnv1a_mix(pedigree, 0xE00 | n)`;
   `slot = h & 0x0F`; `delta = +1 if (h>>8)&1 else -1`; clamp [0..15]
5. Family drift: `h = fnv1a_mix(pedigree, 0xF1F1)`; `slot = h % 5`; `delta = +1 if (h>>16)&1 else -1`; clamp [0..15]
6. Loot drift: `h = fnv1a_mix(pedigree, 0xF2F2)`; `slot = h % 7`; `delta = +1 if (h>>16)&1 else -1`; clamp [0..15]
7. Bag rotation:
   - **Drop**: rotor-ordered scan (`rotor = (pedigree >> 24) & 7`); skip
     `id==0xFF`, `weight<=BAG_WEIGHT_FLOOR`, `slot==last_drop_slot`;
     pick lowest-weight (tiebreak: rotor order, not index); `weight--`;
     `last_drop_slot = slot`
   - **Bump**: `h = fnv1a_mix(pedigree, 0xF3F3)`; `bump = h % 8`; walk
     forward until `id != 0xFF && slot != drop`; if `weight < 15`: `weight++`

**Note:** `family_bias` and `loot_kind_bias` are **seeded** in 0..7 / 0..5
ranges but **drift-clamp** to [0..15]. The clamp, not the seed range, is the
runtime invariant.

### Pool struct layout (field-wise contract)

`sizeof(Pool) == 48` (the header comment "42 bytes packed" is WRONG — the
compiler inserts 3 bytes of padding after `rotation_bias` before `pedigree`,
and 3 bytes after `last_drop_slot`). Do NOT raw-memcpy Pool across languages.
Use the field-wise layout in `golden_vectors.json`:

| field | C type | logical range | JSON key |
|---|---|---|---|
| theme_weights[0..15] | 4-bit × 16 in uint8_t[8] | 0..15 each | `"theme_weights": [16 ints]` |
| primitive_bag[0..7][id, weight] | uint8_t[8][2] | id 0..5 or 0xFF; weight 0..15 | `"primitive_bag": [[id,w], ...]` |
| family_bias[0..4] | uint8_t[5] | 0..15 | `"family_bias": [5 ints]` |
| loot_kind_bias[0..6] | uint8_t[7] | 0..15 | `"loot_kind_bias": [7 ints]` |
| intensity | uint8_t | 0..255 | `"intensity"` |
| rotation_bias | uint8_t | 0..3 | `"rotation_bias"` |
| pedigree | uint32_t | full range | `"pedigree"` (unsigned decimal) |
| last_drop_slot | uint8_t | 0..7 or 0xFF | `"last_drop_slot"` |

**Nibble packing detail (C storage only, not the contract):** even theme
index `t` → low nibble of `theme_weights[t/2]` (`& 0x0F`); odd → high
nibble (`>> 4`). Use `pool_theme_weight()` accessor in C. In Python, read
the unpacked `theme_weights` array from the JSON directly.

### `pool_at(prime_seed, biome, chunk_x, chunk_y)` walk order

X-first, then Y. Positive X = EAST steps; negative X = WEST steps.
Positive Y = SOUTH steps; negative Y = NORTH steps. Same `(args)` → same
Pool, byte-field-identical.

Direction encoding: EAST=0, WEST=1, SOUTH=2, NORTH=3.

---

## Acceptance criteria (spec 53 §9-A)

- [ ] Python `rng_next` produces `sequences[*].next_N` exactly
- [ ] Python `rng_range` produces `range_cases[*].result` AND
      `state_after` exactly (the latter catches rejection-count divergence)
- [ ] Rejection fires for `seed=0xAAAAAAAA, span=0xC0000000` (2 `rng_next` calls)
- [ ] Python `rng_chunk_seed` produces `chunk_seed_cases[*].result` exactly
      including all four coordinate quadrants
- [ ] Python `pool_at_prime` produces `at_prime[*].pool` field-for-field
- [ ] Python `pool_at` produces `at_xy[*].pool` field-for-field
- [ ] Python `pool_step` (sequential) matches `step_sequences[0].steps[*].pool`
      after each step
- [ ] Conformance test fails on any single-field divergence

---

## Regenerating after substrate changes

Any change to `rng.c`, `rng.h`, `pool.c`, or `pool.h` that affects
generation output MUST:
1. Rebuild and re-run `gen_golden`
2. Commit the updated `golden_vectors.json` alongside the substrate change
3. Note the deliberate change in the commit message (same discipline as the
   chunk golden-master fingerprints in `flipper/sanctum_rpg/test/test_main.c`)
