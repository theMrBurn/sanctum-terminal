class BiomeRegistry:
    """
    10x Biome definitions gated by QuestEngine state.
    QuestEngine is the authority — biome selection defers to it
    before falling back to noise-based temperature/moisture logic.
    """

    BIOMES = {
        "VOID": {
            "v_id": "METAL",
            "relic": {"u_fog": (0.0, 0.0, 0.0, 1.0), "u_exp": 0.5},
        },
        "NEON": {
            "v_id": "PIPE",
            "relic": {"u_fog": (0.1, 0.0, 0.2, 1.0), "u_exp": 1.1, "u_glow": 2.5},
        },
        "IRON": {
            "v_id": "RUST",
            "relic": {"u_fog": (0.3, 0.2, 0.1, 1.0), "u_exp": 0.8},
        },
        "SILICA": {
            "v_id": "SAND",
            "relic": {"u_fog": (0.9, 0.8, 0.7, 1.0), "u_exp": 1.5},
        },
        "FROZEN": {
            "v_id": "ICE",
            "relic": {"u_fog": (0.8, 0.9, 1.0, 1.0), "u_exp": 1.0},
        },
        "SULPHUR": {
            "v_id": "S_STONE",
            "relic": {"u_fog": (0.4, 0.4, 0.0, 1.0), "u_exp": 0.9},
        },
        "BASALT": {
            "v_id": "LAVA",
            "relic": {"u_fog": (0.1, 0.0, 0.0, 1.0), "u_exp": 0.7},
        },
        "VERDANT": {
            "v_id": "MOSS",
            "relic": {"u_fog": (0.1, 0.2, 0.1, 1.0), "u_exp": 0.9},
        },
        "MYCELIUM": {
            "v_id": "SPORE",
            "relic": {"u_fog": (0.2, 0.1, 0.2, 1.0), "u_exp": 0.6},
        },
        "CHROME": {
            "v_id": "MIRROR",
            "relic": {"u_fog": (1.0, 1.0, 1.0, 1.0), "u_exp": 2.0},
        },
    }

    # Which biome each quest tier forces when override is active
    TIER_BIOME_MAP = {
        "surface": "VERDANT",
        "dungeon": "BASALT",
        "boss": "VOID",
    }

    def __init__(self, quest_engine=None):
        self.quest_engine = quest_engine

    # ── Private ───────────────────────────────────────────────────────────────

    def _noise_biome(self, t, m):
        """
        Fallback noise-based biome selection when QuestEngine
        has no active override. t=temperature, m=moisture, both 0.0-1.0.
        """
        if t < 0.2:
            return self.BIOMES["FROZEN"]
        if t > 0.8:
            return self.BIOMES["SILICA"] if m < 0.3 else self.BIOMES["SULPHUR"]
        if m > 0.7:
            return self.BIOMES["VERDANT"]
        if m < 0.2:
            return self.BIOMES["IRON"]
        if t > 0.6 and m > 0.4:
            return self.BIOMES["MYCELIUM"]
        if t < 0.4 and m < 0.5:
            return self.BIOMES["NEON"]
        return self.BIOMES["VOID"]

    def _merge_relic(self, base_relic, quest_atmosphere):
        """
        Merges quest atmosphere on top of a base biome relic dict.
        Quest values win on conflict — QuestEngine is the authority.
        Returns a new dict, never mutates the originals.
        """
        merged = dict(base_relic)
        merged.update(quest_atmosphere)
        return merged

    # ── Public API ────────────────────────────────────────────────────────────

    @classmethod
    def all_biome_keys(cls):
        """
        Returns every unique shader key across all biomes.
        Used by the snapshot tool to discover the full key surface area.
        """
        keys = set()
        for biome in cls.BIOMES.values():
            keys.update(biome["relic"].keys())
        return sorted(keys)

    def get_biome(self, t, m):
        """
        Primary biome resolution method.

        Resolution order:
        1. QuestEngine override (boss tier forces a specific biome)
        2. Noise-based fallback (temperature + moisture)

        Returns a biome dict with v_id and relic merged with
        quest atmosphere if QuestEngine is present.
        """
        t = max(0.0, min(1.0, float(t)))
        m = max(0.0, min(1.0, float(m)))

        quest_rules = (
            self.quest_engine.get_active_biome_rules() if self.quest_engine else None
        )

        # Step 1 — check for a hard biome override from QuestEngine
        if quest_rules and quest_rules.get("biome_override"):
            tier = quest_rules["biome_override"]
            biome_key = self.TIER_BIOME_MAP.get(tier, "VOID")
            base_biome = dict(self.BIOMES[biome_key])
            base_biome["relic"] = self._merge_relic(
                base_biome["relic"], quest_rules["atmosphere"]
            )
            return base_biome

        # Step 2 — noise fallback, still merge quest atmosphere if present
        base_biome = dict(self._noise_biome(t, m))
        if quest_rules:
            base_biome["relic"] = self._merge_relic(
                base_biome["relic"], quest_rules["atmosphere"]
            )
        return base_biome

    def get_state(self, t, m):
        """
        Convenience method matching VoxelFactory's expected interface.
        Returns (voxel_id, relic_dict).
        """
        biome = self.get_biome(t, m)
        return biome["v_id"], biome["relic"]
