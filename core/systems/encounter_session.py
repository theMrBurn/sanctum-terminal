"""EncounterSession — runtime instance of the encounter primitive.

One session per Godot connection. Builds from a scout config entry:

    scout → actor (Orb) + environment + objects + ceremony + flavor

Responds to Godot events:

    on_camera(x, y)        → maybe trigger an encounter at the nearest tile
    on_action(action)      → resolve player action, orb takes turn, ceremony
    on_portal()            → portal_exit
    on_hub_arrival()       → consolidate staged XP into depth

The primitive is config-composable: swap the scout id and you get a new
encounter with no code changes. Future scouts pick different actors / envs /
objects from their respective pools.

Victory paths (either closes the encounter):
    - player net_passes >= RESOLUTION_THRESHOLD (understanding)
    - orb.hp <= 0                                 (damage)

Defeat: player.hp <= 0 → respawn at hub full HP, staged XP wiped (DQ sting).
"""
from __future__ import annotations

import random
from typing import Any, Callable, Dict, List, Optional

from core.systems import encounter_config as ec
from core.systems import encounter_resolver as er
from core.systems.actor import Orb, choose_intent, safe_fmt
from core.systems.encounter_engine import EncounterEngine
from core.systems.fingerprint_engine import FingerprintEngine
from core.systems.player_state import PlayerState
from core.systems import player_state as ps


# -- Spatial layout ----------------------------------------------------------
# UAT-1 keeps three one-shot tiles near the hub. These positions live here
# rather than in config because they're scenario-specific (hub arena), not
# part of the reusable primitive.

HUB_SPAWN = (0.0, -14.0)
TILE_CROSS_RADIUS = 1.5
TILE_POSITIONS = [
    ( 0.0, -11.0),
    ( 2.5,  -6.0),
    (-2.5,  -6.0),
]

# UAT-1 scout — what to spawn when a tile is crossed. Change this id to
# reuse the same machinery for a different encounter flavor.
DEFAULT_SCOUT_ID = "first_watcher"

LOG_WINDOW = 6   # how many recent log lines the snapshot carries


# -- Fingerprint priming -----------------------------------------------------

def _prime_fingerprint() -> FingerprintEngine:
    """Seed the dimensions the Watcher queries so resonance clears 0.45
    for a fresh monk. This is the hub-arrival ritual analog — future
    progression lets cold monks build fingerprint organically."""
    fp = FingerprintEngine()
    for _ in range(5):
        fp.record("observation_time", 0.9)
        fp.record("precision_score", 0.9)
    return fp


# -- Session -----------------------------------------------------------------

