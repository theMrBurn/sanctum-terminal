# Feature — feat/make-brain-ping-pong

**Status:** Spec locked 2026-05-04 (refined post-research same day).
Implementation pending.
**Branch:** `feat/make-brain-ping-pong` is the source of truth.
All commits + pushes land on this branch. **Do NOT merge to main**
until UAT signs off on the full feature (Acceptance signature, §end).
**Physics target:** arcade representation, not tennis sim. Vanilla ships
infinite-rally / predictable-bounce / decisive-hit defaults. Realistic
tennis values (drag, Magnus, gravity, COR) live in a `tennis_sim`
preset that inherits from vanilla — for dial-up tuning, not V1 feel.

## Premise

A clean-room cube chamber in the vector terminal where the user can
volley a ball against a wall (and later an invisible NPC, and later
play with mass/velocity/envelope dials), as a high-fidelity
**physics + interaction core**. The engagement doubles as the
**substrate definition** for future "make-brain" instances —
self-contained physics/interaction sub-engines that plug into the
broader Sanctum Terminal ecosystem (archery, ranged ballistics, future
puzzle/mini-game modules).

V1 is **Stage 1 only — solo wall rally with vanilla physics + tennis
scoring + keyboard-console-driven profile snapshots.** Stages 2 (NPC
opponent), 3 (motion envelopes / dynamic dial playground), and the
combat translation (block/parry/time-dilation/coup-de-grace) are spec'd
to ensure V1 substrates don't foreclose them, but ship in later passes.

The load-bearing claim being tested: **tennis volley math = combat
volley math.** A ContactProfile that records intercept-vector +
incoming-state + outgoing-state generalizes from "ball off paddle" to
"weapon arc on target." V1 produces the substrate; V2+ proves the
mapping.

## References we'll rehearse

External material to study before / during PR 4 (ballistics) and PR 5
(strike). Surfaced via 2026-05-04 research pass.

### Implementations to clone or read
- **Spin Doctor** — `sonic.net/~goddard/home/spin/docs/spin.html`. Python+C++ paddle/ball sim. Paddle vel + angle in, ball state out. *Closest match to our ContactProfile shape; rehearse first.*
- **`learning_table_tennis_from_scratch`** (Max Planck) — `github.com/intelligent-soft-robots/learning_table_tennis_from_scratch`. MuJoCo-tuned 3D ball aerodynamics. Mine for physics coefficients in `tennis_sim` preset; skip the RL pipeline.

### Tech docs / talks (required reading where flagged)
- **Erin Catto, *Continuous Collision*, GDC 2013** — `box2d.org/files/ErinCatto_ContinuousCollision_GDC2013.pdf`. **Required before PR 4.** Canonical for our swept-sphere CCD against walls + paddle plane.
- **Catto, *Numerical Methods*, GDC 2015** — pairs with the above. Integrator choice + substep guidance.
- **Mehta et al., *Review of Tennis Ball Aerodynamics*, Sports Technology 2008** — wind-tunnel review. Source of the `tennis_sim` coefficient values (drag 0.55, magnus 0.075–0.275 across spin parameter).
- **Iwata Asks: Wii Sports** — `iwataasks.nintendo.com/interviews/wii/wii_sports/0/0/`. Design validation: swing arc → shot type without buttons. Same thesis as our paddle-intercept-as-attack hypothesis.

### Numbers locked from research

| Param | Vanilla (arcade) | tennis_sim | Source |
|---|---|---|---|
| `ball_drag_coeff` | 0.0 | 0.55 (range 0.5–0.75) | Mehta wind-tunnel |
| `ball_magnus_coeff` | 0.0 | 0.075–0.275 | Stepanek via Mehta |
| `wall_restitution` | 1.0 | 0.85 | tennis racquet COR |
| `gravity_y` | 0.0 | -9.81 | physical |
| Substep | 4–8 per 60Hz frame | same | Catto GDC 2015 |
| CCD | swept-sphere + bisection on TOI | same | Catto GDC 2013 |

**Magnus sign trap (pin in code comment):** `+C_L = backspin (lifts), −C_L = topspin (drops)`. Most-mis-implemented detail in indie tennis threads.

## Decisions locked

