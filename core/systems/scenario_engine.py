"""
core/systems/scenario_engine.py

ScenarioEngine -- five quest types as instantiable templates.

Every scenario is a unique task primitive. When the full ledger is built,
each scenario gets a provenance hash (Yellow Sign) -- created once,
recorded permanently, traceable across playthroughs and seeds.

Scenario types:
    fetch   -- acquire target object, return to position
    escort  -- keep entity within radius until destination
    hunt    -- find and interact with hidden/marked target
    key     -- acquire object A to unlock/enable object B
    switch  -- activate N triggers (ordered or unordered)

State machine:
    PENDING -> ACTIVE -> COMPLETE
                      -> FAILED

win_fn: callable returning True when scenario conditions are met.
        tick() checks this every frame for ACTIVE scenarios.
        switch type manages its own trigger tracking.
        All other types supply their own win_fn at create time.

on_complete: callback fired with scenario_id when state -> COMPLETE.
             QuestEngine, HUD, FingerprintEngine all subscribe here.

Provenance hash: every scenario gets one at creation.
                 Hash = SHA256(type + params + seed + timestamp).
                 Immutable. The ledger remembers even if you forget.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Set


# -- Constants -----------------------------------------------------------------

SCENARIO_TYPES = {"fetch", "escort", "hunt", "key", "switch"}


# -- State ---------------------------------------------------------------------

class ScenarioState(Enum):
    PENDING  = auto()
    ACTIVE   = auto()
    COMPLETE = auto()
    FAILED   = auto()


# -- Scenario record -----------------------------------------------------------

class _Scenario:
    """Internal record for one scenario instance."""

    def __init__(
        self,
        scenario_id:  str,
        scenario_type: str,
        params:       dict,
        win_fn:       Optional[Callable],
        on_complete:  Optional[Callable],
        provenance_hash: str,
    ):
        self.id              = scenario_id
        self.type            = scenario_type
        self.params          = params
        self.win_fn          = win_fn
        self.on_complete     = on_complete or (lambda sid: None)
        self.provenance_hash = provenance_hash
        self.state           = ScenarioState.PENDING

        # switch type: track which triggers have fired
        self._triggered: Set[str] = set()
        self._trigger_ids: List[str] = list(params.get("trigger_ids", []))
        self._ordered: bool = params.get("ordered", False)
        self._trigger_sequence: List[str] = []


# -- ScenarioEngine ------------------------------------------------------------

class ScenarioEngine:
    """
    Manages scenario lifecycle: create, activate, tick, complete, fail.

    Scenarios are task primitives. The engine is the ledger.
    Every scenario created is hashed and recorded -- immutable provenance.
    ScenarioRunner will drive this headlessly for difficulty tuning.
    """

    def __init__(self, seed: str = "BURN"):
        self._seed      = seed
        self._scenarios: Dict[str, _Scenario] = {}

    # -- Create ----------------------------------------------------------------

    def create(
        self,
        scenario_type: str,
        params:        dict,
        win_fn:        Optional[Callable] = None,
        on_complete:   Optional[Callable] = None,
    ) -> str:
        """
        Instantiate a scenario from a type and params dict.
        Returns scenario_id (UUID).
        Raises ValueError for unknown types.

        Provenance hash encodes type + params + seed + timestamp.
        Immutable. Even procedurally generated scenarios are unique.
        """
        if scenario_type not in SCENARIO_TYPES:
            raise ValueError(
                f"Unknown scenario type: {scenario_type!r}. "
                f"Valid: {sorted(SCENARIO_TYPES)}"
            )

        scenario_id      = str(uuid.uuid4())
        provenance_hash  = self._hash(scenario_type, params, scenario_id)

        s = _Scenario(
            scenario_id      = scenario_id,
            scenario_type    = scenario_type,
            params           = dict(params),
            win_fn           = win_fn,
            on_complete      = on_complete,
            provenance_hash  = provenance_hash,
        )
        self._scenarios[scenario_id] = s
        return scenario_id

    # -- Lifecycle -------------------------------------------------------------

    def activate(self, scenario_id: str) -> None:
        """Move PENDING -> ACTIVE. No-op for other states."""
        s = self._scenarios.get(scenario_id)
        if s and s.state is ScenarioState.PENDING:
            s.state = ScenarioState.ACTIVE

    def complete(self, scenario_id: str) -> None:
        """Move ACTIVE -> COMPLETE. No-op if not ACTIVE."""
        s = self._scenarios.get(scenario_id)
        if s and s.state is ScenarioState.ACTIVE:
            s.state = ScenarioState.COMPLETE
            s.on_complete(scenario_id)

    def fail(self, scenario_id: str) -> None:
        """Move ACTIVE -> FAILED. No-op if not ACTIVE."""
        s = self._scenarios.get(scenario_id)
        if s and s.state is ScenarioState.ACTIVE:
            s.state = ScenarioState.FAILED

    # -- Tick ------------------------------------------------------------------

    def tick(self) -> None:
        """
        Check win conditions for all ACTIVE scenarios.
        Scenarios with win_fn: auto-complete when fn returns True.
        Switch scenarios: managed by trigger(), not win_fn.
        Call every frame from taskMgr or ScenarioRunner.
        """
        for s in self._scenarios.values():
            if s.state is not ScenarioState.ACTIVE:
                continue
            if s.win_fn is not None and s.win_fn():
                self.complete(s.id)

    # -- Switch trigger --------------------------------------------------------

    def trigger(self, scenario_id: str, trigger_id: str) -> None:
        """
        Fire a trigger for a switch-type scenario.
        Tracks which triggers have fired.
        Auto-completes when all triggers are satisfied.
        """
        s = self._scenarios.get(scenario_id)
        if not s or s.state is not ScenarioState.ACTIVE:
            return
        if s.type != "switch":
            return
        if trigger_id not in s._trigger_ids:
            return
        s._triggered.add(trigger_id)
        s._trigger_sequence.append(trigger_id)
        if set(s._trigger_ids) <= s._triggered:
            self.complete(scenario_id)

    # -- Query -----------------------------------------------------------------

    def get_state(self, scenario_id: str) -> Optional[ScenarioState]:
        """Current state, or None if scenario_id unknown."""
        s = self._scenarios.get(scenario_id)
        return s.state if s else None

    def get_objective(self, scenario_id: str) -> Optional[str]:
        """Human-readable objective string from params."""
        s = self._scenarios.get(scenario_id)
        return s.params.get("objective") if s else None

    def get_active(self) -> List[str]:
        """All ACTIVE scenario IDs."""
        return [sid for sid, s in self._scenarios.items()
                if s.state is ScenarioState.ACTIVE]

    def get_provenance(self, scenario_id: str) -> Optional[str]:
        """Provenance hash for scenario. The Yellow Sign."""
        s = self._scenarios.get(scenario_id)
        return s.provenance_hash if s else None

    def all_scenarios(self) -> List[dict]:
        """
        Full ledger snapshot -- all scenarios, all states.
        ScenarioRunner uses this for pass/fail reporting.
        """
        return [
            {
                "id":               s.id,
                "type":             s.type,
                "state":            s.state.name,
                "objective":        s.params.get("objective", ""),
                "provenance_hash":  s.provenance_hash,
            }
            for s in self._scenarios.values()
        ]

    # -- Provenance hash -------------------------------------------------------

    def _hash(self, scenario_type: str, params: dict, scenario_id: str) -> str:
        """
        SHA256(seed + type + params + id + timestamp).
        Immutable. Unique even for identical param sets run at different times.
        When the ledger persists to vault.db, this becomes the primary key.
        """
        payload = json.dumps({
            "seed":    self._seed,
            "type":    scenario_type,
            "params":  params,
            "id":      scenario_id,
            "ts":      time.time(),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
