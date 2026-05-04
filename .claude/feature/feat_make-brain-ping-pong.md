# Feature — feat/make-brain-ping-pong

**Status:** Spec locked 2026-05-04. Implementation pending.
**Branch:** TBD — sibling spawn or live on `feat/loop-completion` (defer
per `feedback_artifacts_capture_arcs`; pick at PR 1 commit time).

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

## Decisions locked

| # | Question | Locked answer |
|---|----------|---------------|
| 1 | Where the chamber lives | **Standalone brain process for V1**: `python3 brain_server.py volley 9878`. Promote to hub-accessible biome later. |
| 2 | Cube dimensions | **12m × 12m × 12m abstract cube.** Configurable per profile. Not a real court. |
| 3 | Vanilla physics defaults | Standard relative physics — gravity, drag, magnus channels all present and enabled. Magnus coefficient defaults to 0 in V1 (no spin source until Stage 3 envelopes). All knobs tunable via profile. |
| 4 | Serve pattern | **Atari single-press.** Press `fire_primary` → ball spawns stationary in front of player → press `fire_primary` again → strike. Charge-and-release deferred to V3 once envelopes land. |
| 5 | Profile UI | **Keyboard console.** Backtick toggles. Commands: `mass 2.5`, `save zen_mode`, `load vanilla`, `list`, `diff vanilla heavy_club`. Profiles = replayable command scripts (per `feedback_artifacts_capture_arcs`). |
| 6 | Substrate minimum | **Three new substrates + two existing + one wiring point.** See §"Make-brain substrate." |

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
    metrics_json    TEXT    NOT NULL DEFAULT '{}',     -- per-instance peaks: rally_length, max_v, contact_count
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

- **Standalone brain instance:** `python3 brain_server.py volley 9878`. Boots with no outdoor/cavern state, only the volley_chamber biome.
- **Biome `volley_chamber`** — 12×12×12 cube. 4 walls + floor + ceiling, all wireframe. No clutter, no flora, no atmosphere. Single light source for orientation. Player spawns at center facing the +Z wall (the "front" wall).
- **Vector terminal** connects to port 9878 (CLI flag passthrough).
- **HUD identity:** "VOLLEY CHAMBER" header, current profile name, score block, live ContactProfile readout.

## Physics contract

### BallisticsSolver — `core/systems/ballistics.py`

Discrete-time 3D projectile solver. Fixed-substep update (default 240 Hz, 4 substeps per 60Hz frame). Per substep:

1. Integrate ball state under gravity, drag, magnus (Verlet or RK4 — start with semi-implicit Euler, upgrade if needed).
2. Swept-sphere test ball trajectory against all 6 walls + paddle hitbox. Earliest-hit wins.
3. On hit: compute reflection per ContactProfile, apply restitution, advance to remaining substep time.
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

### Vanilla profile params

```json
{
  "ball_mass":            0.058,
  "ball_radius":          0.0335,
  "ball_drag_coeff":      0.5,
  "ball_magnus_coeff":    0.0,
  "gravity_y":            -9.81,
  "wall_restitution":     0.95,
  "coupling_factor":      1.0,
  "paddle_hitbox_radius": 0.5,
  "swing_velocity":       15.0,
  "cube_size":            12.0,
  "serve_offset":         [0.0, 1.6, 1.5]
}
```

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
- [ ] **V1** — `python3 brain_server.py volley 9878` boots without error. Vector terminal connects, renders cube room. HUD shows "VOLLEY CHAMBER — vanilla."
- [ ] **V2** — Press `fire_primary`. Ball appears at serve offset, stationary, slight wobble.
- [ ] **V3** — Press `fire_primary` again with crosshair on ball. Ball launches forward at swing velocity. Strikes far wall, returns toward player.
- [ ] **V4** — Player swings (LMB or RT) at returning ball with crosshair on it. Ball reflects toward wall again. Rally continues.
- [ ] **V5** — HUD score updates: each successful contact tallies in rally counter; ball passing back-line increments opponent point per scoring rules.
- [ ] **V6** — Press backtick. Console overlay appears. Type `mass 2.5` + ENTER. Vanilla ball mass updates live; ball trajectory visibly heavier on next strike.
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
- Visible paddle mesh (polish pass).
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

### PR 2 — input_map.py port
- New `clients/vector_terminal/input_map.py` mirroring Godot's InputMap pattern.
- All existing main.py inputs migrated through the abstraction (LMB/F/keys all flow through `input_map.pressed()`).
- Gamepad bindings added: RT/RB/LT/A/B/X/Y/sticks/dpad, mapping to action names.
- Default bindings file shipped.
- T3 green. Existing `test_targeting.py` and other input-touching tests still green.

### PR 3 — volley_chamber biome + brain instance
- New `volley` brain mode: `brain_server.py volley 9878`. Boots only volley_chamber biome.
- `volley_chamber` biome registered: 12×12×12 cube wireframe room.
- Manifest emits `instance_id: "ping_pong"`, cube geometry, player spawn at center.
- Vector terminal connects, renders cube, HUD shows VOLLEY CHAMBER identity.
- Initial PingPongHandler stub registered with make_brain_registry.
- V1 partial green.

### PR 4 — BallisticsSolver + ball entity
- New `core/systems/ballistics.py` — discrete-time 3D solver, semi-implicit Euler, fixed-substep tunneling guard.
- MotionVector + ContactProfile abstract keys.
- Ball entity in manifest with `kind: "ball"` and full state (pos, vel, spin).
- Wall-only collision: ball reflects off all 6 walls under wall_restitution.
- `volley_serve` command: spawns ball at serve_offset, stationary.
- T4 + V2 green.

### PR 5 — paddle strike + ContactProfile
- `volley_strike` command: takes paddle_pos + paddle_normal + paddle_vel, runs collision against ball, computes ContactProfile, updates ball MotionVector.
- LMB/RT path in main.py extended: when crosshair-near-ball, send `volley_strike` instead of `kind_destroyed`.
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

## Hot-reload notes
- `core/vault.py` schema changes → brain restart.
- `core/systems/make_brain_registry.py` → brain restart.
- `core/systems/ballistics.py` / `volley_scoring.py` → brain restart.
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
