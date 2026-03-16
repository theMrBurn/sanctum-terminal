import random
from dataclasses import dataclass


@dataclass
class ScoutResult:
    success: bool
    description: str
    aegis_delta: float
    xp_gain: int


class ScoutEngine:
    def __init__(self, environmental_data: dict, player_snapshot: dict):
        self.env = environmental_data
        self.player = player_snapshot

    def resolve(self) -> ScoutResult:
        # 1. Base Difficulty (Derived from Passive Weather)
        # Bad weather = higher difficulty
        difficulty_floor = 40
        if self.env.get("condition") in ["Rain", "Snow", "Extreme"]:
            difficulty_floor += 20

        # 2. Player Power (Derived from Active Aegis)
        # More Aegis = better odds, but more at risk
        power_score = min(self.player["aegis"] / 1000, 50)

        # 3. The Roll
        roll = random.randint(1, 100) + power_score
        success = roll >= difficulty_floor

        if success:
            delta = 100.0  # Reward for success
            msg = (
                f"Scout successful in {self.env['city']}. Recovered digital fragments."
            )
        else:
            delta = -50.0  # Cost of failure
            msg = f"Scout compromised by {self.env['condition']}. Emergency extraction initiated."

        return ScoutResult(
            success=success,
            description=msg,
            aegis_delta=delta,
            xp_gain=10 if success else 2,
        )
