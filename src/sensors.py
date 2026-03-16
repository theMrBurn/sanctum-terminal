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
            "miami": {"lat": 25.7617, "lon": -80.1918}
        }

    def fetch_passive_data(self, city: str = "portland") -> dict:
        """
        Gathers the raw 'Passive' environmental data from the real world.
        """
        city = city.lower().replace(" ", "_")
        coords = self.registry.get(city, self.registry["portland"])
        
        # If no API key, we return a 'Static Default' for testing/offline mode
        if not self.api_key:
            return self._get_offline_defaults(city)

        params = {
            "lat": coords["lat"],
            "lon": coords["lon"],
            "appid": self.api_key,
            "units": "imperial"
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=5)
            data = response.json()
            
            return {
                "city": city.title(),
                "temp": data["main"]["temp"],
                "condition": data["weather"][0]["main"],
                "wind_speed": data["wind"]["speed"],
                "humidity": data["main"]["humidity"],
                "timestamp": datetime.now().isoformat(),
                "is_live": True
            }
        except Exception as e:
            print(f"[SENSOR ERROR] Falling back to offline defaults: {e}")
            return self._get_offline_defaults(city)

    def _get_offline_defaults(self, city: str) -> dict:
        """Fallback for when you're working without an internet connection."""
        return {
            "city": city.title(),
            "temp": 50.0,
            "condition": "Overcast",
            "wind_speed": 5.0,
            "humidity": 80,
            "timestamp": datetime.now().isoformat(),
            "is_live": False
        }

if __name__ == "__main__":
    # Quick tire-kick
    sensor = EnvironmentalSensor()
    print(sensor.fetch_passive_data("portland"))