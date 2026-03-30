"""
dungeon.py

The 7-Door Dungeon -- playable Wizardry-style corridor crawl.

8 doors. 7 attempts. 1 minute detail. Find it.

Controls:
    1-8     Examine door (free, no cost)
    Shift+1-8  Try door (costs an attempt if wrong)
    ESC     Quit

Usage:
    make dungeon
"""

import sys
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight, DirectionalLight, Vec4, Vec3,
    WindowProperties, TextNode, AntialiasAttrib,
    Fog, Material,
)
from rich.console import Console

from core.systems.dungeon_campaign import DungeonCampaign
from core.systems.dungeon_grid import DungeonGrid
from core.systems.geometry import make_box, make_plane

console = Console()

# -- Visual constants ----------------------------------------------------------

CORRIDOR_WIDTH  = 12.0
CORRIDOR_DEPTH  = 20.0
WALL_HEIGHT     = 8.0
DOOR_WIDTH      = 1.2
DOOR_HEIGHT     = 2.5
DOOR_SPACING    = CORRIDOR_WIDTH / 4.5
DOOR_Y          = CORRIDOR_DEPTH / 2 - 1.0

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
        fog.setLinearRange(5.0, 35.0)
        self.render.setFog(fog)

        # Build corridor
        self._build_corridor()
        self._update_hud()

        # Camera
        self.cam.setPos(0, -CORRIDOR_DEPTH / 2 + 2, 3.0)
        self.cam.lookAt(0, DOOR_Y, 3.0)

        # Controls
        for i in range(8):
            self.accept(str(i + 1), self._examine, [i])
            self.accept(f"shift-{i + 1}", self._try_door, [i])
        self.accept("escape", sys.exit)

        self.taskMgr.add(self._loop, "DungeonLoop")

        console.log("[bold cyan]THE GARDEN OF FORKING PATHS[/bold cyan]")
        console.log("8 doors. 7 attempts. Find the detail.")
        console.log("[1-8] examine  [Shift+1-8] try door  [ESC] quit")

    def _setup_lighting(self):
        sun = DirectionalLight("sun")
        sun.setColor(Vec4(0.6, 0.45, 0.3, 1))
        sun.setShadowCaster(True, 512, 512)
        sn = self.render.attachNewNode(sun)
        sn.setHpr(0, -60, 0)
        self.render.setLight(sn)

        fill = DirectionalLight("fill")
        fill.setColor(Vec4(0.08, 0.10, 0.15, 1))
        fn = self.render.attachNewNode(fill)
        fn.setHpr(180, -30, 0)
        self.render.setLight(fn)

        amb = AmbientLight("amb")
        amb.setColor(Vec4(0.04, 0.03, 0.04, 1))
        self.render.setLight(self.render.attachNewNode(amb))

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

        # Floor
        floor = make_plane(int(CORRIDOR_WIDTH), int(CORRIDOR_DEPTH), FLOOR_COLOR)
        fn = self.render.attachNewNode(floor)
        fn.setPos(0, 0, 0)
        self._scene_nodes.append(fn)

        # Ceiling
        ceil = make_plane(int(CORRIDOR_WIDTH), int(CORRIDOR_DEPTH), CEILING_COLOR)
        cn = self.render.attachNewNode(ceil)
        cn.setPos(0, 0, WALL_HEIGHT)
        cn.setP(180)
        self._scene_nodes.append(cn)

        # Left wall
        lw = make_box(0.3, WALL_HEIGHT, CORRIDOR_DEPTH, WALL_COLOR)
        ln = self.render.attachNewNode(lw)
        ln.setPos(-hw, 0, WALL_HEIGHT / 2)
        self._scene_nodes.append(ln)

        # Right wall
        rw = make_box(0.3, WALL_HEIGHT, CORRIDOR_DEPTH, WALL_COLOR)
        rn = self.render.attachNewNode(rw)
        rn.setPos(hw, 0, WALL_HEIGHT / 2)
        self._scene_nodes.append(rn)

        # Far wall (behind doors)
        bw = make_box(CORRIDOR_WIDTH, WALL_HEIGHT, 0.3, WALL_COLOR)
        bn = self.render.attachNewNode(bw)
        bn.setPos(0, DOOR_Y + 1.5, WALL_HEIGHT / 2)
        self._scene_nodes.append(bn)

        # 8 doors along far wall
        self._door_nodes = []
        for i in range(8):
            x = (i - 3.5) * DOOR_SPACING
            door = self._campaign.scene.doors[i]

            color = DOOR_COLOR
            geom = make_box(DOOR_WIDTH, DOOR_HEIGHT, 0.15, color)
            np = self.render.attachNewNode(geom)
            np.setPos(x, DOOR_Y, DOOR_HEIGHT / 2)
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
        if self._message_timer > 0:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self._message = ""
                self._update_hud()
        return task.cont


if __name__ == "__main__":
    Dungeon().run()
