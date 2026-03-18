import pygame
import moderngl
import numpy as np
from spatial_utils import RelativityCamera
from core.vault import Vault
from systems.observer import ObserverSystem
from input_handler import InputHandler
from renderer_handler import RenderHandler
from config_manager import ConfigManager


class SanctumViewport:
    def __init__(self):
        pygame.display.init()
        pygame.font.init()
        self.win_size = (1280, 720)

        # OpenGL Setup
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
        )

        self.screen = pygame.display.set_mode(
            self.win_size, pygame.OPENGL | pygame.DOUBLEBUF
        )
        self.ctx = moderngl.create_context()

        # Modular Systems
        self.config = ConfigManager()
        self.camera = RelativityCamera([0.0, 2.0, 20.0])
        self.vault = Vault()  # Core: Storage + Bloom + Culling
        self.observer = ObserverSystem(self.config)  # Systems: Sensors + Perception
        self.render = RenderHandler(self.ctx)
        self.inputs = InputHandler()

        # State
        self.font = pygame.font.SysFont("Monaco", 22)
        self.hud_vao = self.render.build_hud_vao()
        self.vao = None
        self.current_frame_data = None
        self.last_sync_pos = self.camera.pos.copy()
        self.roll, self.step_cycle = 0.0, 0.0

        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        self._sync_vault()

    def _sync_vault(self):
        """
        One-stop shop for world data.
        The Vault now handles the DB query AND the camera culling internally.
        """
        self.current_frame_data = self.vault.get_visible_frame(
            self.camera.pos, self.camera.front, 80.0
        )
        self.vao = self.render.build_vao(self.current_frame_data)
        self.last_sync_pos = self.camera.pos.copy()

    def update(self, dt):
        v, l = self.inputs.get_movement(dt), self.inputs.get_look(dt)
        self.camera.update_orientation(l[0], l[1])

        # Locomotion with integrated Collision check
        move_vec = (self.camera.front * v[0]) + (self.camera.right * v[1])
        if move_vec.length > 0.01:
            self.step_cycle += dt * 10.0
            self.roll = np.sin(self.step_cycle * 0.5) * 1.2
            if not self.vault.check_collision(self.camera.pos + move_vec, 1.0):
                self.camera.pos += move_vec
        else:
            self.roll *= 0.9

        # Refresh if moved past 1.5m threshold
        if (self.camera.pos - self.last_sync_pos).length > 1.5:
            self._sync_vault()

    def run(self):
        clock = pygame.time.Clock()
        while True:
            dt = clock.tick(120) / 1000.0
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.MOUSEBUTTONDOWN:
                    self.observer.trigger_pulse(self.camera.pos)

            self.update(dt)

            # Unified Render Pipeline
            mvp = self.camera.get_projection() * self.camera.get_view_matrix(self.roll)
            hud_tex = self.create_hud()  # (Kept as simple placeholder)

            self.render.render_frame(
                self.vao,
                mvp,
                self.camera.pos,
                self.observer.get_shader_params(),  # Unified perception data
                hud_tex,
                self.hud_vao,
            )
            pygame.display.flip()
            hud_tex.release()

    def create_hud(self):
        # Placeholder for visual stability - identical to your current code
        surf = pygame.Surface(self.win_size, pygame.SRCALPHA)
        label = f"LOC: {self.camera.pos.x:0.0f}, {self.camera.pos.z:0.0f}"
        surf.blit(self.font.render(label, True, (0, 255, 180)), (30, 30))
        return self.ctx.texture(
            self.win_size, 4, pygame.image.tobytes(surf, "RGBA", False)
        )
