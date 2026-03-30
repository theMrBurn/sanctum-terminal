"""
simulation_theater.py

Watch a scripted quest auto-play in a realized biome.

The Monk walks through a VERDANT forest, picks up a torch,
encounter fires, XP stages, scenario completes. You watch.

Usage:
    make theater
    # or
    PYTHONPATH=. .venv/bin/python simulation_theater.py
"""

import sys
import time as _time
from pathlib import Path

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight, DirectionalLight, Vec4,
    WindowProperties, TextNode, AntialiasAttrib, Fog,
    NodePath,
)
from rich.console import Console

from core.systems.biome_scene import BiomeSceneBuilder
from core.systems.sprite_renderer import SpriteRenderer
from core.systems.avatar_pipeline import AvatarPipeline
from core.systems.scenario_engine import ScenarioEngine
from core.systems.interaction_engine import InteractionEngine
from core.systems.inventory import Inventory
from core.systems.pickup_system import PickupSystem
from core.systems.model_loader import ModelLoader
from core.systems.geometry import make_box as _make_box_geom

console = Console()

# -- Quest script --------------------------------------------------------------

QUEST_SCRIPT = [
    # (action, args, duration_seconds)
    ("log",     "The Monk enters the forest.",              0.0),
    ("wait",    None,                                       2.0),
    ("log",     "Something catches the light ahead.",       0.0),
    ("move",    (8, 15, 0),                                 3.0),
    ("log",     "A torch. Still warm.",                     0.0),
    ("wait",    None,                                       1.5),
    ("pickup",  None,                                       0.5),
    ("log",     "The encounter resonates.",                 0.0),
    ("wait",    None,                                       1.0),
    ("stow",    None,                                       0.5),
    ("log",     "Stowed. The world remembers.",             0.0),
    ("wait",    None,                                       2.0),
    ("move",    (0, 0, 0),                                  3.0),
    ("log",     "Quest complete. Provenance recorded.",     0.0),
    ("wait",    None,                                       3.0),
]


