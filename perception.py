import numpy as np
import pygame


class PerceptionController:
    def __init__(self, sensor_array):
        self.sensors = sensor_array
        self.base_temp = 60.0
        self.sensory_radius = 72.0

        # Sonar State Machine
        self.pulse_active = False
        self.pulse_start_time = 0.0
        self.pulse_origin = np.array([0.0, 0.0, 0.0], dtype="f4")
        self.pulse_duration = 2.5  # Seconds for wave to travel 125m

    def trigger_pulse(self, origin_vector):
        """Initiates a high-frequency sensor ping."""
        self.pulse_active = True
        self.pulse_start_time = pygame.time.get_ticks() / 1000.0
        self.pulse_origin = np.array(
            [origin_vector.x, origin_vector.y, origin_vector.z], dtype="f4"
        )

    def get_shader_state(self, location="portland", current_time=None):
        """
        Consolidates perception data.
        current_time: Optional override for TDD/Simulation.
        """
        if current_time is None:
            current_time = pygame.time.get_ticks() / 1000.0

        weather = self.sensors.fetch_passive_data(location)

        # Passive Shimmer Intensity (Thermal Stress)
        intensity = np.clip(abs(weather.get("temp", 60) - 60) / 50.0, 0.0, 1.0)

        # Active Sonar Pulse Logic
        pulse_elapsed = 0.0
        if self.pulse_active:
            pulse_elapsed = current_time - self.pulse_start_time
            if pulse_elapsed > self.pulse_duration:
                self.pulse_active = False
                pulse_elapsed = 0.0

        return {
            "u_time": current_time,
            "u_intensity": float(intensity),
            "u_visibility": float(self.sensory_radius),
            "u_pulse_time": float(pulse_elapsed),
            "u_pulse_origin": self.pulse_origin,
        }
