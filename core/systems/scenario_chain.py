"""
core/systems/scenario_chain.py

Bridge 2: ScenarioChain -- scenarios link into sequences.

on_complete of step N activates step N+1.
Supports linear chains (mystic quest), cyclical (garden), branching (future).
The campaign JSON defines the chain. The engine executes it.
"""

from __future__ import annotations

from typing import List, Optional


class ScenarioChain:
    """
    Links scenarios into an ordered sequence.

    Parameters
    ----------
    scenario_engine : ScenarioEngine instance
    """

    def __init__(self, scenario_engine):
        self._se = scenario_engine
        self._ids = []          # ordered list of scenario IDs
        self._step = 0          # current active step index
        self._complete = False
        self._on_chain_complete = None

    def create(
        self,
        steps: List[dict],
        on_chain_complete=None,
    ) -> List[str]:
        """
        Create a chain of scenarios from step definitions.
        Each step: {"type": str, "params": dict, "win_fn": optional callable}

        First step activates immediately. Subsequent steps activate on completion.
        Returns list of scenario IDs.
        """
        self._on_chain_complete = on_chain_complete
        self._ids = []
        self._step = 0
        self._complete = False

        for i, step in enumerate(steps):
            # Capture index for closure
            idx = i
            def make_callback(step_idx):
                def on_complete(sid):
                    self._on_step_complete(step_idx)
                return on_complete

            sid = self._se.create(
                scenario_type=step["type"],
                params=step.get("params", {}),
                win_fn=step.get("win_fn"),
                on_complete=make_callback(idx),
            )
            self._ids.append(sid)

        # Activate first step
        if self._ids:
            self._se.activate(self._ids[0])

        return self._ids

    def _on_step_complete(self, step_idx: int):
        """Called when a step completes. Activates the next step."""
        next_idx = step_idx + 1
        if next_idx < len(self._ids):
            self._step = next_idx
            self._se.activate(self._ids[next_idx])
        else:
            self._step = len(self._ids)
            self._complete = True
            if self._on_chain_complete:
                self._on_chain_complete(self._ids)

    def current_step(self) -> int:
        """Index of the currently active step."""
        return self._step

    def current_id(self) -> Optional[str]:
        """Scenario ID of the current step, or None if complete."""
        if self._step < len(self._ids):
            return self._ids[self._step]
        return None

    def is_complete(self) -> bool:
        """True when all steps are complete."""
        return self._complete

    def progress(self) -> dict:
        """Chain progress report."""
        return {
            "total_steps": len(self._ids),
            "current_step": self._step,
            "complete": self._complete,
            "ids": list(self._ids),
        }
