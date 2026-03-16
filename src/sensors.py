import requests
import os
from datetime import datetime


class EnvironmentalSensor:
    def __init__(self, api_key: str = None):
        # You can get a free key at openweathermap.org
        self.api_key = api_key or os.getenv("OPENWEATHER_API_KEY")
        self.base_url = "http://api.openweathermap.org/data/2.5/weather"

        # Our 5-City Anchor Points (Lat/Lon)
        self.registry = {
            "portland": {"lat": 45.5152, "lon": -122.6784},
            "los_angeles": {"lat": 34.0522, "lon": -118.2437},
            "chicago": {"lat": 41.8781, "lon": -87.6298},
            "new_york": {"lat": 40.7128, "lon": -74.0060},
            "miami": {"lat": 25.7617, "lon": -80.1918},
        }

    def fetch_passive_data(self, city: str = "portland") -> dict:
        """
        Gathers the raw 'Passive' environmental data from the real world.
        """
        city_key = city.lower().replace(" ", "_")
        coords = self.registry.get(city_key, self.registry["portland"])

        # Purify name for UI and Tests
        clean_city_name = city_key.replace("_", " ").title()

        if not self.api_key:
            return self._get_offline_defaults(clean_city_name)

        # 1. DEFINE PARAMS HERE (So the try block can see them)
        params = {
            "lat": coords["lat"],
            "lon": coords["lon"],
            "appid": self.api_key,
            "units": "imperial",
        }

        try:
            # 2. params is now defined and safe to use
            response = requests.get(self.base_url, params=params, timeout=5)
            data = response.json()

            return {
                "city": clean_city_name,
                "temp": data["main"]["temp"],
                "condition": data["weather"][0]["main"],
                "wind_speed": data["wind"]["speed"],
                "humidity": data["main"]["humidity"],
                "timestamp": datetime.now().isoformat(),
                "is_live": True,
            }
        except Exception as e:
            print(f"[SENSOR ERROR] Falling back to offline defaults: {e}")
            return self._get_offline_defaults(clean_city_name)
        try:
            response = requests.get(self.base_url, params=params, timeout=5)
            data = response.json()

            return {
                "city": clean_city_name,  # <-- Use it here
                "temp": data["main"]["temp"],
                "condition": data["weather"][0]["main"],
                "wind_speed": data["wind"]["speed"],
                "humidity": data["main"]["humidity"],
                "timestamp": datetime.now().isoformat(),
                "is_live": True,
            }
        except Exception:
            return self._get_offline_defaults(clean_city_name)  # <-- And here

    def _get_offline_defaults(self, display_name: str) -> dict:
        """Fallback for when you're working without an internet connection."""
        return {
            "city": display_name,  # <-- Use the passed display_name
            "temp": 50.0,
            "condition": "Overcast",
            "wind_speed": 5.0,
            "humidity": 80,
            "timestamp": datetime.now().isoformat(),
            "is_live": False,
        }


if __name__ == "__main__":
    # Quick tire-kick
    sensor = EnvironmentalSensor()
    print(sensor.fetch_passive_data("portland"))
