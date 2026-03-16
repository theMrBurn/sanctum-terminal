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
    system_damage: bool = False  # NEW: Defaults to False


class ScoutEngine:
    def __init__(self, environmental_data: dict, player_snapshot: dict, heat: int = 0):
        self.env = environmental_data
        self.player = player_snapshot
        self.heat = heat

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

        # 2. Thermal Drag
        thermal_drag = self.heat / 2.0
        final_hazard = hazard_rating + thermal_drag

        # 3. Player Power
        power_score = min(self.player.get("aegis", 0) / 1000, 30.0)

        # 4. The Resolution Roll
        roll = random.randint(1, 100) + power_score
        success = roll >= final_hazard

        system_damage = False

        # 5. Outcome Calculation
        if success:
            delta = 100.0
            xp_reward = int(10 + (final_hazard / 5))
            heat_generated = random.randint(5, 12)
            msg = f"Uplink stable in {self.env.get('city', 'Unknown')}. Fragments secured."
        else:
            delta = -50.0
            xp_reward = 2
            heat_generated = random.randint(15, 25)
            msg = f"Signal lost. Thermal surge detected: {condition} interference too high."

            # NEW: High-Heat Damage Check
            # If failing at >80% heat, 25% chance of system damage
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
