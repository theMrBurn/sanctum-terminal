# SANCTUM TERMINAL — Mathematical Foundation

## The Three Bases

```
Base-7   = what things ARE       (atomic, indivisible, prime)
Base-60  = how things CONNECT    (composite, maximally divisible)
Base-1   = the act of creation   (provenance hash, unique, immutable)
```

### Base-7: The Atom Layer

7 is prime. It cannot be decomposed. Every atomic unit in the engine is 7.

| System | Count | Elements |
|--------|-------|----------|
| Primitives | 7 | BLOCK, SLAB, PILLAR, PLANE, WEDGE, SPIKE, ARCH |
| Encounter verbs | 7 | THINK, ACT, MOVE, DEFEND, TOOLS, CRAFT, OBSERVE |
| Scenario types | 7 | fetch, escort, hunt, key, switch, defend, trade |
| Encounter space | 7² = 49 | verb × scenario combinations |
| Valid combinations | ~35 | filtered by archetype logic |
| Concept tiers | 7 | variable → assignment → expression → condition → loop → function → module |

7 is the alphabet. You cannot break A into smaller letters.

### Base-60: The Relationship Layer

60 is the smallest highly composite number. It has 12 divisors —
more than any number below it. It divides equally among groups of
1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30.

The Sumerians chose base-60 for the same reason this engine does:
**maximum equitable distribution**. The most ways to share something fairly.

| System | Count | What it connects |
|--------|-------|-----------------|
| Encounter cooldown | 60 seconds | Time between meaningful moments |
| Ability space | 20 dims × 3 slots = 60 | Fingerprint → concrete abilities |
| Relationship vector | 60 dimensions | The player's true name (see below) |
| Session divisibility | 60 minutes | Any session length divides cleanly |

The 60-dimensional player signature:

```
49 verb×scenario affinities    (7 × 7 — how much this player gravitates
                                to each encounter combination)
 7 verb transition weights     (what they do AFTER each verb — sequences)
 4 register affinities         (which visual world they gravitate toward)
───
60 total dimensions            (the true name)
```

Each dimension: 0.0 - 1.0. Computed from behavior. Never configured.
Updated every blend refresh. Read by the procedural generator.

60 is the language. How letters combine into words.

### Base-1: The Naming Layer

To name something is to create it. The Sumerians believed this.
The provenance hash is the name.

```
SHA256(seed + type + params + timestamp) → 16-character hex
Created once. Immutable. Unique across all playthroughs.
The hash IS the identity IS the proof of creation.
```

Every scenario, every crafted object, every relic, every player creation
gets a provenance hash. The Yellow Sign. Made once, recorded permanently,
traceable across seeds.

When the player crafts `stripped_branch + sap_vessel → Field Torch`,
the Field Torch's provenance hash is its name. No two Field Torches
in any playthrough have the same name. The act of combining IS naming.

"You didn't name it. It named itself."

---

## The Sumerian Parallel

Cuneiform was simultaneously:
- A writing system (symbols represent words)
- A number system (symbols represent quantities)
- A naming system (to write something is to create it)

The compound blueprint is simultaneously:
- A geometry definition (grammar[] = the shape)
- A behavioral tag set (tags[] = the fingerprint bridge)
- A provenance identity (hash = the name)

```
Cuneiform tablet          Sanctum compound blueprint
─────────────────         ──────────────────────────
Symbol = word             Primitive = shape
Symbol = number           Tag = dimension
Inscription = creation    Hash = provenance
Clay = medium             JSON = medium
Stylus = tool             Engine = tool
```

The medium is the message. The JSON IS the game.

---

## The Mask and The Name

From the mythic substrate (King in Yellow):

```
Pallid Mask  = ghost profile (what the world sees)
True Name    = 60-dimensional signature (what the world knows)
Yellow Sign  = provenance hash (proof of creation)
The King     = AtmosphereEngine at maximum entropy
Carcosa      = Memory Horizon (visible, never reachable)
```

The ghost profile is the mask. 10 weighted profiles that determine
how the world presents itself to the player. The player might see
their dominant profile in how encounters feel, but never the weights.

Behind the mask: the true name. 60 dimensions computed from every
action, every choice, every moment of silence. The world reads it.
The player feels the response. The name is never spoken.

The provenance hash is the proof. Every creation carries it.
When you share a crafted object via QR code, the hash travels with it.
The recipient knows it was made. Not by whom. By what convergence of
behavior, time, and choice.

---

## Where Each Base Lives in Code

### Base-7 (atoms)

```
core/systems/geometry.py          -- 7 primitive types
core/systems/encounter_engine.py  -- 7 verbs, VERBS set
core/systems/scenario_engine.py   -- 7 scenario types, SCENARIO_TYPES set
config/blueprints/compounds.json  -- objects built from 7 primitives
```

### Base-60 (relationships)

```
core/systems/avatar_pipeline.py   -- design_key() → expands to 60 dims (future)
core/systems/encounter_engine.py  -- ENCOUNTER_COOLDOWN = 60 seconds
core/systems/fingerprint_engine.py -- 20 dims × 3 ability slots = 60
```

### Base-1 (naming)

```
core/systems/scenario_engine.py   -- _hash() → provenance on every scenario
core/systems/crafting_engine.py   -- provenance_hash on every craft result
core/systems/primitive_factory.py -- _make_hash() on every primitive
```

---

## The Recursive Insight

The player who reaches Phase 3 and learns to mod the game
is engaging in the same act as the Sumerians pressing cuneiform
into clay. They are:

1. Using **7 atomic symbols** (primitives) to compose objects
2. Those objects enter a **60-dimensional relationship space**
3. Each creation receives a **provenance hash** (a name)

They are writing. They are counting. They are naming.
The game taught them to do what humans have done for 5,000 years.
They just didn't know it was the same thing.

---

_This document is the mathematical foundation._
_Base-7 is the what. Base-60 is the how. Base-1 is the why._
_The engine reflects the oldest system humans ever built._
