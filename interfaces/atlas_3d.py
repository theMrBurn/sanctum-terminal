# interfaces/atlas_3d.py
import os
from pathlib import Path
from ursina import Ursina, Entity, color, window, camera, Vec3, application
from engines.world import WorldEngine


class Atlas3D:
    def __init__(self, session):
        root_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        application.asset_folder = root_dir

        # Initialize Ursina
        self.app = Ursina(title="SANCTUM_OS // NEURAL_RENDER", development_mode=False)

        # HARD FIX: Override Ursina's default shader at the source
        from ursina import shader

        shader.default_shader = None

        self.session = session
        self.world = WorldEngine(self.session.seed)
        window.color = color.black

        self.voxels = {}
        # Player as a simple sphere to see if primitives are the issue
        self.player_rep = Entity(model="sphere", color=color.white, scale=0.5)

        self.app.update = self.update_sync

    def update_sync(self):
        s = self.session
        if s.active_container:
            return

        self.player_rep.position = Vec3(s.pos[0], 1, s.pos[2])
        camera.position = self.player_rep.position + Vec3(0, 15, -15)
        camera.look_at(self.player_rep)

        # 3x3 Render - ultra tiny to test stability
        px, pz = int(s.pos[0]), int(s.pos[2])
        for z in range(pz - 1, pz + 2):
            for x in range(px - 1, px + 2):
                if (x, z) not in self.voxels:
                    node = self.world.get_node(x, z, s)
                    # We are using 'plane' because it's the simplest mesh
                    v = Entity(
                        model="plane",
                        position=(x, node["pos"][1], z),
                        scale=1,
                        color=color.rgb(*node["color"]),
                    )
                    self.voxels[(x, z)] = v

    def run_bridge(self):
        self.app.run()
