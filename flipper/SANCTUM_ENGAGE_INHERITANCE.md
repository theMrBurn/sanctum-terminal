# Sanctum-engage → Flipper RPG: inheritance map

What the desktop's canonical world model is, and how the Flipper RPG
(the *mobile version of the full sanctum experience*) inherits it
rather than forking a parallel design. Surveyed 2026-05-28 against the
**live** sanctum-engage pipeline (Panda3D-era legacy excluded).

The rule (from `MEMORY.md → project_sanctum_rpg_flipper`): simplify the
*expression*, never the *model*. Where the Flipper can't do something
the desktop does, it should be a graceful subset, not a different thing.

---

## Ground-truth sources (treat as canonical)

| File | What it owns |
|---|---|
| `config/kind_config.json` | Every object "kind" + its **`ascii` glyph**, class, combat profile, pickup flags |
| `core/systems/biome_data.py` (`BIOME_REGISTRY`) | The 3 live biomes + their properties |
| `core/systems/character_classes.py` | 6 classes, 6-stat block, starting abilities |
| `core/systems/quests/rewards.py` | The `{name, weight}` loot-roll shape |
| `core/systems/stamp_world.py` | Pure `(seed, x, y) → entities` world gen |

**Legacy — do NOT inherit:** `entity_template.py` (Panda3D), the
4 visual registers survival/tron/tolkien/sanrio (Panda3D material
tints, not in any live config), `cavern.py`. If a source imports
`direct.showbase.ShowBase` or `panda3d.*`, it's legacy.

> Correction to my own earlier assumption: I'd planned to map the
> Flipper biomes to the "4 visual registers." Those are legacy. The
> live biome set is **cavern / outdoor / workroom**. Adjusted.

---

## 1. Tile vocabulary — inherit the `ascii` field verbatim

**The big win.** Every kind in `kind_config.json` carries an `ascii`
glyph. The Flipper should draw from this exact set so desktop and
mobile render the same world in the same characters.

Canonical glyphs the Flipper RPG should adopt:

