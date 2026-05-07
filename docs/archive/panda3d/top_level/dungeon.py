"""
dungeon.py

The 7-Door Dungeon -- playable Wizardry-style corridor crawl.

8 doors. 7 attempts. 1 minute detail. Find it.

Controls:
    W/S         Walk forward/back
    A/D/Arrows  Turn left/right
    1-8         Examine door (free, no cost)
    Shift+1-8   Try door (costs an attempt if wrong)
    ESC         Quit

Usage:
    make dungeon
"""

import sys
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight, DirectionalLight, Vec4, Vec3,
    WindowProperties, TextNode, AntialiasAttrib,
    Fog, Material, Texture, SamplerState,
    TransparencyAttrib,
)
from rich.console import Console

from core.systems.dungeon_campaign import DungeonCampaign
from core.systems.dungeon_grid import DungeonGrid
from core.systems.geometry import make_box, make_plane, make_textured_quad, make_textured_wall, make_textured_floor

console = Console()

# -- Visual constants ----------------------------------------------------------

CORRIDOR_WIDTH  = 16.0
CORRIDOR_DEPTH  = 24.0
WALL_HEIGHT     = 6.0
DOOR_WIDTH      = 1.8
DOOR_HEIGHT     = 3.2
DOOR_SPACING    = (CORRIDOR_WIDTH - 2.0) / 8.0
DOOR_Y          = CORRIDOR_DEPTH / 2 - 1.5
MOVE_SPEED      = 6.0
TURN_SPEED      = 80.0

# Colors
WALL_COLOR    = (0.10, 0.08, 0.07)
FLOOR_COLOR   = (0.08, 0.06, 0.05)
CEILING_COLOR = (0.06, 0.05, 0.04)
DOOR_COLOR    = (0.15, 0.12, 0.10)
DOOR_CORRECT_HINT = (0.16, 0.13, 0.11)  # barely different — the test
FOG_COLOR     = (0.04, 0.03, 0.03)


