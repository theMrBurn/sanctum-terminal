import numpy as np


class ScoutResult:
    def __init__(self, success, damage=0):
        self.success = success
        self.system_damage = damage


class ObserverSystem:
    def __init__(self, config):
        self.config = config
        self.heat = 0.0
        self.pulse_time = 10.0
        self.pulse_origin = np.array([0, 0, 0], dtype="f4")
        self.is_pulsing = False
        self.base_visibility = 72.0
        self.sensors_nominal = True

    def update(self, dt, move_delta_mag=0.0):
        if self.is_pulsing:
            self.pulse_time += dt
            if self.pulse_time > 2.0:
                self.is_pulsing = False
                self.pulse_time = 10.0

        target_heat = move_delta_mag * 50.0
        if self.heat < target_heat:
            self.heat = min(100.0, self.heat + (dt * 40.0))
        else:
            self.heat = max(0.0, self.heat - (dt * 15.0))

        if self.heat < 10.0 and not self.sensors_nominal:
            self.sensors_nominal = True

    def trigger_pulse(self, origin_vector):
        # Support both MagicMock (.x, .y, .z) and Numpy/List access
        try:
            self.pulse_origin = np.array(
                [origin_vector.x, origin_vector.y, origin_vector.z], dtype="f4"
            )
        except AttributeError:
            self.pulse_origin = np.array(
                [origin_vector[0], origin_vector[1], origin_vector[2]], dtype="f4"
            )
        self.pulse_time = 0.0
        self.is_pulsing = True

    def resolve_scout(self, player_aegis, tactic="neutral", city="portland"):
        hazard = 40.0 if tactic == "aggressive" else 10.0
        is_successful = (player_aegis + self.base_visibility) > (hazard + self.heat)
        damage_taken = 0
        if not is_successful:
            damage_taken = (hazard + self.heat) - (player_aegis + self.base_visibility)
            self.sensors_nominal = False
        return ScoutResult(success=is_successful, damage=damage_taken)

    def get_shader_params(self, city=None):  # 'city' added back for test compatibility
        return {
            "u_pulse_time": self.pulse_time,
            "u_pulse_origin": self.pulse_origin,
            "u_intensity": max(0.0, min(0.8, self.heat / 100.0)),
            "u_visibility": self.base_visibility,
        }

class EventBus:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(EventBus, cls).__new__(cls, *args, **kwargs)
            cls._instance.subscribers = {}
        return cls._instance

    def subscribe(self, event_type: str, callback):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        if callback not in self.subscribers[event_type]:
            self.subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback):
        if event_type in self.subscribers and callback in self.subscribers[event_type]:
            self.subscribers[event_type].remove(callback)

    def emit(self, event_type: str, data=None):
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                callback(data)

    def clear(self):
        """Useful for resetting state between tests."""
        self.subscribers = {}

# Global instance for easy import
bus = EventBus()