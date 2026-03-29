import sys, json, random
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight, DirectionalLight, Vec4,
    WindowProperties, TextNode, AntialiasAttrib
)
from rich.console import Console
from core.systems.biome_renderer import _make_box_geom, _make_plane_geom
from core.systems.crafting_engine import CraftingEngine
from core.systems.primitive_factory import PrimitiveFactory
from core.systems.inventory import Inventory
from core.systems.pickup_system import PickupSystem, PICKUP_RADIUS

console = Console()
MOUSE_SENSITIVITY = 0.15
PITCH_CLAMP       = 80.0
SNAP_THRESHOLD    = 200
GROUND_Z          = 5.0

# Weight by role -- what a thing is determines how much it costs to carry.
# The Long Dark model: no arbitrary numbers, just material truth.
_ROLE_WEIGHT = {
    "handle":    0.3,
    "edge":      0.4,
    "cover":     0.2,
    "material":  0.8,
    "surface":   2.0,
    "container": 0.3,
    "blank":     1.0,
    "marker":    0.6,
    "fuel":      0.5,
}
_DEFAULT_WEIGHT = 0.5


class CreationLab(ShowBase):
    """
    White void creation lab.
    Inspect, combine, and hash objects.
    Workbench accepts two objects -- outputs crafted result.
    [E] lift / stow.  [G] drop.  [C] craft.  [X] clear.
    """

    def __init__(self):
        super().__init__()
        props = WindowProperties()
        props.setTitle("Sanctum -- Creation Lab")
        props.setSize(1280, 720)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.92, 0.90, 0.88, 1)

        self.cam_yaw   = 0.0
        self.cam_pitch = 0.0
        self.mouse_look_active = False
        self._last_mx  = None
        self._last_my  = None
        self.key_map   = {"w": False, "s": False, "a": False, "d": False}

        self.engine  = CraftingEngine()
        self.factory = PrimitiveFactory()
        self.slot_a  = None
        self.slot_b  = None
        self._hud    = []

        self._objects  = self.engine.get_all_objects()
        self._obj_keys = list(self._objects.keys())
        self._spawned  = []   # [{"node": np, "key": key, "obj": dict}]

        # -- Inventory + PickupSystem
        self.inventory = Inventory()
        self.pickup    = PickupSystem(
            camera         = self.cam,
            inventory      = self.inventory,
            get_nearest_fn = self._nearest_pickupable,
            on_held_fn     = self._on_held,
            on_stowed_fn   = self._on_stowed,
            on_dropped_fn  = self._on_dropped,
            on_fail_fn     = self._on_pickup_fail,
        )

        self.disableMouse()
        self.camLens.setFov(75)
        self.cam.setPos(0, -20, GROUND_Z)
        self.cam.setHpr(0, -5, 0)
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        self.setup_lighting()
        self.setup_controls()
        self._build_lab()
        self._update_hud()
        self.taskMgr.add(self.game_loop, "GameLoop")

        self.accept("escape",       self.disable_mouse_look)
        self.accept("shift-escape", self.exit_app)
        self.accept("mouse1",       self.enable_mouse_look)

        console.log("[bold cyan]CREATION LAB[/bold cyan]")
        console.log("WSAD move | mouse look | [E] lift/stow | [G] drop")
        console.log("1-9 spawn | [C] craft | [X] clear | Shift+ESC quit")

    # -- Lab geometry ----------------------------------------------------------

    def _build_lab(self):
        fn = _make_plane_geom(120, 120, (0.88, 0.86, 0.84))
        self.render.attachNewNode(fn).setPos(0, 0, 0)

        for i in range(-5, 6):
            gn = _make_box_geom(0.05, 0.02, 10, (0.75, 0.73, 0.71))
            self.render.attachNewNode(gn).setPos(i*2, 0, 0.01)
            gn2 = _make_box_geom(10, 0.02, 0.05, (0.75, 0.73, 0.71))
            self.render.attachNewNode(gn2).setPos(0, i*2, 0.01)

        wn = _make_box_geom(3.0, 0.6, 2.0, (0.22, 0.18, 0.14))
        self.render.attachNewNode(wn).setPos(0, 0, 0.3)

        an = _make_box_geom(0.8, 0.05, 0.8, (0.4, 0.35, 0.28))
        self.render.attachNewNode(an).setPos(-0.8, 0, 0.61)

        bn = _make_box_geom(0.8, 0.05, 0.8, (0.4, 0.35, 0.28))
        self.render.attachNewNode(bn).setPos(0.8, 0, 0.61)

        on2 = _make_box_geom(0.8, 0.05, 0.8, (0.3, 0.45, 0.35))
        self.render.attachNewNode(on2).setPos(0, -1.2, 0.66)

        sn = _make_box_geom(20, 0.3, 1.5, (0.55, 0.52, 0.48))
        self.render.attachNewNode(sn).setPos(0, 8, 0.75)

        for i, key in enumerate(self._obj_keys[:9]):
            self._spawn_on_shelf(key, i)

    # -- Spawn -----------------------------------------------------------------

    def _make_obj_dict(self, obj_key):
        """
        Inject id and weight into the catalog entry.
        Weight is derived from role -- material truth, not database field.
        """
        obj = dict(self._objects[obj_key])
        obj["id"]     = obj_key
        obj["weight"] = _ROLE_WEIGHT.get(obj.get("role", ""), _DEFAULT_WEIGHT)
        return obj

    def _spawn_on_shelf(self, obj_key, index):
        raw = self._objects.get(obj_key)
        if not raw:
            return
        obj = self._make_obj_dict(obj_key)
        try:
            p  = self.factory.build(
                raw["primitive"], tuple(raw["scale"]),
                tuple(raw["color"]), role=raw["role"]
            )
            np = self.render.attachNewNode(p.geom_node)
            x  = (index - 4) * 2.2
            np.setPos(x, 8, 1.5)
            np.setHpr(index * 15, 0, 0)
            np.setPythonTag("pickupable", True)
            np.setPythonTag("obj", obj)
            self._spawned.append({"node": np, "key": obj_key, "obj": obj})
        except Exception as e:
            console.log(f"[yellow]SPAWN:[/yellow] {obj_key} -- {e}")

    def _spawn_object(self, obj_key):
        raw = self._objects.get(obj_key)
        if not raw:
            console.log(f"[red]Unknown object:[/red] {obj_key}")
            return
        obj = self._make_obj_dict(obj_key)
        try:
            p  = self.factory.build(
                raw["primitive"], tuple(raw["scale"]),
                tuple(raw["color"]), role=raw["role"]
            )
            np = self.render.attachNewNode(p.geom_node)
            np.setPos(-3, -2, 1.0)
            np.setPythonTag("pickupable", True)
            np.setPythonTag("obj", obj)
            self._spawned.append({"node": np, "key": obj_key, "obj": obj})

            if self.slot_a is None:
                self.slot_a = obj_key
                np.setPos(-0.8, 0, 1.2)
                console.log(f"[green]Slot A:[/green] {obj_key}")
            elif self.slot_b is None:
                self.slot_b = obj_key
                np.setPos(0.8, 0, 1.2)
                console.log(f"[green]Slot B:[/green] {obj_key}")
            self._update_hud()
        except Exception as e:
            console.log(f"[red]SPAWN ERROR:[/red] {e}")

    # -- Nearest pickupable ----------------------------------------------------

    def _nearest_pickupable(self):
        """
        Returns {"obj": dict, "node": NodePath} for the closest pickupable
        within PICKUP_RADIUS, or None.
        Skips hidden nodes (already stowed).
        """
        cam_pos  = self.cam.getPos(self.render)
        best     = None
        best_dist = PICKUP_RADIUS

        for entry in self._spawned:
            np = entry["node"]
            if np.isHidden():
                continue
            if not np.getPythonTag("pickupable"):
                continue
            p    = np.getPos(self.render)
            dist = (
                (p.x - cam_pos.x) ** 2 +
                (p.y - cam_pos.y) ** 2
            ) ** 0.5
            if dist < best_dist:
                best      = entry
                best_dist = dist

        if best is None:
            return None
        return {"obj": best["obj"], "node": best["node"]}

    # -- Pickup callbacks ------------------------------------------------------

    def _on_held(self, obj):
        console.log(
            f"[cyan]holding[/cyan]  {obj['id']}  "
            f"[dim]{obj.get('description', '')}[/dim]"
        )
        self._update_hud()

    def _on_stowed(self, obj):
        console.log(
            f"[green]stowed[/green]   {obj['id']}  "
            f"[dim]{self.inventory.count()}/{self.inventory.max_slots} slots[/dim]"
        )
        self._update_hud()

    def _on_dropped(self, obj):
        console.log(f"[yellow]dropped[/yellow]  {obj['id']}")
        self._update_hud()

    def _on_pickup_fail(self, reason):
        messages = {
            "nothing_nearby": "[dim]nothing within reach[/dim]",
            "inventory_full": "[red]carrying too much[/red]",
        }
        console.log(messages.get(reason, reason))

    # -- Craft / clear ---------------------------------------------------------

    def _craft(self):
        if not self.slot_a or not self.slot_b:
            console.log("[yellow]need two objects in slots to craft[/yellow]")
            return
        result = self.engine.craft(self.slot_a, self.slot_b)
        console.log(f"[bold green]CRAFTED:[/bold green] {result['name']}")
        console.log(f"  {result['description']}")
        console.log(f"  ability: {result['ability']}")
        console.log(f"  hash: {result['provenance_hash']}")
        color = (0.6, 0.8, 0.5)
        rn    = _make_box_geom(0.6, 0.6, 0.6, color)
        rp    = self.render.attachNewNode(rn)
        rp.setPos(0, -1.2, 1.2)
        self.slot_a = None
        self.slot_b = None
        self._update_hud(result)

    def _clear(self):
        self.slot_a = None
        self.slot_b = None
        self._update_hud()
        console.log("[dim]slots cleared[/dim]")

    # -- HUD -------------------------------------------------------------------

    def _update_hud(self, result=None):
        for node in self._hud:
            try: node.destroy()
            except: pass
        self._hud = []

        held = self.pickup.held_obj
        lines = [
            f"SLOT A: {self.slot_a or 'empty'}",
            f"SLOT B: {self.slot_b or 'empty'}",
            "",
            f"HELD:   {held['id'] if held else '--'}",
            f"BAG:    {self.inventory.count()}/{self.inventory.max_slots}"
            f"  {self.inventory.current_weight():.1f}kg",
            "",
            "[E] lift/stow  [G] drop  [C] craft  [X] clear",
        ]
        if result:
            lines += [
                "",
                f">> {result['name']}",
                result["description"],
                f"ability: {result['ability']}",
            ]

        y = 0.85
        for line in lines:
            t = OnscreenText(
                text=line, pos=(-1.5, y), scale=0.048,
                fg=(0.15, 0.12, 0.10, 1),
                align=TextNode.ALeft, mayChange=True
            )
            self._hud.append(t)
            y -= 0.07

    # -- Lighting --------------------------------------------------------------

    def setup_lighting(self):
        sun = DirectionalLight("sun")
        sun.setColor(Vec4(1.0, 0.98, 0.94, 1))
        sn = self.render.attachNewNode(sun)
        sn.setHpr(30, -50, 0)
        self.render.setLight(sn)

        fill = DirectionalLight("fill")
        fill.setColor(Vec4(0.5, 0.55, 0.65, 1))
        fn = self.render.attachNewNode(fill)
        fn.setHpr(210, -30, 0)
        self.render.setLight(fn)

        amb = AmbientLight("amb")
        amb.setColor(Vec4(0.55, 0.52, 0.48, 1))
        self.render.setLight(self.render.attachNewNode(amb))

    # -- Controls --------------------------------------------------------------

    def setup_controls(self):
        for key in self.key_map:
            self.accept(key,         self.update_key_map, [key, True])
            self.accept(f"{key}-up", self.update_key_map, [key, False])
        self.accept("e", self.pickup.on_e_pressed)
        self.accept("g", self.pickup.on_drop_pressed)
        self.accept("c", self._craft)
        self.accept("x", self._clear)
        for i in range(9):
            self.accept(str(i + 1), self._spawn_by_number, [i])

    def _spawn_by_number(self, index):
        if index < len(self._obj_keys):
            self._spawn_object(self._obj_keys[index])

    def update_key_map(self, key, val):
        self.key_map[key] = val

    # -- Mouse look ------------------------------------------------------------

    def enable_mouse_look(self):
        self.mouse_look_active = True
        self._last_mx = None
        self._last_my = None
        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

    def disable_mouse_look(self):
        self.mouse_look_active = False
        props = WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

    # -- Game loop -------------------------------------------------------------

    def game_loop(self, task):
        dt = globalClock.getDt()

        if self.mouse_look_active and self.mouseWatcherNode.hasMouse():
            md = self.win.getPointer(0)
            mx, my = md.getX(), md.getY()
            if self._last_mx is not None:
                dx = mx - self._last_mx
                dy = my - self._last_my
                if abs(dx) < SNAP_THRESHOLD and abs(dy) < SNAP_THRESHOLD:
                    self.cam_yaw   -= dx * MOUSE_SENSITIVITY
                    self.cam_pitch -= dy * MOUSE_SENSITIVITY
                    self.cam_pitch  = max(-PITCH_CLAMP, min(PITCH_CLAMP, self.cam_pitch))
                    self.cam.setHpr(self.cam_yaw, self.cam_pitch, 0)
            self._last_mx, self._last_my = mx, my

        if self.key_map["w"]: self.cam.setPos(self.cam, 0,  12.0 * dt, 0)
        if self.key_map["s"]: self.cam.setPos(self.cam, 0, -12.0 * dt, 0)
        if self.key_map["a"]: self.cam.setPos(self.cam, -12.0 * dt, 0, 0)
        if self.key_map["d"]: self.cam.setPos(self.cam,  12.0 * dt, 0, 0)

        self.pickup.update(dt)

        return task.cont

    def exit_app(self):
        sys.exit(0)


if __name__ == "__main__":
    CreationLab().run()