class Dungeon(ShowBase):

    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum -- The Garden of Forking Paths")
        props.setSize(1280, 720)
        self.win.requestProperties(props)

        self.setBackgroundColor(0.02, 0.02, 0.03, 1)
        self.disableMouse()
        self.camLens.setFov(75)
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        # Dungeon state
        self._campaign = DungeonCampaign(seed="GARDEN_OF_FORKING_PATHS")
        self._grid = DungeonGrid()
        self._message = ""
        self._message_timer = 0.0
        self._examine_result = None
        self._hud = []
        self._door_nodes = []
        self._scene_nodes = []

        # Lighting
        self._setup_lighting()

        # Fog
        fog = Fog("dungeon_fog")
        fog.setColor(Vec4(FOG_COLOR[0], FOG_COLOR[1], FOG_COLOR[2], 1))
        fog.setLinearRange(15.0, 50.0)
        self.render.setFog(fog)

        # Load textures
        self._wall_tex = self._load_texture("assets/sprites/textures/wall_forbidden.png")
        self._door_tex = self._load_texture("assets/sprites/textures/door_forbidden.png")
        # Floor/ceiling — use wall as placeholder until dedicated textures land
        self._floor_tex = self._wall_tex
        self._ceil_tex = self._wall_tex

        # Build corridor
        self._build_corridor()
        self._update_hud()

        # Camera — far enough back to see all 8 doors
        self.cam.setPos(0, -CORRIDOR_DEPTH / 2 + 1, 2.5)
        self.cam.lookAt(0, DOOR_Y, 2.8)

        # Movement state
        self._keys = {"w": False, "s": False, "a": False, "d": False,
                       "arrow_left": False, "arrow_right": False}
        self._cam_h = 0.0

        # Controls
        for i in range(8):
            self.accept(str(i + 1), self._examine, [i])
            self.accept(f"shift-{i + 1}", self._try_door, [i])
        self.accept("escape", sys.exit)

        for key in self._keys:
            self.accept(key, self._set_key, [key, True])
            self.accept(f"{key}-up", self._set_key, [key, False])

        self.taskMgr.add(self._loop, "DungeonLoop")

        console.log("[bold cyan]THE GARDEN OF FORKING PATHS[/bold cyan]")
        console.log("8 doors. 7 attempts. Find the detail.")
        console.log("[WASD] move  [1-8] examine  [Shift+1-8] try door  [ESC] quit")

    def _setup_lighting(self):
        from panda3d.core import PointLight

        # Dim ambient — just enough to see shapes
        amb = AmbientLight("amb")
        amb.setColor(Vec4(0.03, 0.025, 0.03, 1))
        self.render.setLight(self.render.attachNewNode(amb))

        # Overhead directional — faint, gives top-face shading
        sun = DirectionalLight("sun")
        sun.setColor(Vec4(0.15, 0.12, 0.08, 1))
        sn = self.render.attachNewNode(sun)
        sn.setHpr(0, -70, 0)
        self.render.setLight(sn)

        # Wall sconces — point lights along both walls
        hw = CORRIDOR_WIDTH / 2 - 0.5
        sconce_y_positions = [-6, 0, 6]  # 3 pairs along corridor
        self._sconce_nodes = []
        for y in sconce_y_positions:
            for x_side in [-hw, hw]:
                lamp = PointLight(f"sconce_{x_side}_{y}")
                lamp.setColor(Vec4(1.0, 0.7, 0.35, 1))  # warm torch light
                lamp.setShadowCaster(True, 256, 256)
                lamp.setAttenuation((0.5, 0.08, 0.01))
                ln = self.render.attachNewNode(lamp)
                ln.setPos(x_side, y, WALL_HEIGHT * 0.7)
                self.render.setLight(ln)
                self._sconce_nodes.append(ln)

                # Visual sconce bracket (small box on wall)
                bracket = make_box(0.15, 0.15, 0.3, (0.2, 0.15, 0.1))
                bn = self.render.attachNewNode(bracket)
                bn.setPos(x_side, y, WALL_HEIGHT * 0.65)
                self._sconce_nodes.append(bn)

    def _load_texture(self, path):
        tex = self.loader.loadTexture(path)
        tex.setMagfilter(SamplerState.FT_nearest)
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setWrapU(SamplerState.WM_repeat)
        tex.setWrapV(SamplerState.WM_repeat)
        return tex

    def _clear_scene(self):
        for np in self._scene_nodes + self._door_nodes:
            try:
                np.removeNode()
            except Exception:
                pass
        self._scene_nodes = []
        self._door_nodes = []

    def _build_corridor(self):
        self._clear_scene()

        hw = CORRIDOR_WIDTH / 2
        hd = CORRIDOR_DEPTH / 2
        tile_x = CORRIDOR_DEPTH / WALL_HEIGHT  # tile proportionally

        # Floor — textured
        floor_tile = max(CORRIDOR_WIDTH, CORRIDOR_DEPTH) / 4.0
        floor_geom = make_textured_floor(CORRIDOR_WIDTH, CORRIDOR_DEPTH, tile_x=floor_tile, tile_y=floor_tile, name="floor")
        fn = self.render.attachNewNode(floor_geom)
        fn.setPos(0, 0, 0)
        fn.setTexture(self._floor_tex)
        fn.setTwoSided(True)
        self._scene_nodes.append(fn)

        # Ceiling — textured
        ceil_geom = make_textured_floor(CORRIDOR_WIDTH, CORRIDOR_DEPTH, tile_x=floor_tile, tile_y=floor_tile, name="ceiling")
        cn = self.render.attachNewNode(ceil_geom)
        cn.setPos(0, 0, WALL_HEIGHT)
        cn.setP(180)
        cn.setTexture(self._ceil_tex)
        cn.setTwoSided(True)
        self._scene_nodes.append(cn)

        # Left wall — textured quad facing +X (into corridor)
        lw_geom = make_textured_wall(CORRIDOR_DEPTH, WALL_HEIGHT, tile_x=tile_x, tile_y=1.0, name="left_wall")
        lw = self.render.attachNewNode(lw_geom)
        lw.setPos(-hw, 0, WALL_HEIGHT / 2)
        lw.setH(90)  # rotate to face inward
        lw.setTexture(self._wall_tex)
        lw.setTwoSided(True)
        self._scene_nodes.append(lw)

        # Right wall — textured quad facing -X (into corridor)
        rw_geom = make_textured_wall(CORRIDOR_DEPTH, WALL_HEIGHT, tile_x=tile_x, tile_y=1.0, name="right_wall")
        rw = self.render.attachNewNode(rw_geom)
        rw.setPos(hw, 0, WALL_HEIGHT / 2)
        rw.setH(-90)  # rotate to face inward
        rw.setTexture(self._wall_tex)
        rw.setTwoSided(True)
        self._scene_nodes.append(rw)

        # Far wall (behind doors) — textured, facing camera (-Y)
        fw_geom = make_textured_wall(CORRIDOR_WIDTH, WALL_HEIGHT, tile_x=CORRIDOR_WIDTH / WALL_HEIGHT, tile_y=1.0, name="far_wall")
        fw = self.render.attachNewNode(fw_geom)
        fw.setPos(0, DOOR_Y + 1.5, WALL_HEIGHT / 2)
        fw.setTexture(self._wall_tex)
        fw.setTwoSided(True)
        self._scene_nodes.append(fw)

        # 8 doors along far wall — textured quads
        self._door_nodes = []
        for i in range(8):
            x = (i - 3.5) * DOOR_SPACING
            door_geom = make_textured_quad(DOOR_WIDTH, DOOR_HEIGHT, name=f"door_{i}")
            np = self.render.attachNewNode(door_geom)
            np.setPos(x, DOOR_Y, DOOR_HEIGHT / 2)
            np.setTexture(self._door_tex)
            np.setTransparency(TransparencyAttrib.MAlpha)
            self._door_nodes.append(np)

            # Door number
            tn = TextNode(f"door_num_{i}")
            tn.setText(str(i + 1))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(0.4, 0.35, 0.3, 1)
            label = self.render.attachNewNode(tn)
            label.setPos(x, DOOR_Y - 0.2, DOOR_HEIGHT + 0.3)
            label.setScale(0.4)
            label.setBillboardPointEye()
            self._scene_nodes.append(label)

    def _examine(self, door_index):
        result = self._campaign.examine_door(door_index)
        if result["has_detail"]:
            self._show_message(f"Door {door_index + 1}: {result['description']}", 4.0)
            console.log(
                f"[bold green]DETAIL[/bold green]  Door {door_index + 1}: "
                f"{result['description']}  [dim]({result['detail_type']})[/dim]"
            )
        else:
            self._show_message(f"Door {door_index + 1}: A door. Like the others.", 2.0)

    def _try_door(self, door_index):
        result = self._campaign.try_door(door_index)

        if result.get("advanced"):
            self._show_message(
                f"The door opens. Corridor {result['corridor']}. "
                f"Tier: {result['tier']}.",
                3.0,
            )
            console.log(
                f"[bold green]ADVANCE[/bold green]  Corridor {result['corridor']}  "
                f"Tier {result['tier']}"
            )
            self._build_corridor()
        elif result.get("reset"):
            self._show_message(result["message"], 4.0)
            console.log(f"[bold red]RESET[/bold red]  {result['message']}")
            self._build_corridor()
        else:
            self._show_message(
                f"Door {door_index + 1} doesn't open. {result['message']}", 2.5
            )
            console.log(
                f"[yellow]WRONG[/yellow]  Door {door_index + 1}  "
                f"{result['attempts_remaining']} attempts left"
            )

        self._update_hud()

    def _set_key(self, key, value):
        self._keys[key] = value

    def _show_message(self, text, duration=2.0):
        self._message = text
        self._message_timer = duration

    def _update_hud(self):
        for n in self._hud:
            try:
                n.destroy()
            except Exception:
                pass
        self._hud = []

        r = self._campaign.report()
        lines = [
            f"Corridor {r['corridor']}   Tier {r['tier']} ({r['detail_type']})",
            f"Attempts: {'| ' * r['attempts']}  ({r['attempts']}/7)",
            f"Deepest: {r['deepest']}",
            "",
        ]

        if self._message:
            lines.append(self._message)
        else:
            lines.append("[1-8] examine   [Shift+1-8] try door")

        y = 0.92
        for line in lines:
            t = OnscreenText(
                text=line, pos=(-1.5, y), scale=0.048,
                fg=(0.75, 0.65, 0.55, 1),
                align=TextNode.ALeft, mayChange=True,
            )
            self._hud.append(t)
            y -= 0.07

    def _loop(self, task):
        dt = globalClock.getDt()

        # Turning
        if self._keys["arrow_left"] or self._keys["a"]:
            self._cam_h += TURN_SPEED * dt
        if self._keys["arrow_right"] or self._keys["d"]:
            self._cam_h -= TURN_SPEED * dt

        # Forward / backward relative to heading
        import math
        heading_rad = math.radians(self._cam_h)
        forward_x = -math.sin(heading_rad)
        forward_y = math.cos(heading_rad)

        dx, dy = 0.0, 0.0
        if self._keys["w"]:
            dx += forward_x * MOVE_SPEED * dt
            dy += forward_y * MOVE_SPEED * dt
        if self._keys["s"]:
            dx -= forward_x * MOVE_SPEED * dt
            dy -= forward_y * MOVE_SPEED * dt

        pos = self.cam.getPos()
        hw = CORRIDOR_WIDTH / 2 - 0.5
        hd = CORRIDOR_DEPTH / 2 - 0.5
        new_x = max(-hw, min(hw, pos.getX() + dx))
        new_y = max(-hd, min(hd, pos.getY() + dy))
        self.cam.setPos(new_x, new_y, pos.getZ())
        self.cam.setH(self._cam_h)

        # Message timer
        if self._message_timer > 0:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self._message = ""
                self._update_hud()
        return task.cont


if __name__ == "__main__":
    Dungeon().run()
