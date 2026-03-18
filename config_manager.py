import json
import os


class ConfigManager:
    def __init__(self):
        # Base path is the directory where this file lives
        base_path = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_path, "config", "manifest.json")

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Missing manifest at {config_path}")

        with open(config_path, "r") as f:
            self.data = json.load(f)

    def get(self, key_path, default=None):
        """Allows nested lookup like 'avatar.height'"""
        keys = key_path.split(".")
        val = self.data
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            return default

    def resolve_city(self, alias: str) -> str:
        return self.data.get("city_map", {}).get(alias.lower(), alias)

    def resolve_tactic(self, alias: str) -> str:
        return self.data.get("tactics", {}).get(str(alias).lower(), "standard")
