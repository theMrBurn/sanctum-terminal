# interfaces/atlas_3d.py
import os
from pathlib import Path
from ursina import Ursina, Entity, color, window, camera, Vec3, application
from engines.world import WorldEngine


class Atlas3D:
    def __init__(self, session):
        root_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        application.asset_folder = root_dir

        # Initialize with 'Zero-Shader' Safe Mode
        self.app = Ursina(
            title="SANCTUM_OS // NEURAL_RENDER",
            development_mode=False,
            shader=None,  # KILL SHADERS AT THE ROOT
        )

        self.session = session
        self.world = WorldEngine(self.session.seed)

        window.color = color.black
        window.borderless = False

        # The Voxel Cache (Witnessing the Global WorldEngine)
        self.voxels = {}
        self.player_rep = Entity(
            model="cube", color=color.white, scale=(0.8, 1.8, 0.8), position=(25, 2, 25)
        )

        # We use a simple background color instead of a Sky object to avoid shaders
        camera.clip_plane_far = 100
        self.app.update = self.update_sync

    def update_sync(self):
        s = self.session
        if s.active_container:
            return

        # Global Logic Sync
        self.player_rep.position = Vec3(s.pos[0], 1, s.pos[2])
        camera.position = self.player_rep.position + Vec3(0, 15, -15)
        camera.look_at(self.player_rep)

        # Rendering from the Global Kernel
        px, pz = int(s.pos[0]), int(s.pos[2])
        for z in range(pz - 5, pz + 6):
            for x in range(px - 5, px + 6):
                if (x, z) not in self.voxels:
                    node = self.world.get_node(x, z, s)

                    # Material-Aware Voxel
                    v = Entity(
                        model="cube",
                        position=(x, node["pos"][1], z),
                        scale=(1, 1, 1),
                        color=color.rgb(*node["color"]),
                    )

                    # Restoring 'Tree' functionality
                    if node["char"] == "f":
                        Entity(
                            parent=v,
                            model="cube",
                            y=1.2,
                            color=color.rgb(20, 80, 20),
                            scale=(0.6, 1.2, 0.6),
                        )

                    self.voxels[(x, z)] = v

    def run_bridge(self):
        self.app.run()
