import os
from config_manager import ConfigManager


class EnvironmentalSensor:
    def __init__(self, api_key: str = None):
        self.config = ConfigManager()
        self.api_key = api_key or os.getenv("OPENWEATHER_API_KEY")
        self.registry = {
            "portland": {"lat": 45.5152, "lon": -122.6784},
            "los_angeles": {"lat": 34.0522, "lon": -118.2437},
            "chicago": {"lat": 41.8781, "lon": -87.6298},
            "new_york": {"lat": 40.7128, "lon": -74.0060},
            "miami": {"lat": 25.7617, "lon": -80.1918},
        }

    def get_static_anchor(self, city: str = "portland"):
        mapped_city = self.config.resolve_city(city)
        return self.registry.get(mapped_city, self.registry["portland"])

    def fetch_passive_data(self, city: str = "portland"):
        anchor = self.get_static_anchor(city)
        # Use the mapped city name and format for TDD (title case, no underscores)
        raw_name = self.config.resolve_city(city)
        formatted_city = raw_name.replace("_", " ").title()

        return {
            "city": formatted_city,
            "lat": anchor["lat"],
            "lon": anchor["lon"],
            "temp": 20.0,
            "coherence": 0.85,
        }
