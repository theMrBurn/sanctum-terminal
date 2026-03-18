import numpy as np
import pygame
import random
from dataclasses import dataclass
from typing import Dict, Optional

# --- DATA STRUCTURES ---


@dataclass
class ScoutResult:
    success: bool
    description: str
    aegis_delta: float
    xp_gain: int
    heat_gain: int
    system_damage: bool = False


class ThermalError(Exception):
    """Raised when system heat exceeds safety thresholds."""

    pass


# --- THE UNIFIED OBSERVER ---


class ObserverSystem:
    def __init__(self, config_manager, api_key: str = None):
        self.config = config_manager
        self.api_key = api_key

        # Internal State
        self.heat = 0
        self.sensory_radius = 72.0
        self.pulse_active = False
        self.pulse_start_time = 0.0
        self.pulse_origin = np.array([0.0, 0.0, 0.0], dtype="f4")
        self.pulse_duration = 2.5

        # Registry
        self.registry = {
            "portland": {"lat": 45.5152, "lon": -122.6784},
            "los_angeles": {"lat": 34.0522, "lon": -118.2437},
            "chicago": {"lat": 41.8781, "lon": -87.6298},
            "new_york": {"lat": 40.7128, "lon": -74.0060},
            "miami": {"lat": 25.7617, "lon": -80.1918},
        }

    # 1. SENSOR LOGIC (Formerly EnvironmentalSensor)
    def _get_weather(self, city: str = "portland") -> Dict:
        mapped_city = self.config.resolve_city(city)
        anchor = self.registry.get(mapped_city, self.registry["portland"])
        return {
            "city": mapped_city.replace("_", " ").title(),
            "lat": anchor["lat"],
            "lon": anchor["lon"],
            "temp": 20.0,
            "condition": "Clear",
            "coherence": 0.85,
        }

    # 2. PERCEPTION LOGIC (Formerly PerceptionController)
    def trigger_pulse(self, origin_vector):
        self.pulse_active = True
        self.pulse_start_time = float(pygame.time.get_ticks() / 1000.0)
        self.pulse_origin = np.array(
            [origin_vector.x, origin_vector.y, origin_vector.z], dtype="f4"
        )

    def get_shader_params(self, city: str = "portland") -> Dict:
        t = float(pygame.time.get_ticks() / 1000.0)
        weather = self._get_weather(city)
        intensity = np.clip(abs(weather.get("temp", 60) - 60) / 50.0, 0.0, 1.0)

        pulse_elapsed = 0.0
        if self.pulse_active:
            pulse_elapsed = t - self.pulse_start_time
            if pulse_elapsed > self.pulse_duration:
                self.pulse_active = False
                pulse_elapsed = 0.0

        return {
            "u_time": t,
            "u_intensity": float(intensity),
            "u_visibility": float(self.sensory_radius),
            "u_pulse_time": float(pulse_elapsed),
            "u_pulse_origin": self.pulse_origin,
        }

    # 3. SCOUT LOGIC (Formerly ScoutEngine)
    def resolve_scout(
        self, player_aegis: float, tactic: str = "standard", city: str = "portland"
    ) -> ScoutResult:
        if self.heat >= 100:
            raise ThermalError("CRITICAL OVERHEAT: System lockout active.")

        weather = self._get_weather(city)
        hazard_rating = 40.0 + (self.heat / 2.0)

        modifiers = {
            "stealth": {"hazard": -10.0, "reward": 0.7, "heat": 0.5},
            "standard": {"hazard": 0.0, "reward": 1.0, "heat": 1.0},
            "aggressive": {"hazard": 15.0, "reward": 1.5, "heat": 2.0},
        }
        mod = modifiers.get(tactic, modifiers["standard"])

        power_score = min(player_aegis / 1000, 30.0)
        roll = random.randint(1, 100) + power_score
        success = roll >= (hazard_rating + mod["hazard"])

        # Update internal heat state
        heat_gen = (
            int(random.randint(5, 12) * mod["heat"])
            if success
            else int(random.randint(15, 25) * mod["heat"])
        )
        self.heat += heat_gen

        msg = (
            f"[{tactic.upper()}] Signal stable in {weather['city']}."
            if success
            else f"[{tactic.upper()}] Signal lost in {weather['city']}."
        )

        return ScoutResult(success, msg, 100.0 * mod["reward"], 10, heat_gen)
