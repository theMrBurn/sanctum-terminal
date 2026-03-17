import json
import os


class ConfigManager:
    def __init__(self):
        # Resolve path relative to this file to ensure it works from any directory
        base_path = os.path.dirname(__file__)
        config_path = os.path.join(base_path, "config", "manifest.json")

        with open(config_path, "r") as f:
            self.data = json.load(f)

    def resolve_city(self, alias: str) -> str:
        """Converts pdx -> portland. Returns alias if no match found."""
        return self.data["city_map"].get(alias.lower(), alias)

    def resolve_tactic(self, alias: str) -> str:
        """Converts 's' or '1' -> 'stealth'. Defaults to 'standard'."""
        return self.data["tactics"].get(str(alias).lower(), "standard")