| Glyph | Kind | Class | Flipper role |
|---|---|---|---|
| `.` | cave_gravel | geological | floor (already used ✓) |
| `,` | rubble | geological | floor variant |
| `#` | mega_column / wood_crate | structural | wall (already used ✓) |
| `\|` | column | structural | wall variant |
| `o` | boulder | geological | obstacle |
| `^` | stalagmite | geological | obstacle |
| `n` | doorframe | structural | **walk-through door** (already use `+`; should migrate to `n`) |
| `*` | crystal_cluster | crystalline | **pickup** (already used ✓ — and it's canonically pickupable!) |
| `$` | exit_lure | crystalline | exit marker |
| `u` | clay_pot | life | destructible container (pickupable) |
| `T` | treasure_chest / torch | life/encounter | container / light (pickupable) |
| `r` `R` | rat / rat_ice/fire | life | creature (combat_profile) |
| `b` | beetle | life | creature |
| `s` | spider | life | creature |
| `B` | bat | life | creature (flight) |
| `S` | slime | life | creature |
| `&` | giant_fungus | organic_flora | flora |
| `O` | orb | encounter | roaming encounter agent |

Player `@` is a Flipper-RPG addition (no PC glyph in kind_config since
the desktop is 3D-billboard for the player).

**Action for v0.3.3:** replace the Flipper's ad-hoc item `*` placeholder
with a small typed-kind table drawn from these. Keep `+`→`n` door
migration as a low-priority cosmetic.

## 2. Object classes — 9 canonical, map to a 4-bit enum

`geological, structural, crystalline, organic_flora, atmosphere, life,
horizon, encounter, debug`.

For the Flipper, the meaningful distinctions are:
- **walkable-vs-wall** (structural/geological big ones = wall)
- **pickupable** (`crystal_cluster`, `clay_pot`, `treasure_chest`,
  `torch_handcrafted`, `wood_crate`, `healing_potion`)
- **creature** (anything in `life` class with a `combat_profile`)
- **decor** (everything else — flora, atmosphere, horizon)

Store `class` as 4-bit; derive behavior from class + the pickup/combat
flags rather than per-kind special-casing (mirrors AGENTS.md's
"never `if biome ==`" / "never `if kind ==`" discipline).

## 3. Loot — `{name, weight}` rolls, NO global rarity

There is no rarity enum in kind_config. Loot is per-context reward
tables: `roll([{name, weight}, ...])` where weight ∈ 0..1 is drop
probability (`core/systems/quests/rewards.py`).

**Flipper mirror:** a small static loot table per (biome, depth) of
`{kind_glyph, weight}` entries. Reuse the exact roll semantics. Items
are FINITE (delta layer already enforces "picked up = gone"), so a
chunk's loot is rolled once at generation and never refreshes.
This is the v0.3.3 + v0.3.4 (biome) work.

## 4. Biomes — 3 live, Flipper uses 2

| Biome | has_ceiling | sun | Flipper use |
|---|---|---|---|
| `cavern` | yes | no | dungeon-style chunks (default) |
| `outdoor` | no | yes | surface chunks |
| `workroom` | no | no | authoring sandbox — **skip on mobile** |

Each biome carries a `density` table — `(kind, density_per_1000sqm,
clearance_radius, margin)` — which is exactly a spawn-weight table by
another name. The Flipper's per-biome generation should read a
simplified version: which kinds appear, at what frequency.

**Flipper mirror (v0.3.4):** biome as 2-bit enum on each chunk, derived
from `(seed, chunk_x, chunk_y)`. Biome picks the kind-density table that
feeds procgen. cavern → walls/crystals/fungi; outdoor → flora/grass/logs.

## 5. Classes — 6 canonical, 3 PC-playable

PC: `rogue`, `monk`, `philosopher`. Each: 6 stats (DEX/WIS/INT/CHA/STR/CON,
all fit uint8), 4 starting abilities. NPC archetypes (`watcher`, `scout`,
`scholar`) have TBD abilities.

7 world-verbs: `OBSERVE MEDITATE MARK PARLEY KINDLE REMEMBER INSCRIBE`;
players start with 4 (`OBSERVE MARK PARLEY REMEMBER`), earn 3.

**Flipper mirror (deferred, ~v0.4):** class as 3-bit enum, 6-stat block,
verbs as a 7-bit mask. New Game would pick a PC class. Not in the
current slice plan until combat/abilities exist to differentiate them.

## 6. World generation — `stamp_world` pattern

Desktop: pure `(seed, x, y) → entities`, honeycomb node grid, stamps
(authored multi-object compositions), 7-shell render horizon (7×7m
bands to 49m). Scenario types: `fetch escort hunt key switch defend
trade journal`. Quest archetypes: `survival mystic garden souls
learning`. Ghost-profile fingerprint biases world emphasis.

**Flipper already mirrors the core idea** — our `world_generate_chunk`
is a pure `(seed, cx, cy) → tiles` function, same determinism contract.
The desktop's "stamp" concept = our future hand-authored room templates
the generator can stamp in. The 7-shell horizon maps to: render the
16×6 chunk = "near shells"; off-chunk = blank (we already do this via
chunk boundaries).

**Flipper mirror (later):** introduce "stamps" (authored mini-layouts
the generator places) once procgen variety matters. Scenario types +
quest archetypes are the Phase 5+ quest layer.

---

## Revised slice plan (was v0.3.3+, now grounded in the model)

| Slice | Was | Now (model-grounded) |
|---|---|---|
| v0.3.3 | "item types" | Typed kinds from `kind_config.json` glyphs: pickupables + a `kind` enum + per-kind flags. Loot table uses `{glyph, weight}` roll. |
| v0.3.4 | "biomes" | cavern/outdoor biome per chunk from seed; biome picks the kind-density table feeding procgen |
| v0.3.5 | "inventory" | Carried kinds list, shown on an Inventory screen; kinds from the canonical set |
| v0.3.6 | "level scaling" | depth (chunk distance from origin) shifts loot-table weights toward rarer/stronger kinds |
| v0.4.x | classes + verbs + combat | the `combat_profile` creatures become real; 7-verb system; PC class pick |

The model is richer than the Flipper will ever fully express — but
every Flipper system now has a canonical parent to inherit from, so
desktop↔mobile stay coherent and Phase-4 sync stays meaningful.
