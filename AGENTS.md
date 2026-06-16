# AGENTS.md

Contract every agent reads before touching this repo.

## Read order
1. AGENTS.md (this file)
2. The ONE Layer-1 AGENTS.md for the subsystem you're touching
3. Layer-4 files (`LIVE_STATE.md`, `LIVE_PIPELINE_MAP.md`) only if your task names them
4. `.claude/audit_framework.md` if the task is audit-shaped (force-multiplier review, architecture or migration audit)

Do not chain reads beyond this. Subagents inherit this contract via the spawning prompt.

**Skip the read for trivial work** — typo fixes, single-line questions about a known location, status checks. The scaffold is overhead that earns its keep on multi-file or behavior-bearing changes; for one-shots it's just tax.

## Hard rules
- Air-gap: no LLM calls in production paths. Lexicon is gensim/spaCy.
- Voice: copy echoes the user's wife's writing — never D&D tutorial.
- No hardcoded tunables: literals controlling behavior live as named consts at file top.
- kind_config single source: scale/color/collision/recipes live in `config/kind_config.json`.
- BIOME_REGISTRY single source: never `if biome == ...` in live code.
- Brain owns config: `core/systems/biome_data.py` is canonical. Godot reads manifest.
- One change at a time: edit, screenshot, confirm, proceed.
- No layering: execute the named scope only. No "while I'm here" cleanups.
- No reverting on first failure: tune the one variable that broke. (But reverting IS valid after UAT exposes a wrong implementation — see `feedback_coordinate_convention_class`.)
- Plan before code on trajectory shifts.
- Confirm before fix: present options, let the user pick direction.
- Coord math pairs: when adding code that does coordinate math (tile keys, distance, projection), search the codebase for the OTHER side of the convention and write a cross-reference test pinning them together. Two silent bugs shipped before 2026-05-01 UAT caught this. See `feedback_coordinate_convention_class`.
- Vector terminal first: the canonical client per `design_brain_ground_truth`. Godot is paused; treat its rendering as reference, not parity target. Banner compositing, HUD, overlays all land in vector terminal first. Godot hooks come at the end if/when needed.
- Banner compositing as universal primitive: every camera-relative visual (HUD, particles, beacons, atmosphere, horizon objects) goes through the 7-layer banner system per `design_banner_compositing`. Don't add new ad-hoc overlay subsystems — assign a layer + role.
- (Full Won't-tolerate list: see memory pin `design_wont_tolerate`.)

## Live-vs-legacy
The repo has Panda3D-era files still launchable via `make` targets.
Refactoring legacy is zero-leverage. See `LIVE_PIPELINE_MAP.md` for the boundary.
If a file imports `direct.showbase.ShowBase` or `panda3d.*`, it is legacy.

## Process model
Live procs during a session:
- `python3 brain_server.py outdoor 9877` — Python brain, TCP :9877
- Godot 4.4 viewer (`godot/main.tscn`)
- Optionally: `clients/vector_terminal/main.py`

Restart brain on edits to: `biome_data.py`, lexicon, vault schema.
Godot reloads manifest automatically; restart on shader edits.

## Wire format
JSON-line over TCP :9877. Schema bumps require both-end deploy.
Brain emits raw entity state. Render hints (fade, lighting, scanline) live in clients.

## Subagent vs main-thread
Spawn a subagent for: 3+ file lookups, multi-source reconciliation, parallel work, surveys.
Stay main-thread for: targeted edits, single-file tasks, design discussion, iterative work needing screenshots.

## Subagent briefing pattern
When spawning Agent (Explore, general-purpose, Plan), the prompt MUST include:
"Read AGENTS.md and <relevant subsystem>/AGENTS.md before starting. Then: <task>."
Subagents have no auto-memory. These files are their only durable context.
For parallel-safe sibling features (per `.claude/feature/<branch>.md`), pass `isolation: "worktree"` to keep changes isolated.

Example briefing (good shape — short, specific, capped):
"Read AGENTS.md and core/systems/journal/AGENTS.md before starting.
Then: locate all callers of vault.py public API outside core/systems/journal/.
Return file:line list. No analysis. Cap response at 50 lines."

## Model routing
Pass the `model` param when spawning Agent calls. Default inherits from parent.
- Haiku  — file lookups, grep, status checks, syntax fixes, classification
- Sonnet — implementation work (code edits, refactors, tests)
- Opus   — design, planning, audits, multi-file architecture

## Acceptance criteria taxonomy
Tag every change with at least one:
- TEST     — pytest path validates it
- VISUAL   — screenshot UAT, user confirms
- SCENARIO — runs through brain + client end-to-end
- MIGRATION — old vault/save loads after schema bump

## Promotion ladder for new doctrine
correction → SHARED_STATE.md (immediate visibility)
           → feature AGENTS (this branch only)
           → subsystem AGENTS (recurs in this domain)
           → root AGENTS      (cross-cutting)

**Mandate:** Every behavioral fix or feature implementation **MUST** end with a proposed update to the relevant AGENTS.md or SHARED_STATE.md. "Fixing the code is 50% of the task; updating the machine's instructions is the other 50%."