| # | Question | Locked answer |
|---|----------|---------------|
| 1 | Where the chamber lives | **Standalone brain process for V1**: `python3 brain_server.py volley_chamber 9878`. Promote to hub-accessible biome later. |
| 2 | Cube dimensions | **12m × 12m × 12m abstract cube.** Configurable per profile. Not a real court. |
| 3 | Vanilla physics defaults | **Arcade defaults — infinite rally, predictable, easy-to-hit.** All channels (gravity, drag, magnus, restitution) present in schema as profile knobs; vanilla turns them OFF or sets them to permissive values (gravity=0, drag=0, magnus=0, restitution=1.0). Realistic-tennis values live in a `tennis_sim` preset that inherits from vanilla. |
| 4 | Serve pattern | **Atari single-press.** Press `fire_primary` → ball spawns stationary in front of player → press `fire_primary` again → strike. Charge-and-release deferred to V3 once envelopes land. |
| 5 | Profile UI | **Keyboard console.** Backtick toggles. Commands: `mass 2.5`, `save zen_mode`, `load vanilla`, `list`, `diff vanilla heavy_club`. Profiles = replayable command scripts (per `feedback_artifacts_capture_arcs`). Grammar V1: whitespace-separated tokens, single-line, no quoting. |
| 6 | Substrate minimum | **Three new substrates + two existing + one wiring point.** See §"Make-brain substrate." |
| 7 | Solver location | **Brain-side** at `core/systems/ballistics.py`. When ping-pong substrate becomes combat substrate in main brain, same module imports — zero port. Single-player + localhost = client-side has no upside. |
| 8 | Run grain | **One row in `vault.runs` per volley brain process lifetime (a session).** Rallies stored as nested events in `metrics_json`. Peak markers = aggregate queries (`MAX(rally.length)` etc.). Retro tennis games saved tournament progression, never per-rally telemetry — no historical model to copy, but session-grain is right for the make-brain framing. |
| 9 | Paddle velocity formula | `paddle_v = camera_angular_velocity × paddle_arm_length`. Default `paddle_arm_length=0.7m`. This is the load-bearing variable for "tennis math = combat math" — carries swing weight to ContactProfile and lets Stage 3 motion envelopes hook in. |
| 10 | Visible paddle | **Stage 3 prereq, not polish.** V1 ships invisible (hitbox at crosshair, matches existing smash). Stage 3 contact-spot env effects need a paddle *with extent* (sweet spot vs edge), so visible/extended paddle is a hard prereq for those effects — schedule as a real PR before Stage 3, not as a polish pass. |

## Make-brain substrate (the meta layer)

Three new artifacts that ship with V1 and become reusable for any
future make-brain instance:

### `vault.profiles` — universal config snapshot table

```sql
CREATE TABLE IF NOT EXISTS profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     TEXT    NOT NULL,                  -- "ping_pong", future "archery", etc.
    profile_name    TEXT    NOT NULL,                  -- "vanilla", "heavy_club", "fast_stab"
    parent_profile  TEXT,                              -- inheritance: heavy_club extends vanilla
    params_json     TEXT    NOT NULL,                  -- per-instance schema, free-form blob
    notes           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE(instance_id, profile_name)
);
CREATE INDEX IF NOT EXISTS idx_profiles_instance ON profiles(instance_id);
```

V1 ships with one row: `(ping_pong, vanilla)`.

### `vault.runs` — universal per-engagement record

```sql
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     TEXT    NOT NULL,
    run_id          TEXT    NOT NULL,                  -- ULID-style
    profile_name    TEXT    NOT NULL,                  -- foreign key to profiles
    started_at      TEXT    NOT NULL,
    ended_at        TEXT,                              -- null if in-progress
    metrics_json    TEXT    NOT NULL DEFAULT '{}',     -- session-grain blob; ping_pong stores rallies[] with per-rally length/max_v/contacts
    terminal_state  TEXT,                              -- "won" / "lost" / "aborted" / null
    UNIQUE(instance_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_runs_instance ON runs(instance_id);
CREATE INDEX IF NOT EXISTS idx_runs_profile ON runs(instance_id, profile_name);
```

Peak markers are queries on this — `SELECT MAX(json_extract(metrics_json, '$.rally_length')) WHERE instance_id='ping_pong'` — not a separate table.

### `core/systems/make_brain_registry.py` — instance dispatch

Small Python module. Each instance registers a record:

```python
register(
    instance_id="ping_pong",
    entry_point="biome:volley_chamber",          # or "object:fridge" for reflective, etc.
    default_profile="vanilla",
    state_event_types=[
        "make_brain_started", "make_brain_ended", "profile_loaded",
        "peak_recorded",                          # universal
        "time_scale_changed",                     # Stage 3 parry — emit shape pinned now, renderer-respect deferred
        "ball_spawned", "ball_struck", "ball_settled",
        "rally_started", "rally_ended", "score_changed",
    ],
    handler=PingPongHandler,                      # class with .on_command(), .tick(), .on_input()
)
```

