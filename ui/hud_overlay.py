from ursina import Text, color, window
from systems.observer import bus


class HUDOverlay:
    def __init__(self, session, world):
        self.session = session
        self.world = world

        # ASCII Viewport in top right corner
        self.text_element = Text(
            text="",
            position=(0.5, 0.45),  # Top right
            origin=(0.5, 0.5),  # Anchor top right
            scale=1.5,
            color=color.green,
            font="Courier",  # Monospaced font for grid
            background=True,
        )
        self.text_element.create_background(
            padding=0.05, color=color.rgba(0, 0, 0, 200)
        )

        bus.subscribe("PLAYER_MOVED", self.on_player_moved)
        bus.subscribe("VFX_CONFIG", self.on_vfx_config)
        # Initialize display
        self.update_display()

    def on_player_moved(self, data):
        self.update_display()

    def on_vfx_config(self, config_data):
        # We can live-tweak aesthetic logic here, e.g., color tinting the HUD
        # based on dither_step or wind_sway_hz
        if "color" in config_data:
            self.text_element.color = config_data["color"]

    def update_display(self):
        px, pz = int(self.session.pos[0]), int(self.session.pos[2])
        grid_size = 5  # 5 in each direction = 11x11 grid

        lines = []
        # z-axis usually goes "up" in terminal but standard loop goes top to bottom
        # Let's render highest Z at the top
        for z in range(pz + grid_size, pz - grid_size - 1, -1):
            row = []
            for x in range(px - grid_size, px + grid_size + 1):
                if x == px and z == pz:
                    row.append("@")
                else:
                    obj_id = self.world.get_object_at(x, z)
                    if obj_id == "101":
                        row.append("$")
                    elif obj_id == "301":
                        row.append("#")
                    else:
                        row.append(".")
            lines.append(" ".join(row))

        self.text_element.text = "\n".join(lines)
