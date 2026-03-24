import pygame, moderngl, time, argparse, sys, zlib
import numpy as np
from spatial_utils import RelativityCamera
from core.vault import Vault
from systems.volume import Volume
from input_handler import InputHandler
from renderer_handler import RenderHandler


class SanctumViewport:
    def __init__(self, max_voxels_m=11):
        print(">>> [SYSTEM] Initializing Pygame...")
        pygame.display.init()
        pygame.font.init()

        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
        )

        self.win_size = (1280, 720)
        print(">>> [SYSTEM] Creating Window...")
        self.screen = pygame.display.set_mode(
            self.win_size, pygame.OPENGL | pygame.DOUBLEBUF
        )

        print(">>> [SYSTEM] Creating ModernGL Context...")
        self.ctx = moderngl.create_context()

        print(">>> [SYSTEM] Initializing Vault & Renderer...")
        self.render = RenderHandler(self.ctx)
        self.vault = Vault(ctx=self.ctx, max_reserve=int(max_voxels_m * 1_000_000))

        # Start 2m high to see the floor grid immediately
        self.world_offset = np.array([0.0, 0.0, 0.0], dtype="f4")
        self.current_loc_key = None
        self.fullscreen = False

        self.camera = RelativityCamera([0, 2, 0])
        self.inputs = InputHandler()
        self.font = pygame.font.SysFont("Monaco", 22)
        self.hud_vao = self.render.build_hud_vao()
        self.clock = pygame.time.Clock()
        self.start_time = time.time()

        pygame.mouse.set_visible(True)

    def update_location_exchange(self, current_time):
        center_x = (self.world_offset[0] // 64.0) * 64.0
        center_z = (self.world_offset[2] // 64.0) * 64.0

        combined_key = zlib.adler32(np.array([center_x, center_z]).tobytes())

        if combined_key != self.current_loc_key:
            self.current_loc_key = combined_key
            all_voxels = []

            # RADIUS SCAN: Fetch 3x3 set of 64m volumes
            for dx in [-64.0, 0.0, 64.0]:
                for dz in [-64.0, 0.0, 64.0]:
                    origin = [center_x + dx, 0.0, center_z + dz]
                    vol = Volume(origin)

                    vel_mag = np.linalg.norm(self.inputs.velocity)
                    seed_mod = 666 if vel_mag > 15.0 else 0

                    vdata = vol.hydrate(current_time, biome_seed=seed_mod)
                    all_voxels.append(vdata)

            final_payload = np.vstack(all_voxels).astype("f4")
            # Push straight to the GPU bridge
            self.vault.update_vbo(final_payload, self.render.prog)

    def update(self, dt, current_time):
        dt = min(dt, 0.033)
        v, l = self.inputs.get_movement(dt), self.inputs.get_look(dt)
        self.camera.update_orientation(l[0], l[1])

        fwd = np.array([self.camera.front.x, 0, self.camera.front.z], dtype="f4")
        mag = np.linalg.norm(fwd)
        if mag > 1e-5:
            fwd /= mag
        right = np.array([fwd[2], 0, -fwd[0]], dtype="f4")

        self.world_offset += (fwd * v[0] + right * v[1]) * dt
        self.update_location_exchange(current_time)

    def run(self):
        print(">>> [SYSTEM] Handshake Complete. Entering Run Loop.")
        # Force a pump to help macOS window focus
        pygame.event.pump()

        while True:
            current_time = time.time() - self.start_time
            dt = self.clock.tick(144) / 1000.0

            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return

                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_RIGHTBRACKET or e.key == pygame.K_BACKSLASH:
                        self.fullscreen = not self.fullscreen
                        if self.fullscreen:
                            pygame.display.set_mode(
                                (0, 0),
                                pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN,
                            )
                        else:
                            pygame.display.set_mode(
                                self.win_size, pygame.OPENGL | pygame.DOUBLEBUF
                            )

            self.update(dt, current_time)

            # Frame math
            mvp = self.camera.get_projection() * self.camera.get_view_matrix()
            view_origin = self.world_offset + np.array([0.0, 2.0, 0.0], dtype="f4")
            vel_mag = np.linalg.norm(self.inputs.velocity)
            hud_tex = self.create_hud()

            self.render.render_frame(
                self.vault,
                mvp,
                view_origin,
                current_time,
                vel_mag,
                hud_tex,
                self.hud_vao,
            )

            pygame.display.flip()
            hud_tex.release()

    def create_hud(self):
        cur_w, cur_h = self.screen.get_size()
        surf = pygame.Surface((cur_w, cur_h), pygame.SRCALPHA)
        telemetry = [
            f"SANCTUM PROTOCOL | ACTIVE",
            f"LOCATION KEY: {self.current_loc_key}",
            f"COORDS: {self.world_offset[0]:.1f}, {self.world_offset[2]:.1f}",
            f"VELOCITY: {np.linalg.norm(self.inputs.velocity):.2f} m/s",
        ]
        for i, text in enumerate(telemetry):
            surf.blit(self.font.render(text, True, (0, 255, 180)), (40, 40 + (i * 25)))
        return self.ctx.texture(
            (cur_w, cur_h), 4, pygame.image.tobytes(surf, "RGBA", False)
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--voxels", type=float, default=11)
    args = parser.parse_args()
    app = SanctumViewport(max_voxels_m=args.voxels)
    app.run()
