import json
import sqlite3
from pathlib import Path


def _load_manifest():
    path = Path(__file__).parent.parent.parent / "config" / "manifest.json"
    if path.exists():
        return json.load(open(path))
    return {}


class QuestEngine:
    """
    The Heartbeat. Global state authority for the Sanctum Terminal.
    Reads from vault.db on init, holds state in memory during session,
    writes back to vault.db on register_event.
    All tunable values loaded from config/manifest.json.
    """

    def __init__(self, db_path=None, config=None):
        self._config = config or _load_manifest()

        tiers = self._config.get(
            "tiers", {"surface": [1, 3], "dungeon": [4, 6], "boss": [7, 10]}
        )
        self.TIER_MAP = {k: tuple(v) for k, v in tiers.items()}

        atm = self._config.get("atmosphere", {})
        self.TIER_ATMOSPHERES = {
            "surface": self._parse_atm(
                atm.get("surface", {"u_fog": (0.1, 0.1, 0.15, 1.0), "u_exp": 0.8})
            ),
            "dungeon": self._parse_atm(
                atm.get("dungeon", {"u_fog": (0.05, 0.05, 0.1, 1.0), "u_exp": 1.2})
            ),
            "boss": self._parse_atm(
                atm.get("boss", {"u_fog": (0.02, 0.0, 0.05, 1.0), "u_exp": 1.8})
            ),
        }
        self.DEFAULT_ATMOSPHERE = self._parse_atm(
            atm.get("default", {"u_fog": (0.1, 0.1, 0.15, 1.0), "u_exp": 1.0})
        )

        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "vault.db"

        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"QuestEngine: vault.db not found at {self.db_path}"
            )

        self.relics = []
        self._load_relics()

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_atm(atm_dict):
        fog = atm_dict.get("u_fog", [0.1, 0.1, 0.15, 1.0])
        return {
            "u_fog": tuple(fog) if isinstance(fog, list) else fog,
            "u_exp": atm_dict.get("u_exp", 1.0),
        }

    def _load_relics(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT archetypal_name, vibe, impact_rating FROM archive"
            ).fetchall()
            conn.close()
            self.relics = [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            raise RuntimeError(f"QuestEngine: failed to load relics — {e}") from e

    def _max_impact(self):
        if not self.relics:
            return 0
        return max(r["impact_rating"] for r in self.relics)

    def _avg_impact(self):
        if not self.relics:
            return 0.0
        return sum(r["impact_rating"] for r in self.relics) / len(self.relics)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_impact_tier(self, rating):
        for tier, (lo, hi) in self.TIER_MAP.items():
            if lo <= rating <= hi:
                return tier
        return "surface"

    def get_atmosphere_for_tier(self, tier):
        return dict(self.TIER_ATMOSPHERES.get(tier, self.TIER_ATMOSPHERES["surface"]))

    def get_active_biome_rules(self):
        if not self.relics:
            return {
                "biome_override": None,
                "atmosphere": dict(self.DEFAULT_ATMOSPHERE),
                "encounter_density": 0.0,
                "rotation_speed": 1.0,
            }

        max_impact = self._max_impact()
        avg_impact = self._avg_impact()
        tier = self.get_impact_tier(max_impact)
        atmosphere = self.get_atmosphere_for_tier(tier)
        scale = max_impact / 10.0
        encounter_density = min(1.0, scale * 1.2)
        rotation_speed = 0.5 + scale
        atmosphere["u_exp"] = round(0.5 + (avg_impact / 10.0) * 2.0, 3)

        return {
            "biome_override": tier if max_impact >= 7 else None,
            "atmosphere": atmosphere,
            "encounter_density": round(encounter_density, 3),
            "rotation_speed": round(rotation_speed, 3),
        }

    def register_event(self, relic_dict):
        if not relic_dict:
            raise ValueError("QuestEngine.register_event: relic_dict is empty.")
        if "archetypal_name" not in relic_dict:
            raise ValueError("QuestEngine.register_event: archetypal_name is required.")

        rating = relic_dict.get("impact_rating", 1)
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            rating = 1
        rating = max(1, min(10, rating))

        vibe = relic_dict.get("vibe", "")
        name = relic_dict["archetypal_name"]

        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO archive (archetypal_name, vibe, impact_rating) VALUES (?, ?, ?)",
                (name, vibe, rating),
            )
            conn.commit()
            conn.close()
        except sqlite3.OperationalError as e:
            raise RuntimeError(
                f"QuestEngine.register_event: DB write failed — {e}"
            ) from e

        self.relics.append(
            {
                "archetypal_name": name,
                "vibe": vibe,
                "impact_rating": rating,
            }
        )

    def build_relic_dict(self, relic):
        rating = relic.get("impact_rating", 1)
        tier = self.get_impact_tier(rating)
        atm = self.get_atmosphere_for_tier(tier)
        scale = rating / 10.0
        atm["u_exp"] = round(0.5 + scale * 2.0, 3)
        return atm
