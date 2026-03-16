import random
from dataclasses import dataclass


class ThermalError(Exception):
    """Custom exception raised when heat exceeds the safety threshold."""

    pass


@dataclass
class ScoutResult:
    success: bool
    description: str
    aegis_delta: float
    xp_gain: int
    heat_gain: int
    system_damage: bool = False


class ScoutEngine:
    def __init__(
        self,
        environmental_data: dict,
        player_snapshot: dict,
        heat: int = 0,
        tactic: str = "standard",
    ):
        self.env = environmental_data
        self.player = player_snapshot
        self.heat = heat
        self.tactic = tactic

    def resolve(self) -> ScoutResult:
        if self.heat >= 100:
            raise ThermalError(
                "CRITICAL OVERHEAT: System lockout active. Vent thermal load."
            )

        # 1. Base Hazard Rating
        hazard_rating = 40.0
        condition = self.env.get("condition", "Clear")
        if condition in ["Rain", "Snow", "Extreme", "Overcast"]:
            hazard_rating += 15.0

        # 2. Tactical Adjustments
        # Stealth: -10% Hazard, 0.7x Reward, 0.5x Heat
        # Aggressive: +15% Hazard, 1.5x Reward, 2.0x Heat
        modifiers = {
            "stealth": {"hazard": -10.0, "reward": 0.7, "heat": 0.5},
            "standard": {"hazard": 0.0, "reward": 1.0, "heat": 1.0},
            "aggressive": {"hazard": 15.0, "reward": 1.5, "heat": 2.0},
        }
        mod = modifiers.get(self.tactic, modifiers["standard"])

        # 3. Final Hazard Calculation
        thermal_drag = self.heat / 2.0
        final_hazard = hazard_rating + thermal_drag + mod["hazard"]

        # 4. Player Power
        power_score = min(self.player.get("aegis", 0) / 1000, 30.0)

        # 5. The Resolution Roll
        roll = random.randint(1, 100) + power_score
        success = roll >= final_hazard

        system_damage = False

        # 6. Outcome Calculation
        if success:
            delta = 100.0 * mod["reward"]
            xp_reward = int((10 + (final_hazard / 5)) * mod["reward"])
            heat_generated = int(random.randint(5, 12) * mod["heat"])
            msg = f"[{self.tactic.upper()}] Uplink stable in {self.env.get('city', 'Unknown')}. Fragments secured."
        else:
            delta = -50.0
            xp_reward = 2
            heat_generated = int(random.randint(15, 25) * mod["heat"])
            msg = f"[{self.tactic.upper()}] Signal lost. Thermal surge detected: {condition} interference."

            # High-Heat Damage Check
            if self.heat > 80 and random.random() < 0.25:
                system_damage = True
                msg += " CRITICAL: Hardware component desoldered."

        return ScoutResult(
            success=success,
            description=msg,
            aegis_delta=delta,
            xp_gain=xp_reward,
            heat_gain=heat_generated,
            system_damage=system_damage,
        )
