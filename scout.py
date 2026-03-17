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
        hardware_status: dict = None,
    ):
        self.env = environmental_data
        self.player = player_snapshot
        self.heat = heat
        self.tactic = tactic
        self.hardware = hardware_status or {"sensor_array": True}

    def resolve(self) -> ScoutResult:
        if self.heat >= 100:
            raise ThermalError(
                "CRITICAL OVERHEAT: System lockout active. Vent thermal load."
            )

        # 1. Hardware & Base Hazard
        sensors_nominal = self.hardware.get("sensor_array", True)
        hazard_rating = 40.0
        condition = self.env.get("condition", "Clear")
        city = self.env.get("city", "Unknown")

        if not sensors_nominal:
            hazard_rating += 20.0
            condition = "SENSOR FAILURE"
        elif condition in ["Rain", "Snow", "Extreme", "Overcast"]:
            hazard_rating += 15.0

        # 2. Tactical Adjustments
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

        # 5. Resolution Roll
        roll = random.randint(1, 100) + power_score
        success = roll >= final_hazard
        system_damage = False

        # 6. Outcome Calculation
        prefix = f"[{self.tactic.upper()}]"
        if not sensors_nominal:
            prefix += " [BLIND SCAN]"

        if success:
            delta = 100.0 * mod["reward"]
            xp_reward = int((10 + (final_hazard / 5)) * mod["reward"])
            heat_generated = int(random.randint(5, 12) * mod["heat"])
            msg = f"{prefix} Uplink stable in {city}. Fragments secured."
        else:
            delta = -50.0
            xp_reward = 2
            heat_generated = int(random.randint(15, 25) * mod["heat"])
            # UPDATED: Added city name to the failure message
            msg = f"{prefix} Signal lost in {city}. Thermal surge detected: {condition} interference."

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