Brain dispatches commands by `instance_id` → handler. Future archery, reflective-loop instances just register here; no surgery on `brain_server.py` dispatch.

### Existing substrates consumed

- **StateEvent primitive** (`design_state_events`) — make-brains emit StateEvents on every state change. No new infra.
- **`input_map.py`** (new this feature, see §"Input bindings") — abstract action layer. Make-brains declare which actions they consume.

## Surface — volley chamber

- **Standalone brain instance:** `python3 brain_server.py volley_chamber 9878`. Boots with no outdoor/cavern state, only the volley_chamber biome.
- **Biome `volley_chamber`** — 12×12×12 cube. 4 walls + floor + ceiling, all wireframe. No clutter, no flora, no atmosphere. Single light source for orientation. Player spawns at center facing the +Z wall (the "front" wall).
- **Vector terminal** connects to port 9878 (CLI flag passthrough).
- **HUD identity:** "VOLLEY CHAMBER" header, current profile name, score block, live ContactProfile readout.

## Physics contract

### BallisticsSolver — `core/systems/ballistics.py` (brain-side)

Lives in `core/` (not `clients/`) so the same solver hosts ping-pong V1
*and* future combat encounters in the main brain — no port. Brain owns
canonical ball state; client renders from manifest.

Discrete-time 3D projectile solver. Fixed-substep update (default 240 Hz,
4–8 substeps per 60Hz frame per Catto GDC 2015 guidance). Per substep:

1. Integrate ball state under gravity, drag, magnus (Verlet or RK4 — start with semi-implicit Euler, upgrade if needed).
   - **Magnus sign convention pinned in code comment** at the integrator:
     `+C_L = backspin (lifts), −C_L = topspin (drops)`. This is the
     most-mis-implemented detail in indie tennis threads.
2. Swept-sphere test ball trajectory against all 6 walls + paddle hitbox. Earliest-hit wins. CCD per Catto GDC 2013 (swept-sphere vs. plane + bisection on TOI).
3. On hit: compute reflection per ContactProfile, apply restitution, advance to remaining substep time.
   - **Reflection (normal component):** `v_ball_n' = (1+e)·v_paddle_n − e·v_ball_n`
   - **Tangential:** picks up paddle tangent × friction → spin imparts here
4. Emit StateEvents on transition: `ball_struck`, `ball_settled` (KE below threshold), boundary-cross events.

### MotionVector — abstract key

```python
@dataclass(frozen=True)
class MotionVector:
    pos:        tuple[float, float, float]    # m
    vel:        tuple[float, float, float]    # m/s
    spin:       tuple[float, float, float]    # rad/s (Magnus axis × magnitude)
    timestamp:  float                          # solver time
```

### ContactProfile — abstract key

```python
@dataclass(frozen=True)
class ContactProfile:
    contact_point:      tuple[float, float, float]
    incoming:           MotionVector
    paddle_normal:      tuple[float, float, float]    # unit vector
    paddle_velocity:    tuple[float, float, float]    # m/s, paddle's instantaneous v at contact
    outgoing:           MotionVector
    coupling_factor:    float                          # 1.0 = full energy transfer (vanilla)
    contact_kind:       str                            # "strike" V1; "block"/"parry" Stage-3
```

Every contact event records one ContactProfile. Logged to vault.runs.metrics_json[].contacts in V1.5+ (V1 keeps in-memory only — schema slot reserved).

### Vanilla profile params (arcade defaults)

Target: infinite rally, predictable bounces, decisive hits. All
realistic-physics channels are present in the schema but turned OFF or
set permissive — this is what "no funny business" means in arcade
framing. User dials toward sim via console or by loading `tennis_sim`.

```json
{
  "_target":              "arcade — infinite rally, predictable, easy-to-hit",
  "ball_mass":            1.0,
  "ball_radius":          0.15,
  "ball_drag_coeff":      0.0,
  "ball_magnus_coeff":    0.0,
  "gravity_y":            0.0,
  "wall_restitution":     1.0,
  "coupling_factor":      1.0,
  "paddle_hitbox_radius": 0.6,
  "paddle_arm_length":    0.7,
  "swing_velocity":       12.0,
  "cube_size":            12.0,
  "serve_offset":         [0.0, 1.6, 1.5]
}
```

### Tennis-sim preset (ships alongside vanilla)

