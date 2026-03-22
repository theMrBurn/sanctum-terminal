import math


class WorldEngine:
    def __init__(self, seed=42):
        self.seed = seed
        self.poi_coords = (0, 0)

    def get_object_at(self, x, y):
        """
        001: Substrate (Ground)
        101: Data Vault (Entity)
        301: Void Wall (Barrier)
        """
        # Deterministic seed for spatial consistency
        h = (int(x) * 73856093 ^ int(y) * 19349663 ^ self.seed) % 100

        # Buffer around spawn
        if abs(x) < 3 and abs(y) < 3:
            return None

        if h > 92:
            return "101"  # Data Vault
        if h > 75:
            return "301"  # Void Wall

        return None

    def get_node(self, x, z, session):
        # 1. Bypass normal geographical logic in LAB MODE
        if getattr(session, "is_lab_mode", False):
            # Load dynamic lab manifest
            import json
            import os

            entities_map = {}
            manifest_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config",
                "lab_manifest.json",
            )
            if os.path.exists(manifest_path):
                with open(manifest_path, "r") as f:
                    manifest_data = json.load(f)
                    for ent in manifest_data.get("entities", []):
                        entities_map[tuple(ent["pos"])] = ent["id"]

            # 20x20 Stage bounds
            if -10 <= x <= 10 and -10 <= z <= 10:
                # Neutral grey stage
                r, g, b = (100, 100, 100)
                passable = True
                char = "."
                meta = {}

                if (x, z) in entities_map:
                    from core.registry import LAB_REGISTRY

                    obj_id = entities_map[(x, z)]
                    lab_obj = LAB_REGISTRY.get(obj_id, {})
                    r, g, b = lab_obj.get("base_color", (255, 0, 255))
                    passable = False
                    char = (
                        "L" if obj_id == "201" else "E"
                    )  # Provide a fallback char 'E' for generic entities
                    meta = lab_obj.copy()

                    # Print parameter logger to console
                    from rich.console import Console
                    from rich.panel import Panel

                    console = Console()

                    log_text = (
                        f"[cyan]ID:[/cyan] {obj_id}\n"
                        f"[cyan]Name:[/cyan] {meta.get('name')}\n"
                        f"[cyan]Dither Step:[/cyan] {meta.get('dither_step')}\n"
                        f"[cyan]Light Radius:[/cyan] {meta.get('light_radius')}\n"
                        f"[cyan]Flicker HZ:[/cyan] {meta.get('flicker_hz')}"
                    )
                    console.print(
                        Panel(
                            log_text,
                            title=f"[yellow]LAB: PARAMETER LOGGER ({x}, {z})[/yellow]",
                        )
                    )

                return {
                    "pos": (float(x), 0.0, float(z)),
                    "color": (r, g, b),
                    "meta": meta,
                    "passable": passable,
                    "char": char,
                }
            else:
                # The Void outside the stage
                return {
                    "pos": (float(x), 0.0, float(z)),
                    "color": (0, 0, 0),
                    "meta": {},
                    "passable": False,
                    "char": " ",
                }

        from core.atlas import VOXEL_REGISTRY, ARCHETYPES

        obj_id = self.get_object_at(x, z)

        # Mappings: None -> Substrate (.), 101 -> Data Vault ($), 301 -> Void Wall (X)
        if obj_id == "101":
            voxel_key = "$"
            passable = False
        elif obj_id == "301":
            voxel_key = "X"
            passable = False
        else:
            voxel_key = "."
            passable = True

        meta = VOXEL_REGISTRY.get(voxel_key, {}).copy()

        # We also need a char key in meta for the 2D terminal compatibility
        meta["char"] = voxel_key

        # Base color selection based on archetype
        archetype = ARCHETYPES.get(session.user_locale, {})
        base_color = (128, 128, 128)  # fallback gray
        if session.user_locale == "URBAN":
            base_color = (100, 100, 100)
        elif session.user_locale == "FOREST":
            base_color = (34, 139, 34)
        elif session.user_locale == "DESERT":
            base_color = (210, 180, 140)
        elif session.user_locale == "COAST":
            base_color = (70, 130, 180)

        r, g, b = base_color

        # Specific color overrides based on the object
        if obj_id == "101":
            # Data Vault is glowing gold/yellow
            r, g, b = (255, 215, 0)
        elif obj_id == "301":
            # Void Wall is deep purple/black
            r, g, b = (40, 0, 60)

        # "Neon" Signal Layer (0x10) shifts RGB to bright neon tones
        if 0x10 in session.biome_tags:
            # Shift colors to neon variants (e.g. increase blue/red, boost brightness)
            # A simple glowing shift: boost R and B for that synthwave/neon look
            r = min(255, r + 80)
            g = max(0, g - 20)
            b = min(255, b + 100)

        # Scale to 0-1 range for many rendering engines if needed, but dict asks for standard RGB
        # We will keep 0-255 scale

        return {
            "pos": (float(x), 0.0, float(z)),
            "color": (r, g, b),
            "meta": meta,
            "passable": passable,
            "char": voxel_key,  # Also provide at root level for backward compatibility if needed
        }