class SimulationTheater(ShowBase):
    """
    Headed auto-play. Watch a quest run in a biome.
    No input needed. The Monk moves on its own.
    """

    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum -- Simulation Theater")
        props.setSize(1280, 720)
        self.win.requestProperties(props)

        self.setBackgroundColor(0.03, 0.06, 0.03, 1)
        self.disableMouse()
        self.camLens.setFov(75)
        self.cam.setPos(0, -20, 8)
        self.cam.lookAt(0, 10, 2)
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        # Lighting
        sun = DirectionalLight("sun")
        sun.setColor(Vec4(1.2, 0.9, 0.6, 1))
        sun.setShadowCaster(True, 1024, 1024)
        sn = self.render.attachNewNode(sun)
        sn.setHpr(15, -55, 0)
        self.render.setLight(sn)

        amb = AmbientLight("amb")
        amb.setColor(Vec4(0.08, 0.10, 0.06, 1))
        self.render.setLight(self.render.attachNewNode(amb))

        # Fog
        fog = Fog("theater_fog")
        fog.setColor(Vec4(0.08, 0.12, 0.06, 1))
        fog.setLinearRange(20.0, 80.0)
        self.render.setFog(fog)

        # Scene layers
        self.layer_scene = self.render.attachNewNode("layer_scene")

        # Build biome
        self._biome = BiomeSceneBuilder(
            self.layer_scene, seed=42, radius=50.0, panda_loader=self.loader
        )
        self._biome.build("VERDANT", register="survival")

        # Sprite renderer
        self._sprites = SpriteRenderer(self.render, self.loader)

        # Monk sprite
        self._monk = self._sprites.spawn_sprite("monk", pos=(0, 0, 0), scale=4.0)
        self._monk_pos = [0.0, 0.0, 0.0]
        self._monk_target = None

        # Pipeline
        self._pipeline = AvatarPipeline(
            answers={"q1": "nature", "q8": "seeker"}, age=30, seed="THEATER"
        )
        for _ in range(5):
            self._pipeline.fingerprint.record("precision_score", 0.9)
            self._pipeline.fingerprint.record("observation_time", 0.8)
        self._pipeline.refresh_blend()

        # Scenario engine
        self._se = ScenarioEngine(seed="THEATER")
        self._inventory = Inventory()

        # Spawn target object (torch compound rendered as Kenney model)
        self._target_pos = (8, 15, 0)
        ml = ModelLoader(self.loader)
        self._target_node = ml.load("campfire")
        if self._target_node:
            self._target_node.reparentTo(self.layer_scene)
            self._target_node.setPos(*self._target_pos)

        # Create fetch scenario
        self._target_id = "theater_torch"
        self._sid = self._se.create(
            "fetch",
            {"target_id": self._target_id, "return_pos": (0, 0, 0),
             "objective": "Retrieve the torch from the forest."},
            win_fn=lambda: self._inventory.get(self._target_id) is not None,
        )
        self._se.activate(self._sid)

        # HUD
        self._hud = []
        self._log_lines = []

        # Script execution
        self._script = list(QUEST_SCRIPT)
        self._script_idx = 0
        self._script_wait = 0.0
        self._elapsed = 0.0

        # Start game loop
        self.taskMgr.add(self._theater_loop, "TheaterLoop")
        self.accept("escape", sys.exit)

        console.log("[bold cyan]SIMULATION THEATER[/bold cyan]")
        console.log("Watch the Monk. No input needed.")

    def _theater_loop(self, task):
        dt = globalClock.getDt()
        self._elapsed += dt

        # Move monk toward target
        if self._monk_target:
            mx, my, mz = self._monk_pos
            tx, ty, tz = self._monk_target
            dx, dy = tx - mx, ty - my
            dist = (dx**2 + dy**2) ** 0.5
            if dist > 0.3:
                speed = 5.0
                nx = mx + (dx / dist) * speed * dt
                ny = my + (dy / dist) * speed * dt
                self._monk_pos = [nx, ny, 0.0]
                self._monk.setPos(nx, ny, 0)
                self._sprites.animate(self._monk, "monk_walk", dt)
                # Camera follows
                self.cam.setPos(nx - 5, ny - 18, 8)
                self.cam.lookAt(nx, ny + 5, 2)
            else:
                self._monk_pos = [tx, ty, 0.0]
                self._monk.setPos(tx, ty, 0)
                self._monk_target = None
                self._sprites.animate(self._monk, "monk_idle", dt)
        else:
            self._sprites.animate(self._monk, "monk_idle", dt)

        # Script execution
        if self._script_wait > 0:
            self._script_wait -= dt
        elif self._script_idx < len(self._script):
            action, args, duration = self._script[self._script_idx]
            self._script_idx += 1

            if action == "log":
                self._add_log(args)
                console.log(f"[dim]{args}[/dim]")
            elif action == "wait":
                self._script_wait = duration
            elif action == "move":
                self._monk_target = args
                self._script_wait = duration
            elif action == "pickup":
                if self._target_node and not self._target_node.isEmpty():
                    self._target_node.hide()
                self._add_log("  [E] picked up")
                self._script_wait = duration
                # Begin encounter
                entity = {"id": self._target_id,
                          "tags": ["crafting_time", "precision_score"],
                          "type": "object"}
                worth = self._pipeline.encounter.begin(entity)
                if worth:
                    verb = self._pipeline.encounter.dominant_verb()
                    self._pipeline.encounter.choose(verb)
                    self._add_log(f"  ENCOUNTER: resonant, verb={verb}")
                    console.log(f"[bold magenta]ENCOUNTER[/bold magenta] verb={verb}")
            elif action == "stow":
                result = self._pipeline.encounter.resolve()
                self._inventory.add({"id": self._target_id, "weight": 0.4})
                self._se.tick()
                state = self._se.get_state(self._sid)
                self._add_log(f"  RESOLVED: xp={result['xp_staged']:.2f}")
                self._add_log(f"  SCENARIO: {state.name}")
                console.log(
                    f"[bold green]RESOLVED[/bold green] xp={result['xp_staged']:.2f} "
                    f"scenario={state.name}"
                )
                self._script_wait = duration

        # Update HUD
        self._update_hud()

        return task.cont

    def _add_log(self, text):
        self._log_lines.append(text)
        if len(self._log_lines) > 8:
            self._log_lines = self._log_lines[-8:]

    def _update_hud(self):
        for n in self._hud:
            try:
                n.destroy()
            except Exception:
                pass
        self._hud = []

        state = self._se.get_state(self._sid)
        lines = [
            "SIMULATION THEATER",
            f"BIOME: VERDANT  SCENARIO: {state.name if state else '--'}",
            f"ELAPSED: {self._elapsed:.1f}s",
            "",
        ] + self._log_lines

        y = 0.92
        for line in lines:
            t = OnscreenText(
                text=line, pos=(-1.5, y), scale=0.044,
                fg=(0.85, 0.80, 0.72, 1),
                align=TextNode.ALeft, mayChange=True
            )
            self._hud.append(t)
            y -= 0.06


if __name__ == "__main__":
    SimulationTheater().run()