Inherits from vanilla; overrides only the realistic-physics channels.
Demonstrates profile inheritance + gives a one-keystroke dial-up to
peer-reviewed tennis values when user wants that direction.

```json
{
  "_target":              "tennis sim — Mehta wind-tunnel coefficients",
  "_parent":              "vanilla",
  "ball_mass":            0.058,
  "ball_radius":          0.0335,
  "ball_drag_coeff":      0.55,
  "ball_magnus_coeff":    0.175,
  "gravity_y":            -9.81,
  "wall_restitution":     0.85
}
```

### Paddle velocity formula

Client computes paddle velocity at strike time as:

```
paddle_v = camera_angular_velocity × paddle_arm_length
```

This is the **load-bearing variable** for "tennis math = combat math" —
mouse-flick speed becomes paddle velocity, standing still = small
swing. Carries through ContactProfile to outgoing ball velocity (and
later to weapon-arc impact for combat). Stage 3 motion envelopes
multiply this term to fake heavy-club / fast-stab feel without
changing the math elsewhere.

## Tennis scoring engine — `core/systems/volley_scoring.py`

Standard tennis: 0/15/30/40/game, 2-point game lead, first to 6 games (2-game lead) wins set, best-of-3 sets. State machine. Out-of-bounds in Stage 1 (wall rally) = ball passes back behind player's serve line = miss.

```python
@dataclass
class MatchState:
    sets:       list[tuple[int, int]]    # [(player_games, opp_games), ...]
    current:    tuple[int, int]          # (player_games, opp_games)
    game:       tuple[int, int]          # (0/15/30/40, 0/15/30/40)
    server:     str                       # "player" / "opp"
    in_rally:   bool
    rally_id:   str | None
```

V1 (solo wall rally): "opp" never scores; player scores by hitting wall and successfully returning. Miss = "opp" gets the point.

## Brain ↔ client contract

New brain commands (additive to existing dispatch):

| cmd                | payload                                    | response                             |
|--------------------|--------------------------------------------|--------------------------------------|
| `volley_serve`     | `{}` (state-aware)                         | `{ok}` — emits `ball_spawned` event  |
| `volley_strike`    | `{paddle_pos, paddle_normal, paddle_vel}`  | `{ok, contact_profile}` or `{ok:false, reason: "no_ball_in_range"}` |
| `volley_reset_rally` | `{}`                                     | `{ok}`                               |
| `volley_reset_match` | `{}`                                     | `{ok}`                               |
| `profile_save`     | `{instance_id, profile_name, params}`      | `{ok}`                               |
| `profile_load`     | `{instance_id, profile_name}`              | `{ok, params}` or `{ok:false, reason:"not_found"}` |
| `profile_list`     | `{instance_id}`                            | `{ok, profiles: [...]}`              |
| `console_exec`     | `{line: "mass 2.5"}`                       | `{ok, output}` or `{ok:false, reason}` |

Manifest additions for active volley instance:

```python
{
  "instance_id":     "ping_pong",
  "ball":            { "x", "y", "z", "vx", "vy", "vz", "exists": bool },
  "match_state":     { "sets":[...], "current":[g,g], "game":[p,p], "in_rally":bool },
  "active_profile":  "vanilla",
  "contact_log":     [ {ContactProfile JSON}, ... ],   # last N for HUD
  "console_state":   { "open": bool, "lines": [...], "input": "..." },
}
```

## Input bindings

### `clients/vector_terminal/input_map.py` — new abstraction

Mirrors Godot's InputMap pattern, ported to raylib-py. Action names → list of triggers. Each trigger is one of: keyboard key, mouse button, gamepad button, gamepad axis (with threshold).

V1 actions:

