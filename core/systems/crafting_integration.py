"""
core/systems/crafting_integration.py

Bridge 3: CraftingIntegration -- crafting connects to inventory and world.

Pulls inputs from inventory, runs CraftingEngine, puts result back.
Optionally checks if the craft result completes an active key scenario.
"""

from __future__ import annotations

from typing import Optional


class CraftingIntegration:
    """
    Connects CraftingEngine to Inventory and ScenarioEngine.

    Parameters
    ----------
    crafting_engine  : CraftingEngine instance
    inventory        : Inventory instance
    scenario_engine  : ScenarioEngine instance (optional, for key scenario completion)
    """

    def __init__(self, crafting_engine, inventory, scenario_engine=None):
        self.engine = crafting_engine
        self.inventory = inventory
        self._se = scenario_engine

    def craft(self, input_a: str, input_b: str) -> Optional[dict]:
        """
        Craft from two inventory items.
        Removes inputs, adds result, checks scenario completion.
        Returns result dict or None if inputs not in inventory.
        """
        # Verify both items exist in inventory
        item_a = self.inventory.get(input_a)
        item_b = self.inventory.get(input_b)
        if item_a is None or item_b is None:
            return None

        # Execute craft
        result = self.engine.craft(input_a, input_b)

        # Remove inputs from inventory
        self.inventory.drop(input_a)
        self.inventory.drop(input_b)

        # Add result to inventory
        result_obj = {
            "id": result["name"],
            "weight": result.get("weight", 0.5),
            "description": result.get("description", ""),
            "ability": result.get("ability", ""),
            "provenance_hash": result.get("provenance_hash", ""),
        }
        self.inventory.pickup(result_obj)

        # Check if this completes an active key scenario
        if self._se:
            self._check_scenario_completion(result)

        return result

    def can_craft(self, input_a: str, input_b: str) -> bool:
        """Check if both items are in inventory."""
        return (self.inventory.get(input_a) is not None and
                self.inventory.get(input_b) is not None)

    def _check_scenario_completion(self, result):
        """Complete any active key scenario whose target matches the craft result."""
        from core.systems.scenario_engine import ScenarioState
        for s in self._se.all_scenarios():
            if s["state"] != "ACTIVE":
                continue
            if s["type"] != "key":
                continue
            # Check if result name matches scenario target
            target = s.get("objective", "")
            result_name = result.get("name", "")
            # Also check target_id in the scenario's params
            sid = s["id"]
            scenario_obj = self._se._scenarios.get(sid)
            if scenario_obj:
                target_id = scenario_obj.params.get("target_id", "")
                if result_name == target_id or result_name.lower() == target_id.lower():
                    self._se.complete(sid)