class EncounterSession:
    """Per-connection encounter state. Owns player + orb + engine."""

    def __init__(self, seed: int = 42, age: int = 45,
                 scout_id: str = DEFAULT_SCOUT_ID):
        self.scout_id = scout_id
        self.scout = ec.get_scout(scout_id)
        # mode = "dialog" | "action". Dialog scouts route through
        # resolve_dialog_action (stance-match parley, no HP loss). Action
        # scouts use the legacy combat resolver. Default "action" preserves
        # legacy behavior for any scout that predates the mode field.
        self.mode: str = self.scout.get("mode", "action")

        self.fingerprint = _prime_fingerprint()
        self.engine = EncounterEngine(
            fingerprint=self.fingerprint,
            ghost_blend={"SEEKER": 1.0},
            age=age,
        )
        self.player = PlayerState.new(
            name="Wanderer", seed=seed, max_hp=10)
        self.consumed_tiles: set[int] = set()
        self._rng_src = random.Random(seed)
        self._rng = random.Random(seed + 1)   # intent-pick rng (separate stream)
        self._roll = lambda size: self._rng_src.randint(1, size)

        self.orb: Optional[Orb] = None
        self.action_log: list[dict] = []
        self._last_outcome: Optional[dict] = None
        self.pending_flags: Dict[str, bool] = {}   # disadvantage_next / bonus_next_read
        self._last_player_action: Optional[str] = None
        self._last_player_save: Optional[str] = None
        self.advantage: str = "neutral"            # first_strike | ambush | neutral

        # World-level data that persists across encounters in this session.
        # flags: string keys → bool/int/str, written by set_flag effect,
        #        readable by future path matchers (not wired yet).
        # pending_followup: scout_id to swap into on the NEXT trigger,
        #        consumed once. Written by open_dialog_branch effect.
        self.flags: Dict[str, Any] = {}
        self.pending_followup: Optional[str] = None

        # Per-encounter stance history — each entry captures the semantic
        # result of one dialog verb: {verb, stance, save, stance_match,
        # progress_delta}. Read by _select_path at resolution. Reset when
        # a new encounter begins.
        self.stance_history: List[Dict[str, Any]] = []

    # -- Spatial trigger -----------------------------------------------------

    def on_camera(self, cam_x: float, cam_y: float) -> Optional[dict]:
        """Check for tile crossing. Returns trigger dict or None.

        Skipped when: encounter already active, cooldown in effect, or every
        tile consumed. The nearest unconsumed tile within radius triggers.
        """
        if self.engine.active_encounter is not None:
            return None
        if self.engine.on_cooldown:
            return None

        nearest_idx = -1
        nearest_d2 = TILE_CROSS_RADIUS ** 2
        for i, (tx, ty) in enumerate(TILE_POSITIONS):
            if i in self.consumed_tiles:
                continue
            d2 = (cam_x - tx) ** 2 + (cam_y - ty) ** 2
            if d2 <= nearest_d2:
                nearest_d2 = d2
                nearest_idx = i

        if nearest_idx < 0:
            return None

        self._consume_pending_followup()
        self.stance_history = []
        self.orb = Orb.from_config(self.scout["actor"])
        entity = {
            "id":   f"{self.scout_id}#{nearest_idx}",
            "kind": self.orb.name,
            "tags": self.orb.tags,
        }
        worth = self.engine.begin(entity)
        self._active_tile_idx = nearest_idx
        self.action_log = []
        self.pending_flags = {}
        self._last_player_action = None
        self._last_player_save = None

        if not worth:
            # Silence — the orb is real but the fingerprint doesn't speak
            # to it. One-shot tile still consumed.
            self.consumed_tiles.add(nearest_idx)
            self.engine.active_encounter = None
            self.orb = None
            return {"triggered": False, "reason": "silence"}

        # Pre-queue the orb's first intent so the telegraph shows before the
        # player moves. DQ-style stakes: "a Watcher coils..." is visible
        # before you pick your action.
        name, spec = choose_intent(
            self.orb, None, None, self._rng, mode=self.mode)
        self.orb.current_intent = (name, spec)

        return {
            "triggered": True,
            "tile_idx":  nearest_idx,
            "resonance": self.engine.active_encounter["resonance"],
            "tags":      self.orb.tags,
        }

    # -- Action input --------------------------------------------------------

    def on_orb_contact(self, actor_id: str, advantage: str,
                       orb_id: str = "", hp_bonus: int = 0) -> dict:
        """Begin an encounter from a roaming-orb contact event.

        advantage ∈ {"first_strike", "ambush", "neutral"}:
            first_strike — player caught orb from behind; orb skips first turn
            ambush       — orb caught player from behind; player skips first turn
            neutral      — head-on, normal sequencing

        Returns same shape as the legacy on_camera trigger. brain_server
        is responsible for removing the orb from the roaming pool after
        this call returns {triggered: True}.
        """
        if self.engine.active_encounter is not None:
            return {"triggered": False, "reason": "already_active"}
        if self.engine.on_cooldown:
            return {"triggered": False, "reason": "cooldown"}

        self._consume_pending_followup()
        self.stance_history = []
        # Build orb from its configured actor id (which came from the
        # roaming agent, sourced from kind_config / encounter_config).
        self.orb = Orb.from_config(actor_id)
        # Apply procedural HP variant — one base actor, many "species."
        if hp_bonus != 0:
            self.orb.max_hp = max(1, self.orb.max_hp + hp_bonus)
            self.orb.hp = self.orb.max_hp
        entity = {
            "id":   orb_id or f"contact#{actor_id}",
            "kind": self.orb.name,
            "tags": self.orb.tags,
        }
        worth = self.engine.begin(entity)
        self._active_tile_idx = -1   # contact trigger doesn't use tiles
        self.action_log = []
        self.pending_flags = {}
        self._last_player_action = None
        self._last_player_save = None

        if not worth:
            self.engine.active_encounter = None
            self.orb = None
            return {"triggered": False, "reason": "silence"}

        # Apply advantage — Tartarus rule:
        #   first_strike: orb loses its first turn (skip orb turn once)
        #   ambush:       player's first save is at disadvantage
        #   neutral:      no modifier
        self.advantage = advantage
        if advantage == "ambush":
            self.pending_flags["disadvantage_next"] = True

        # Pre-queue the orb's first intent for telegraph.
        name, spec = choose_intent(
            self.orb, None, None, self._rng, mode=self.mode)
        self.orb.current_intent = (name, spec)

        return {
            "triggered": True,
            "actor_id":  actor_id,
            "advantage": advantage,
            "resonance": self.engine.active_encounter["resonance"],
            "tags":      self.orb.tags,
        }

    def on_action(self, action: str) -> dict:
        """Resolve one player action, then (if encounter alive) orb takes a turn.
        Auto-finalizes on resolved/defeated outcomes."""

        # Apply disadvantage to the next save (consumed on use).
        roll_fn = self._roll
        if self.pending_flags.get("disadvantage_next"):
            roll_fn = self._disadvantage_roll_factory()
            self.pending_flags["disadvantage_next"] = False

        if self.mode == "dialog":
            orb_posture = ""
            if self.orb is not None and self.orb.current_intent is not None:
                _, cur_spec = self.orb.current_intent
                orb_posture = cur_spec.get("posture", "")
            self.player, out = er.resolve_dialog_action(
                self.engine, self.player, action, orb_posture, roll_fn)
            # Log stance outcome for path matching at resolution.
            self.stance_history.append({
                "verb":             action,
                "stance":           out.get("stance"),
                "save":             out.get("save"),
                "stance_match":     out.get("stance_match"),
                "progress_delta":   out.get("progress_delta", 0),
            })
        else:
            self.player, out = er.resolve_action(
                self.engine, self.player, action, roll_fn)

        # Bonus read — THINK/OBSERVE pass on a reveal flag bumps progress once.
        if (self.pending_flags.get("bonus_next_read")
                and action in ("THINK", "OBSERVE")
                and out.get("save") == "pass"):
            self.engine.active_encounter["net_passes"] += 1
            out["net_passes"] = self.engine.active_encounter["net_passes"]
            self.pending_flags["bonus_next_read"] = False

        # Damage orb on successful ACT (primitive's combat axis).
        if action == "ACT" and out.get("save") == "pass" and self.orb is not None:
            self.orb.take_damage(1)
            out["orb_hp_after"] = self.orb.hp

        # Log player action with flavor template.
        flavor_key = f"{action}_{out.get('save')}" if out.get("save") else action
        flavor = self.scout.get("flavor", {}).get(flavor_key, "")
        log_entry = self._build_log_entry(action, out, flavor)
        self.action_log.append(log_entry)
        out["log_entry"] = log_entry

        # Recompute resolution — orb HP=0 is a fresh victory path.
        if (out["resolution"] == "pending"
                and self.orb is not None and self.orb.is_defeated()):
            out["resolution"] = "resolved"

        # Orb turn — skipped once if player earned first_strike.
        skip_orb_turn = self.advantage == "first_strike"
        if skip_orb_turn:
            self.advantage = "neutral"   # consumed
            self.action_log.append({
                "action": "—", "save": None,
                "text": "The %s is unaware — it yields the opening." % (
                    self.orb.name if self.orb else "orb"),
                "resolution": "pending",
            })

        if (not skip_orb_turn
                and out["resolution"] == "pending"
                and self.engine.active_encounter is not None
                and self.orb is not None
                and not self.orb.is_defeated()):
            orb_log = self._run_orb_turn(action, out.get("save"))
            out["orb_turn"] = orb_log
            self.action_log.append({
                "action":    f"[{self.orb.name}]",
                "save":      None,
                "text":      orb_log.get("narration", ""),
                "intent":    orb_log.get("intent"),
                "resolution": "pending",
            })

            # Player HP may have just dropped to zero from orb strike
            if self.player.hp <= 0:
                out["resolution"] = "defeated"

        # Track context for the NEXT orb intent pick.
        self._last_player_action = action
        self._last_player_save = out.get("save")

        # Finalize on resolved/defeated.
        if out["resolution"] == "resolved":
            final = self.engine.resolve(outcome="resolved")
            out["xp_staged"] = final["xp_staged"]
            out["consumed_tile"] = self._finalize_tile()
            # Match a path against stance history, apply its effects, and
            # use its ceremony text if provided. Dialog scouts carry paths;
            # action scouts fall through to the default victory ceremony.
            path_name, path_cfg = self._select_path()
            ceremony_override = (path_cfg or {}).get("ceremony")
            self._last_outcome = self._ceremony_outcome(
                "victory", final, text_override=ceremony_override)
            self._last_outcome["path"] = path_name
            out["path"] = path_name
            if path_cfg:
                self._apply_effects(path_cfg.get("effects", []))
            self.action_log.append({
                "action": "—",
                "text":   self._last_outcome["ceremony_text"],
                "resolution": "resolved",
            })
        elif out["resolution"] == "defeated":
            final = self.engine.resolve(outcome="defeated")
            out["xp_staged"] = final["xp_staged"]
            # Defeat sting: wipe staged XP.
            self.engine.staged_xp = 0.0
            self.player = self.player._replace(hp=self.player.max_hp)
            out["consumed_tile"] = self._finalize_tile()
            self._last_outcome = self._ceremony_outcome("defeat", final)
            self.action_log.append({
                "action": "—",
                "text":   self._last_outcome["ceremony_text"],
                "resolution": "defeated",
            })

        return out

    # Legacy alias
    on_verb = on_action

    def on_portal(self) -> dict:
        if self.engine.active_encounter is not None:
            out = self.engine.resolve(outcome="portal_exit")
            self._finalize_tile()
            self._last_outcome = self._ceremony_outcome("fled", out)
            return out
        return {"outcome": "no_encounter"}

    def on_flee(self) -> dict:
        if self.engine.active_encounter is not None:
            out = self.engine.resolve(outcome="fled")
            self._finalize_tile()
            self._last_outcome = self._ceremony_outcome("fled", out)
            return out
        return {"outcome": "no_encounter"}

    def on_hub_arrival(self) -> dict:
        return self.engine.consolidate(reason="rest")

    # -- Snapshot ------------------------------------------------------------

    def snapshot(self) -> dict:
        active_block = None
        if self.engine.active_encounter is not None and self.orb is not None:
            tile_idx = getattr(self, "_active_tile_idx", -1)
            tx, ty = (TILE_POSITIONS[tile_idx]
                      if 0 <= tile_idx < len(TILE_POSITIONS) else (0.0, 0.0))

            # Telegraph the currently-chosen intent (if one is queued).
            telegraph = ""
            posture = ""
            if self.orb.current_intent is not None:
                _name, spec = self.orb.current_intent
                telegraph = safe_fmt(spec.get("telegraph", ""), actor=self.orb.name)
                posture = spec.get("posture", "")

            active_block = {
                "orb": {
                    "name":       self.orb.name,
                    "hp":         self.orb.hp,
                    "max_hp":     self.orb.max_hp,
                    "phase":      self.orb.phase(),
                    "posture":    posture,
                    "segments":   self.orb.segments,
                    "visual":     self.orb.visual,
                },
                "tile":         [tx, ty],
                "mode":         self.mode,
                "verbs":        self._active_verbs(),
                "resonance":    self.engine.active_encounter["resonance"],
                "net_passes":   self.engine.active_encounter.get("net_passes", 0),
                "threshold":    er.RESOLUTION_THRESHOLD,
                "action_used":  self.engine.active_encounter.get("action_used"),
                "intent_telegraph": telegraph,
                "log":          self.action_log[-LOG_WINDOW:],
                "ceremony":     dict(self.scout.get("ceremony", {})),
                "pending_flags": dict(self.pending_flags),
            }

        return {
            "active": active_block,
            "tiles": [
                {"x": tx, "y": ty, "consumed": i in self.consumed_tiles}
                for i, (tx, ty) in enumerate(TILE_POSITIONS)
            ],
            "hub_spawn": list(HUB_SPAWN),
            "player": {
                "hp":       self.player.hp,
                "max_hp":   self.player.max_hp,
                "str_save": self.player.str_save,
                "dex_save": self.player.dex_save,
                "wil_save": self.player.wil_save,
            },
            "progression": {
                "depth":       round(self.engine.depth, 4),
                "staged_xp":   round(self.engine.staged_xp, 4),
                "abilities":   list(self.engine.abilities),
                "on_cooldown": self.engine.on_cooldown,
            },
            "last_outcome": self._last_outcome,
        }

    # -- Internals -----------------------------------------------------------

    def _run_orb_turn(self, last_action: str, last_save: Optional[str]) -> dict:
        """Execute the pre-queued intent, then queue the NEXT intent so the
        telegraph shows in the next snapshot. Applies non-damage effects."""
        # current_intent was pre-queued (encounter start, or previous orb turn).
        # If somehow missing, pick one now as fallback.
        if self.orb.current_intent is None:
            name, spec = choose_intent(
                self.orb, last_action, last_save, self._rng, mode=self.mode)
            self.orb.current_intent = (name, spec)

        self.player, orb_log = self.orb.take_turn(self.player, self._roll)

        # Apply non-damage effects to session state.
        if orb_log["effect"] == "progress_delta":
            if self.engine.active_encounter is not None:
                self.engine.active_encounter["net_passes"] = max(
                    0,
                    self.engine.active_encounter.get("net_passes", 0)
                    + int(orb_log.get("value", 0)))
        elif orb_log["effect"] == "disadvantage_next":
            self.pending_flags["disadvantage_next"] = True
        elif orb_log["effect"] == "bonus_next_read":
            self.pending_flags["bonus_next_read"] = True

        # Queue next intent so the next snapshot carries the new telegraph.
        nxt_name, nxt_spec = choose_intent(
            self.orb, last_action, last_save, self._rng, mode=self.mode)
        self.orb.current_intent = (nxt_name, nxt_spec)

        return orb_log

    def _disadvantage_roll_factory(self) -> Callable[[int], int]:
        """Return a roll_fn that, for d20 saves, takes the worse of two d20s.
        Non-d20 rolls pass through unchanged. Uses self._roll so tests that
        override _roll with a deterministic sequence still work — the
        factory consumes two rolls from the underlying stream per d20."""
        def roll(size: int) -> int:
            if size == 20:
                a = self._roll(20)
                b = self._roll(20)
                return max(a, b)   # higher = worse (Cairn: roll ≤ stat = pass)
            return self._roll(size)
        return roll

    def _build_log_entry(self, action: str, out: dict, flavor: str) -> dict:
        save = out.get("save")
        roll = int(out.get("roll", 0))
        stat = int(out.get("stat", 0))
        hp_d = int(out.get("hp_delta", 0))
        net = int(out.get("net_passes", 0))

        # Concise technical tail: save result + roll/stat + effect.
        tail_bits = []
        if save in ("pass", "fail"):
            tail_bits.append(f"{save.upper()} {roll}/{stat}")
        if hp_d < 0:
            tail_bits.append(f"HP {hp_d}")
        elif save == "pass" and net > 0:
            tail_bits.append(f"progress {net}/3")
        tail = "  ".join(tail_bits)

        body = flavor or action
        text = f"{body}  ({tail})" if tail else body

        return {
            "action":     action,
            "save":       save,
            "roll":       roll,
            "stat":       stat,
            "hp_delta":   hp_d,
            "net_passes": net,
            "resolution": out.get("resolution", "pending"),
            "text":       text,
            "flavor":     flavor,
        }

    def _ceremony_outcome(self, kind: str, final: dict,
                          text_override: Optional[str] = None) -> dict:
        if text_override:
            text = text_override
        else:
            text = self.scout.get("ceremony", {}).get(kind, kind.upper())
        return {
            "ceremony":      kind,
            "ceremony_text": text,
            "xp_staged":     final.get("xp_staged", 0.0),
            "outcome":       final.get("outcome", kind),
        }

    # -- Path matching -------------------------------------------------------

    def _select_path(self) -> tuple[str, Optional[dict]]:
        """Match the stance_history against scout.paths. First path whose
        `when` clause matches wins. If none match, fall back to
        scout.default_path. Returns (path_name, path_cfg) or ('default', None)
        when the scout declares no paths."""
        paths = self.scout.get("paths") or {}
        if not paths:
            return ("default", None)

        for name, cfg in paths.items():
            if name.startswith("_"):
                continue
            if self._path_matches(cfg.get("when", {})):
                return (name, cfg)

        fallback = self.scout.get("default_path")
        if fallback and fallback in paths:
            return (fallback, paths[fallback])
        # No match, no default — take whichever is first, stable.
        first = next((k for k in paths.keys() if not k.startswith("_")), None)
        return (first or "default", paths.get(first) if first else None)

    def _path_matches(self, when: dict) -> bool:
        """Return True if the current stance_history satisfies the `when`
        clause. Supported keys (AND-combined):
            breaks_min     — int: at least N stance_match == 'breaks'
            reads_min      — int: at least N stance_match == 'reads'
            passes_min     — int: at least N save == 'pass'
            stance_count   — {stance: N, ...}: at least N passed instances
                             of each listed stance
            flag           — str: self.flags[str] must be truthy
            not_flag       — str: self.flags[str] must be falsy/absent
        """
        if not when:
            return True

        passes   = [h for h in self.stance_history if h.get("save") == "pass"]
        breaks_n = sum(1 for h in passes if h.get("stance_match") == "breaks")
        reads_n  = sum(1 for h in passes if h.get("stance_match") == "reads")

        if "breaks_min" in when and breaks_n < int(when["breaks_min"]):
            return False
        if "reads_min"  in when and reads_n  < int(when["reads_min"]):
            return False
        if "passes_min" in when and len(passes) < int(when["passes_min"]):
            return False
        if "stance_count" in when:
            wanted: dict = when["stance_count"]
            for stance, need in wanted.items():
                got = sum(1 for h in passes if h.get("stance") == stance)
                if got < int(need):
                    return False
        if "flag" in when and not self.flags.get(when["flag"]):
            return False
        if "not_flag" in when and self.flags.get(when["not_flag"]):
            return False
        return True

    # -- Effect dispatch -----------------------------------------------------

    # Per-effect param schema. Each entry maps {param_name: (type, required)}.
    # Schema serves three jobs:
    #   1) Replaces the whitelist — keys are the known effect names.
    #   2) Validates spec params at dispatch time — wrong types and missing
    #      required keys raise BEFORE handler runs. Catches config typos
    #      (e.g. "amounnt") that would otherwise no-op silently or KeyError
    #      deep in the handler.
    #   3) Documents the contract of every effect in one place.
    # `object` matches any type — used when the param accepts mixed values
    # (e.g. set_flag.value can be bool/int/str).
    _EFFECT_SCHEMAS: dict[str, dict[str, tuple]] = {
        "heal_player": {"amount": (int, False)},
        "give_item": {"name": (str, True), "slot_cost": (int, False)},
        "take_item": {"name": (str, True)},
        "set_flag": {"name": (str, True), "value": (object, False)},
        "trigger_rest": {},
        "open_dialog_branch": {"scout_id": (str, True)},
    }

    def _validate_effect_spec(self, name: str, spec: dict) -> None:
        schema = self._EFFECT_SCHEMAS[name]
        for key, (expected_type, required) in schema.items():
            if key not in spec:
                if required:
                    raise ValueError(
                        f"effect {name!r}: missing required param {key!r}")
                continue
            val = spec[key]
            if expected_type is not object and not isinstance(val, expected_type):
                raise ValueError(
                    f"effect {name!r}: param {key!r} expected "
                    f"{expected_type.__name__}, got {type(val).__name__}")
        # "type" is the dispatcher key, always allowed alongside schema keys.
        extras = set(spec) - set(schema) - {"type"}
        if extras:
            raise ValueError(
                f"effect {name!r}: unknown params {sorted(extras)}; "
                f"known: {sorted(schema)}")

    def _apply_effects(self, effects: list) -> None:
        for spec in effects or []:
            name = spec.get("type", "")
            if name not in self._EFFECT_SCHEMAS:
                raise ValueError(
                    f"unknown effect {name!r}; known: "
                    f"{sorted(self._EFFECT_SCHEMAS)}")
            self._validate_effect_spec(name, spec)
            handler = getattr(self, f"_fx_{name}")
            handler(spec)

    def _fx_heal_player(self, spec: dict) -> None:
        amt = int(spec.get("amount", 0))
        self.player = ps.heal(self.player, amt)

    def _fx_give_item(self, spec: dict) -> None:
        from core.systems.player_state import Item
        name = str(spec["name"])
        cost = int(spec.get("slot_cost", 1))
        self.player = ps.add_item(self.player, Item(name=name, slot_cost=cost))

    def _fx_take_item(self, spec: dict) -> None:
        from core.systems.player_state import Item
        name = str(spec["name"])
        # remove_item matches on (name, slot_cost) tuple equality; use the
        # first matching slot_cost we find in inventory to avoid forcing
        # callers to know the stored slot_cost.
        for it in self.player.inventory:
            if it.name == name:
                self.player = ps.remove_item(self.player, it)
                return
        # Silently absent — take_item of a missing item is a no-op, not
        # an error. Callers who care should gate with a flag first.

    def _fx_set_flag(self, spec: dict) -> None:
        self.flags[str(spec["name"])] = spec.get("value", True)

    def _fx_trigger_rest(self, _spec: dict) -> None:
        self.engine.consolidate(reason="rest")

    def _fx_open_dialog_branch(self, spec: dict) -> None:
        self.pending_followup = str(spec["scout_id"])

    # -- Followup swap -------------------------------------------------------

    def _consume_pending_followup(self) -> None:
        """If open_dialog_branch queued a scout swap, apply it now and
        clear the queue. Fingerprint and engine stay — only the scout
        reference and mode move."""
        if not self.pending_followup:
            return
        target = self.pending_followup
        self.pending_followup = None
        self.switch_scout(target)

    def switch_scout(self, scout_id: str) -> None:
        """Bind the session to a new scout mid-expedition. Used by
        open_dialog_branch to chain encounters without tearing the session
        down."""
        self.scout_id = scout_id
        self.scout = ec.get_scout(scout_id)
        self.mode = self.scout.get("mode", "action")

    def _active_verbs(self) -> list[str]:
        """Verbs the HUD should render for the current mode. Dialog mode
        pulls from config; action mode returns the legacy combat set."""
        if self.mode == "dialog":
            return ec.dialog_verb_names()
        return ["THINK", "ACT", "MOVE", "DEFEND", "OBSERVE", "CRAFT", "TOOLS"]

    def _finalize_tile(self) -> Optional[int]:
        idx = getattr(self, "_active_tile_idx", -1)
        if 0 <= idx < len(TILE_POSITIONS):
            self.consumed_tiles.add(idx)
            self._active_tile_idx = -1
            self.orb = None
            return idx
        return None