| Action | Default keyboard | Default mouse | Default gamepad |
|---|---|---|---|
| `fire_primary` (swing / serve commit) | — | LMB | RT (button index per project.godot) |
| `melee` (alt strike — reserved) | — | RMB | RB |
| `aim_ads` (reserved Stage 3 block) | — | — | LT |
| `move_forward/back/left/right` | WASD | — | left stick |
| `look_*` | — | mouse motion | right stick |
| `jump` | SPACE | — | A |
| `interact` | F | — | X |
| `console_toggle` | backtick (`` ` ``) | — | — |
| `pause` | ESC | — | START |
| `reset_rally` | R | — | — |
| `reset_match` | SHIFT+R | — | — |

Existing `is_mouse_button_pressed(MOUSE_BUTTON_LEFT)` → `input_map.pressed("fire_primary")`. Existing `is_key_pressed(KEY_F)` → `input_map.pressed("interact")`. The downstream payload (ContactProfile construction, brain command) doesn't change.

## Renderer contract

- **Cube room** renders via wireframe primitives — reuses `wireframe_renderer.py`. 6 quad faces as wire-only.
- **Ball** renders via existing entity primitive with `kind: "ball"`. Sphere wireframe, ~24 lat/lon segments. Color cycles slightly with velocity (visual feedback for tuning, not gameplay).
- **Paddle** is invisible in V1 — hitbox at crosshair, matches existing smash primitive. Visible mesh deferred to a polish PR.
- **Contact flash** reuses `interact_flashes` (line 397 in main.py). White on strike, gold on parry (Stage 3+).
- **HUD overlay (volley active):**
  ```
  VOLLEY CHAMBER — vanilla
  SETS  0 - 0      GAME  30 - 15      RALLY  4 contacts
  BALL  ( 2.4, 1.8, 7.2 )    v 14.2 m/s
  LAST  in 14.0 → out 13.7 m/s    coupling 1.00
  ```
- **Console overlay (when open):**
  ```
  > mass 2.5
    OK ball_mass = 2.5
  > save heavy_club from vanilla
    OK profile saved (ping_pong, heavy_club)
  > _
  ```

## Definition of done — definitive AC

### TEST
- [ ] **T1** — `tests/test_make_brain_substrate.py` covers `vault.profiles` and `vault.runs` schema migration on existing vault.db; CRUD round-trip for both tables; profile parent-inheritance resolution.
- [ ] **T2** — `tests/test_make_brain_registry.py` covers instance registration, dispatch by `instance_id`, error on unknown instance, state_event_types validation.
- [ ] **T3** — `tests/test_input_map.py` covers action → trigger binding, action lookup, multi-trigger OR semantics (LMB OR RT both fire `fire_primary`), gamepad axis threshold logic.
- [ ] **T4** — `tests/test_ballistics.py` covers solver determinism (same initial state + same dt = same trajectory), gravity-only fall, drag-decay terminal velocity, magnus deflection, swept-sphere wall reflection, no tunneling at vmax (test ball at 100 m/s through 12m cube — must hit wall, never pass through).
- [ ] **T5** — `tests/test_contact_profile.py` covers ContactProfile construction from MotionVector + paddle state, outgoing velocity = elastic reflection + paddle velocity coupling, coupling_factor scaling.
- [ ] **T6** — `tests/test_volley_scoring.py` covers full match progression (0→15→30→40→game; deuce; set; match), state transitions, server alternation rules, V1 wall-rally scoring (only player scores, miss = point lost).
- [ ] **T7** — `tests/test_volley_chamber_brain.py` covers volley brain instance boots cleanly on port 9878, manifest emits the chamber + ball state, all volley_* commands round-trip, profile load/save persists across restart.
- [ ] **T8** — `tests/test_console.py` covers tokenization (`mass 2.5`, `save heavy_club from vanilla`, `load vanilla`, `list`), unknown-command error, profile-not-found error, console history navigation.
- [ ] **T9** — All test suites green together; no regression in existing 119/119 + base suites.

### MIGRATION
- [ ] **M1** — Existing vault.db opens cleanly, picks up `profiles` and `runs` tables on first volley brain boot, never touches existing rows. Vanilla profile auto-inserted on first boot if absent.

### VISUAL
- [ ] **V1** — `python3 brain_server.py volley_chamber 9878` boots without error. Vector terminal connects, renders cube room. HUD shows "VOLLEY CHAMBER — vanilla."
- [ ] **V2** — Press `fire_primary`. Ball appears at serve offset, stationary (arcade vanilla has gravity=0, so it hangs in place — not a bug).
- [ ] **V3** — Press `fire_primary` again with crosshair on ball. Ball launches forward at swing velocity. Strikes far wall, returns toward player.
- [ ] **V4** — Player swings (LMB or RT) at returning ball with crosshair on it. Ball reflects toward wall again. Rally continues.
- [ ] **V5** — HUD score updates: each successful contact tallies in rally counter; ball passing back-line increments opponent point per scoring rules.
- [ ] **V6** — Press backtick. Console overlay appears. Type `gravity_y -3.0` + ENTER. Next strike, ball visibly arcs downward instead of traveling straight (arcade → semi-sim dial confirmed live).
- [ ] **V7** — In console, type `save heavy_club from vanilla` + ENTER. Confirmation. Restart brain. Type `load heavy_club`. Same heavy parameters apply.
- [ ] **V8** — In console, type `load vanilla`. Parameters revert.
- [ ] **V9** — Tunneling guard: console command `swing_velocity 100` (extreme). Strike. Ball at 100 m/s never passes through walls (visual confirmation matches T4 assertion).
- [ ] **V10** — Press R. Current rally resets, ball clears, ready to serve again. Score preserved.
- [ ] **V11** — Press SHIFT+R. Match resets. Score zeros.

### SCENARIO
- [ ] **S1** — Boot volley brain. Serve. Sustain rally for ≥10 contacts on vanilla. ContactProfile values visible in HUD update each contact. Each contact emits `ball_struck` StateEvent.
- [ ] **S2** — During an active rally, miss the ball (let it pass back-line). Score updates; new serve auto-prompts. Telemetry: a `vault.runs` row exists with `terminal_state="lost"` and `metrics_json` containing rally_length and max_v.
- [ ] **S3** — Save `zen` profile from vanilla with low gravity (`gravity_y -2.0`). Save `gritty` profile with high mass + low coupling. Switch between them mid-session via console. Each switch logs a new run with the active profile recorded. After session, query `vault.runs` confirms each rally tagged with the right profile.
- [ ] **S4** — Kill brain mid-rally. Restart. Console `load zen` re-applies zen profile. Score is reset (sessions don't bridge); profile persistence does.
- [ ] **S5** — Gamepad path: same flow as V1–V8 using Xbox controller (RT serve/strike, START pause, left stick move, right stick look). Confirm input_map abstraction routes both keyboard and gamepad through the same downstream code.

### Out-of-scope (V1)
- NPC opponent (Stage 2 — invisible return-function).
- Motion envelope primitive / dynamic velocity arcs (Stage 3 — heavy-club, fast-stab paddle dynamics).
- Block / parry / parry-window / coup-de-grace (combat translation — Stage 3 follow-up).
- Visible paddle mesh (Stage 3 prereq — required for sweet-spot vs edge contact-spot env effects, not a polish pass).
- Magnus / spin tracking from paddle motion (Stage 3 — needs envelope).
- HUD overlay panel UI (we picked console; deferred unless console proves wrong).
- In-world dial pedestals (long-term home for tunings; deferred).
- Hub-accessible biome promotion (V1 ships standalone; promotion is a separate PR once tuned).
- Audio hooks (per `feedback_audio_last`).
- Visible NPC sprite (per Stage 2 spec — function-only opponent).
- Time-dilation StateEvent renderer (Stage 3 dependency; emit shape pinned now, renderer respects deferred).

## Phasing — PR breakdown

### PR 1 — make-brain substrate
- `vault.profiles` + `vault.runs` schema + idempotent migration in `core/vault.py`.
- Helpers: `vault.profile_save / profile_load / profile_list / run_start / run_end / runs_by_instance`.
- `core/systems/make_brain_registry.py` with `register()` + `dispatch()`.
- Brain dispatch wires `profile_save / profile_load / profile_list` (instance-agnostic).
- Auto-insert vanilla profile shape on first boot for any registered instance.
- T1 + T2 + M1 green.

### PR 2 — input_map.py port  ⚠️ *refactor with regression burden*
- New `clients/vector_terminal/input_map.py` mirroring Godot's InputMap pattern.
- All existing main.py inputs migrated through the abstraction (LMB/F/keys all flow through `input_map.pressed()`).
- Gamepad bindings added: RT/RB/LT/A/B/X/Y/sticks/dpad, mapping to action names.
- Default bindings file shipped.
- **This is a real refactor, not just a new module** — every existing
  `is_mouse_button_pressed` / `is_key_pressed` call site changes. Touches
  the entire main.py input loop including workroom BUILD/EDIT mode,
  fridge engagement, pillar engagement, tag events. Run full test suite
  + manual UAT smoke against the workroom flow before declaring done.
- T3 green. Existing `test_targeting.py` and other input-touching tests still green. **Existing UAT scenarios for workroom + reflective fridge unchanged.**

### PR 3 — volley_chamber biome + brain instance
- New `volley_chamber` biome boot: `brain_server.py volley_chamber 9878`. Boots only volley_chamber biome.
- `volley_chamber` biome registered: 12×12×12 cube wireframe room.
- Manifest emits `instance_id: "ping_pong"`, cube geometry, player spawn at center.
- Vector terminal connects, renders cube, HUD shows VOLLEY CHAMBER identity.
- Initial PingPongHandler stub registered with make_brain_registry.
- V1 partial green.

### PR 4 — BallisticsSolver + ball entity
- **Required reading before coding:**
  - Erin Catto, *Physics for Game Programmers: Continuous Collision*, GDC 2013 (PDF). Canonical for swept-sphere CCD.
  - Catto, *Numerical Methods*, GDC 2015. Integrator + substep guidance.
  - Spin Doctor docs (sonic.net/~goddard/home/spin/docs/spin.html). Closest paddle/ball model to our ContactProfile shape; mine for paddle-velocity input semantics.
- New `core/systems/ballistics.py` — discrete-time 3D solver, semi-implicit Euler, fixed-substep tunneling guard (4–8 substeps per 60Hz frame).
- Magnus sign convention pinned in code comment at the integrator: `+C_L = backspin (lifts), −C_L = topspin (drops)`.
- MotionVector + ContactProfile abstract keys.
- Ball entity in manifest with `kind: "ball"` and full state (pos, vel, spin).
- Wall-only collision: ball reflects off all 6 walls under wall_restitution.
- `volley_serve` command: spawns ball at serve_offset, stationary.
- Vanilla profile (arcade defaults — drag=0, magnus=0, gravity=0, restitution=1.0) ships seeded; `tennis_sim` preset (peer-reviewed coefficients) ships alongside as a `_parent: vanilla` profile.
- T4 + V2 green.

### PR 5 — paddle strike + ContactProfile
- `volley_strike` command: takes paddle_pos + paddle_normal + paddle_vel, runs collision against ball, computes ContactProfile, updates ball MotionVector.
- **Client computes paddle_vel** at strike time as `camera_angular_velocity × paddle_arm_length`. Tracked over a short window (e.g., last 5 frames) so a brief mouse-flick produces real velocity. This is the load-bearing carrier from tennis-math to combat-math; pin in module docstring.
- **Reflection math** (in solver, called from this PR):
  - Normal: `v_ball_n' = (1+e)·v_paddle_n − e·v_ball_n`
  - Tangential: `v_ball_t' = v_ball_t + friction·v_paddle_t` (where future spin imparts)
- LMB/RT path in main.py extended: when crosshair-near-ball, send `volley_strike` instead of `kind_destroyed`. Existing smash path stays for non-volley brains (gated on instance_id).
- Existing `interact_flashes` reused for contact visualization.
- T5 + V3 + V4 green.

### PR 6 — tennis scoring + match state
- `core/systems/volley_scoring.py` — MatchState + state machine.
- Brain integrates scoring: rally start on serve, contact tally, out-of-bounds detection (back-line crossing), point/game/set/match progression.
- `volley_reset_rally / volley_reset_match` commands.
- HUD shows live score block.
- StateEvents: `rally_started`, `rally_ended`, `score_changed`.
- T6 + V5 + V10 + V11 green.

### PR 7 — keyboard console + profile commands
- New `clients/vector_terminal/console.py` — overlay state, tokenizer, history.
- Backtick toggle. Commands: setters (`<param> <value>`), `save <name> [from <parent>]`, `load <name>`, `list`, `diff <a> <b>`, `help`.
- Brain `console_exec` command dispatches lines through the volley handler.
- Profile shape for ping_pong fully defined; vanilla seeded.
- T7 + T8 + V6 + V7 + V8 green.

### PR 8 — telemetry + UAT
- Brain records vault.runs entries: rally start → rally end with metrics_json.
- Aggregate query helpers (peak rally length, peak max_v per profile).
- UAT pass: hands-on S1–S5.
- Tunneling guard verified at extreme swing_velocity.
- Pin `project_make_brain_ping_pong_v1` memory + `design_make_brain_substrate` memory.
- T9 + S1–S5 + V9 green.

### PR 9 — activity-loop substrate + first producer
**Frame:** Old-dev discipline applied. The "what is this player doing" question
is too important and too frequent to live in a per-event log. Bytes-as-counters,
tables-as-policy, polled-not-pushed. Telemetry log exists but is never read for
gameplay. Per `feedback_factor_of_7` and the SNES-discipline framing locked
2026-05-05.

- New `core/systems/activity_loop.py`:
  - `ActivityClass` IntEnum, **seven slots, pinned**: `HUNT MAKE SNEAK UNWIND SOLVE WANDER RITUAL`. No string class names in hot path.
  - `PreferenceCounters` — `int[7]`, saturating at 255, slot-decay rotating across classes (one slot decremented per `DECAY_PERIOD_FRAMES`). O(1) emit + O(1) tick.
  - `REWARD_TABLE` — static `tuple[(class, threshold, kind, register), ...]`. Edits require brain restart. Polled each tick.
  - `ActivityLoop.tick()` — edge-detect rewards via `prev_count[c] < threshold ≤ count[c]`; fire one `StateEvent` per crossing. No callbacks, no chains.
- `BrainWorld` owns singleton `PreferenceCounters` + `ActivityLoop` (alongside `state_events`). Ticked once per server tick.
- **One producer wired:** `PingPongHandler.on_tick` brick-destroyed branch — `prefs.emit(HUNT, intensity=1 if max_hp==1 else 3)`. Single-line addition.
- Optional `vault.activity_log` table — append-only telemetry, **never read for gameplay**. Used for UAT readout + later post-hoc analysis. Schema additive, idempotent migration.
- Console command: `activity_summary` — backtick console, returns per-class counts + last N reward firings.
- Out of scope: TensionCycle reading counters, other producers (workroom seed_create, journal-quest, lexicon), reward side-effects beyond StateEvent, migrating existing `_emit_event` chains to ActivityEvent.
- T10 (activity_loop pytest: saturate cap, slot-decay rotation, edge detection fires once, StateEvent emission) + S6 (volley_chamber → strike bricks → `activity_summary` shows HUNT counter advance → cross threshold → toast renders).

### PR 10 — UNWIND producer (second class, validates multi-producer signal)
**Frame:** Adds the second activity producer to confirm the substrate carries
multi-class signal correctly. UNWIND is the natural second slot — `dwell_time`
is already a measured value; we translate it into the activity-loop currency
without adding a new instrumentation surface.

- New `DWELL_UNWIND_SLICE_SECONDS` const in `core/systems/activity_loop.py`
  (default 10s — see comment above the const for the threshold-duration math).
- `BrainWorld.__init__` adds `_dwell_accum_for_unwind: float = 0.0` —
  pure-cumulative, decoupled from the existing `dwell_time` (which decays on
  movement). One emit per slice of accumulated low-input time, even across
  active stretches.
- `run_server`'s dissociation block (low-input branch) drains the accumulator
  in a `while` loop, calling `activity_loop.emit_activity(UNWIND, 1)` once per
  slice crossing.
- REWARD_TABLE adds two rows:
  - `(UNWIND, 30,  "unwind_recognized", "UNWIND — RECOGNIZED", ritual)` (~5 min)
  - `(UNWIND, 100, "unwind_deepened",   "UNWIND — DEEPER",     ritual)` (~17 min)
- Out of scope: rewriting how `dwell_time` itself works, integrating UNWIND
  with reflective_loop entry (later PR), persisting the accumulator across
  brain reboots.
- T10 expanded (slice constant legibility, UNWIND threshold crossings, register
  matches state_events RITUAL vocab) + S7 (volley_chamber boot → don't move
  for 5 min → `activity` shows UNWIND ≥30 → "UNWIND — RECOGNIZED" toast).

## Hot-reload notes
- `core/vault.py` schema changes → brain restart.
- `core/systems/make_brain_registry.py` → brain restart.
- `core/systems/ballistics.py` / `volley_scoring.py` / `activity_loop.py` → brain restart.
- `REWARD_TABLE` in `activity_loop.py` (compile-time constant) → brain restart.
- `clients/vector_terminal/input_map.py` → vector terminal restart.
- `clients/vector_terminal/console.py` → vector terminal restart.
- `brain_server.py` dispatch → brain restart.
- Profiles edited via console: live, no restart.

## Parallel-safe siblings
- `feat/loop-completion` — disjoint files except `brain_server.py` dispatch (additive). Merge order: whoever lands first gets clean diff.
- `feat/vector-workroom` (PR 6 in flight) — disjoint code paths; both extend brain dispatch additively.
- Permanent Objects journal queue (J4/J5/J6.1/J7) — disjoint vault tables.
- Future make-brain instances (archery, reflective tuning, etc.) — explicitly enabled by this feature; expected to land disjoint per make_brain_registry.

## Acceptance signature

Once T1–T9 + M1 + V1–V11 + S1–S5 hold and PR 8 UAT passes, the
feature is shipped. Pin `project_make_brain_ping_pong_v1` AND
`design_make_brain_substrate` memories at that point with:

- vault.profiles + vault.runs contracts
- make_brain_registry signature
- input_map.py abstraction
- ContactProfile + MotionVector abstract keys
- Tunneling guarantee (swept-sphere, fixed substep)
- StateEvent types every make-brain emits

so future make-brain instances (archery / parabolic ballistics, future
reflective-loop tuning, future puzzle/encounter modules) extend cleanly
without re-litigating the substrate.
