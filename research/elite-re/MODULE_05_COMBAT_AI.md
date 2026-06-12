# Module 05 — Combat AI + Flight Model

The hardest module. The pirate AI's intercept-and-attack state machine,
the police AI's enforcement logic, the docking computer's beautiful
"approach and align" sub-routine, the missile lock, the ship physics.
Lots of state machines, lots of trig approximations on a 6502 with no
multiply instruction.

Estimated time: **5–10 evenings.**

---

## Goal

Implement, in your own code:

```c
typedef enum {
    AI_IDLE,
    AI_APPROACH,
    AI_ENGAGE,
    AI_FLEE,
    AI_MISSILE_LOCK,
    AI_DOCKING_APPROACH,
    AI_DOCKING_ALIGN,
    AI_DOCKING_FINAL
} ai_state_t;

typedef struct {
    ai_state_t state;
    uint8_t    aggression;        // 0..7, per-pirate
    uint8_t    laser_temp;
    uint8_t    missiles_remaining;
    ship_t    *target;
} npc_t;

void npc_tick(npc_t *npc, ship_t *self, world_t *world);
```

That, when fed a realistic combat scenario, behaves recognisably like
Elite's pirates — wide approach, swooping engage, retreat when
damaged, occasional missile launch at high-aggression individuals.

**Verification:** record a 60-second combat encounter in BeebEm
against a known pirate; record the same in your simulator with the
same initial conditions; behaviours should be qualitatively
indistinguishable (same approach pattern, similar engage cadence,
similar flee threshold).

---

## What you'll discover

- The AI is **state-machine driven** with a single per-tick update
- "Approach" uses a simple proportional-navigation heuristic — point
  at where the target *will be*, accelerate
- "Engage" is concentric-arc fire patterns; the AI doesn't try to
  perfectly aim, it sweeps the player's expected position
- "Flee" triggers on `hull < threshold` AND `aggression < 5`; high-
  aggression NPCs never flee
- Missiles have **target-following logic** distinct from ship AI —
  it's a different, simpler state machine
- Docking computer (when you buy one) is its own AI that takes over
  the player's ship; reuses the docking-approach states above
- Trig approximation: there's a 256-entry sin/cos table; no actual
  multiplication; angle calculations use lookup + 8-bit shifts

---

## Suggested approach

### Step 1 — find the AI dispatch

Break on the per-tick game loop (it's the one that runs at 4 Hz).
Within it, find the per-NPC update call. Step through one NPC's
update; that's `npc_tick`.

### Step 2 — enumerate the states

Watch the same NPC over a minute of gameplay. Each state should
become visible in its behavior: long straight-line approach, swooping
engagement, sudden retreat. Map the observed behaviours back to
discrete state values stored on the NPC.

### Step 3 — the approach math

For "Approach", trace the per-frame velocity / heading updates. The
algorithm should be:
- Compute relative position (target_pos - self_pos) → desired heading
- Adjust current orientation toward desired (limited rotation rate)
- Accelerate forward

This is much simpler than full proportional navigation; Elite
approximates.

### Step 4 — the engage pattern

This is the iconic Elite combat: a swooping arc around the player.
The AI doesn't track precisely; it overshoots and re-targets in a
loop. Trace the heading and laser-fire decisions over several engage
cycles to recover the pattern.

### Step 5 — fire timing

When does the AI fire? Probably:
- `dot(forward, vector_to_target) > threshold` (target in front cone)
- `laser_temp < cap` (don't fry the laser)
- `frame_count % cadence == 0` (rate-limit fire)

Recover the threshold, cap, and cadence values.

### Step 6 — flee logic

What's the hull threshold? What's the aggression threshold? How does
"Flee" select a destination (just heads away from the engager;
attempts hyperspace eventually)?

### Step 7 — missile follow

If a missile is in flight, it's a separate per-tick update with its
own state. Find the missile-update routine. It's simpler than NPC AI
— roughly proportional navigation toward the locked target.

### Step 8 — reimplement

Build out `npc_tick()` with the recovered state machine. Run it in a
toy world (no rendering needed; just text output of "ship X at (x,y,z),
state=ENGAGE, fired=true").

### Step 9 — verify

Side-by-side BBC vs your-sim run against a fixed scenario. Behaviours
should match in shape, if not exact frame-by-frame trajectories.

---

## Your notes

### State table

```
State            Entry condition         Behavior                    Exit condition
-----            ---------------         --------                    --------------
IDLE             spawn                   drift                       player in range
APPROACH         player in range         head toward player          range < engage_dist
ENGAGE           range < engage_dist     sweep + fire                hull < flee_thresh OR ...
FLEE             hull < flee_thresh      head away                   hull > recover_thresh
...
```

### Fire decision tree

(transcribed: under what conditions does laser fire? Missile launch?)

### Sin / cos table location

(byte offset of the 256-entry table)

---

## Verification log

Run a 60-second engagement in BeebEm against a known pirate at known
initial conditions. Record:

- State sequence (e.g., APPROACH → ENGAGE → ENGAGE → FLEE)
- Approximate fire count over the engagement
- Approximate hits taken

Run your sim with the same scenario. Compare.

---

## When stuck

- Combat AI is *organic* — it doesn't fail loudly when your
  reimplementation is wrong, it just doesn't *feel* like Elite. Trust
  your sense of "this pirate is behaving wrong" over abstract test
  matchups.
- Stash interesting state observations in `findings/combat_log.md`;
  the patterns become clear after enough hours.
- Moxon's combat annotations are by far his deepest. After 2 weeks
  on this alone, peeking at his state-machine diagram is fair use.

---

## Onward — beyond the modules

You've now reverse-engineered every major subsystem of Elite. The
takeaways for sanctum:

- The procgen patterns from Modules 01–02 are the blueprint for
  `sanctum-engage`'s and the Flipper RPG's world generation
- The wireframe pipeline from Module 03 is the renderer for the
  eventual "Sanctum Elite" — it sits directly behind any space-fi
  sanctum content
- The trade economy from Module 04 is the structural template for
  any sanctum market simulation
- The combat AI from Module 05 is a model for any NPC-driven
  sanctum content where the AI has to *feel* alive without LLM
  involvement (per the inherited no-LLM rule)

Write up a closing post in `MILESTONES.md`. Then start thinking
about the next spec — the one that uses all of this without copying
any of it.
