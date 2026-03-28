import random
from pathlib import Path


class SpawnEngine:
    """
    Procedural scene composer using asset prefix taxonomy.
    Composes ecologically valid biome scenes around player origin (0,0,0).
    Deterministic given the same seed value.
    No assets hardcoded — works with whatever exists in asset_lib.
    """

    # Spawn radius around origin
    SPAWN_RADIUS = 30.0

    # How many of each prefix to consider per density level
    DENSITY_TABLE = {
        "GLO": (1, 1),  # always exactly 1
        "ATM": (0, 2),  # 0-2 landmarks
        "PAS": (1, 4),  # 1-4 passive fill
        "ACT": (0, 5),  # 0-5 encounter objects scaled by density
        "TOOL": (0, 3),  # 0-3 interactive objects
        "WEAR": (0, 2),  # 0-2 equipment (only with ACT)
    }

    def __init__(self, asset_lib=None, db_path=None):
        self.asset_lib = asset_lib or {}
        self.db_path = Path(db_path) if db_path else None
        self.prefix_table = self._build_prefix_table()

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_prefix_table(self):
        """Index asset_lib by prefix for fast lookup."""
        table = {}
        for asset_id in self.asset_lib:
            prefix = asset_id.split("_")[0]
            if prefix not in table:
                table[prefix] = []
            table[prefix].append(asset_id)
        return table

    def _pick(self, rng, prefix, count):
        """Randomly pick count assets from a prefix bucket."""
        pool = self.prefix_table.get(prefix, [])
        if not pool:
            return []
        return [rng.choice(pool) for _ in range(min(count, len(pool)))]

    def _random_pos(self, rng, radius=None):
        """Random position within spawn radius. Never exactly origin."""
        r = radius or self.SPAWN_RADIUS
        while True:
            x = rng.uniform(-r, r)
            y = rng.uniform(-r, r)
            if abs(x) > 1.0 or abs(y) > 1.0:
                return (round(x, 2), round(y, 2), 0.0)

    def _count_for_density(self, prefix, density):
        """Scale spawn count by encounter density (0.0-1.0)."""
        lo, hi = self.DENSITY_TABLE.get(prefix, (0, 1))
        if prefix == "GLO":
            return 1
        scaled = lo + int((hi - lo) * density)
        return max(lo, min(hi, scaled))

    # ── Public API ────────────────────────────────────────────────────────────

    def compose_scene(self, encounter_density=0.5, seed=42):
        """
        Composes a full biome scene as a list of spawn instructions.
        Deterministic given the same seed and density.
        Respects ecological rules:
          - Always exactly 1 GLO base
          - WEAR only spawns when ACT is present
          - TOOL count never exceeds ACT count
        Returns list of dicts: {asset_id, prefix, pos}
        """
        rng = random.Random(seed)
        scene = []

        # GLO — always first, always at origin
        glo_assets = self._pick(rng, "GLO", 1)
        for asset_id in glo_assets:
            scene.append(
                {
                    "asset_id": asset_id,
                    "prefix": "GLO",
                    "pos": (0, 0, 0),
                }
            )

        # ATM — landmarks, scattered wide
        atm_count = self._count_for_density("ATM", encounter_density)
        for asset_id in self._pick(rng, "ATM", atm_count):
            scene.append(
                {
                    "asset_id": asset_id,
                    "prefix": "ATM",
                    "pos": self._random_pos(rng, self.SPAWN_RADIUS),
                }
            )

        # PAS — passive fill, medium scatter
        pas_count = self._count_for_density("PAS", encounter_density)
        for asset_id in self._pick(rng, "PAS", pas_count):
            scene.append(
                {
                    "asset_id": asset_id,
                    "prefix": "PAS",
                    "pos": self._random_pos(rng, self.SPAWN_RADIUS * 0.6),
                }
            )

        # ACT — encounters, close to player
        act_count = self._count_for_density("ACT", encounter_density)
        act_spawned = []
        for asset_id in self._pick(rng, "ACT", act_count):
            pos = self._random_pos(rng, self.SPAWN_RADIUS * 0.4)
            scene.append(
                {
                    "asset_id": asset_id,
                    "prefix": "ACT",
                    "pos": pos,
                }
            )
            act_spawned.append(asset_id)

        # TOOL — only if ACT present, count <= ACT count
        if act_spawned:
            tool_count = min(
                self._count_for_density("TOOL", encounter_density), len(act_spawned)
            )
            for asset_id in self._pick(rng, "TOOL", tool_count):
                scene.append(
                    {
                        "asset_id": asset_id,
                        "prefix": "TOOL",
                        "pos": self._random_pos(rng, self.SPAWN_RADIUS * 0.3),
                    }
                )

        # WEAR — only if ACT present
        if act_spawned:
            wear_count = self._count_for_density("WEAR", encounter_density)
            for asset_id in self._pick(rng, "WEAR", wear_count):
                scene.append(
                    {
                        "asset_id": asset_id,
                        "prefix": "WEAR",
                        "pos": self._random_pos(rng, self.SPAWN_RADIUS * 0.2),
                    }
                )

        return scene

    def scene_from_quest_rules(self, quest_rules, seed=42):
        """
        Convenience method — composes scene directly from QuestEngine rules.
        """
        density = quest_rules.get("encounter_density", 0.5)
        return self.compose_scene(encounter_density=density, seed=seed)
