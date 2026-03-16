from src.sensors import EnvironmentalSensor


def test_sensor_registry_coverage():
    """Verify all 5 cities are correctly mapped."""
    sensor = EnvironmentalSensor()
    cities = ["portland", "los_angeles", "chicago", "new_york", "miami"]

    for city in cities:
        data = sensor.fetch_passive_data(city)
        assert data["city"] == city.replace("_", " ").title()
        assert "temp" in data
