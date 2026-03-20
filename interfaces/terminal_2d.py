# interfaces/terminal_2d.py
import pygame
import math
from engines.world import WorldEngine


class Terminal2D:
    def __init__(self, session):
        pygame.init()
        pygame.joystick.init()
        self.res = (1280, 720)
        self.screen = pygame.display.set_mode(self.res, pygame.DOUBLEBUF)
        self.font = pygame.font.SysFont("Monospace", 18)
        self.session = session
        self.world = WorldEngine(self.session.seed)
        self.clock = pygame.time.Clock()
        self.joystick = None
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()

    def handle_input(self):
        s = self.session
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                s.is_alive = False
            if event.type == pygame.JOYBUTTONDOWN:
                if event.button == 0:
                    s.interact(int(s.pos[0]), int(s.pos[2]), self.world)
                if event.button == 1:
                    s.is_scouting = not s.is_scouting

            if event.type == pygame.KEYDOWN:
                if s.active_container == "BOOT_SEQUENCE":
                    if event.key == pygame.K_RETURN:
                        s.calibrate(s.input_buffer)
                    elif event.key == pygame.K_BACKSPACE:
                        s.input_buffer = s.input_buffer[:-1]
                    else:
                        s.input_buffer += event.unicode
                elif s.active_container == "TRANSITION":
                    s.active_container = None
                elif event.key == pygame.K_e:
                    s.interact(int(s.pos[0]), int(s.pos[2]), self.world)

                key_map = {
                    pygame.K_w: (0, -1),
                    pygame.K_s: (0, 1),
                    pygame.K_a: (-1, 0),
                    pygame.K_d: (1, 0),
                }
                move = key_map.get(event.key)
                if move:
                    s.process_step(
                        int(s.pos[0] + move[0]), int(s.pos[2] + move[1]), self.world
                    )

        if self.joystick and not s.active_container:
            hat = self.joystick.get_hat(0)
            if hat != (0, 0):
                s.process_step(
                    int(s.pos[0] + hat[0]), int(s.pos[2] - hat[1]), self.world
                )

    def draw_world(self):
        s, px, pz = self.session, int(self.session.pos[0]), int(self.session.pos[2])
        self.screen.fill((2, 2, 8))

        # 1. ANALOG SIGNALS (Haptics/RGB)
        rgb_hex = s.get_rgb_handshake()
        low, high = s.get_haptic_signal()
        if self.joystick:
            self.joystick.rumble(low, high, 100)

        # 2. TOP HUD (The Integrated Dashboard)
        pygame.draw.rect(self.screen, (10, 10, 15), (0, 0, 1280, 60))

        # HP Bar (Left)
        hp_color = (255, 50, 50) if s.hp < 30 else (0, 255, 100)
        pygame.draw.rect(self.screen, (40, 20, 20), (20, 20, 200, 15))
        pygame.draw.rect(self.screen, hp_color, (20, 20, int(s.hp * 2), 15))
        self.screen.blit(
            self.font.render(f"HP: {int(s.hp)}%", True, (255, 255, 255)), (225, 18)
        )

        # Tension Bar (Center)
        bar_color = (0, 255, 255) if s.tension < 75 else (255, 100, 0)
        pygame.draw.rect(self.screen, (30, 30, 40), (480, 20, 200, 15))
        pygame.draw.rect(self.screen, bar_color, (480, 20, int(s.tension * 2), 15))
        self.screen.blit(
            self.font.render(f"STRAIN: {int(s.tension)}%", True, bar_color), (690, 18)
        )

        # Compass & XP (Right)
        heading = s.get_compass_heading(self.world.poi_coords)
        diag = f"XP: {s.xp} | COMPASS: {heading} | RGB: {rgb_hex}"
        self.screen.blit(self.font.render(diag, True, (255, 255, 0)), (920, 18))

        # 3. TOPOGRAPHY RENDER
        raster_warp = int(s.tension / 15.0)
        for z_off, z in enumerate(range(pz - 15, pz + 16)):
            line_shift = math.sin(z * 0.4) * raster_warp
            for x_off, x in enumerate(range(px - 25, px + 26)):
                node = self.world.get_node(x, z, s)
                proj_x, proj_y = 180 + (x_off * 18) + int(line_shift), (
                    120 + z_off * 16
                ) - int(node["pos"][1] * 9)
                lum = node["rel"]["intensity"]
                color = (int(80 * lum), int(200 * lum), int(255 * lum))
                if s.is_glitched and node["rel"]["noise"] > 0.7:
                    color = (255, 50, 50)
                char = node["char"]
                if x == px and z == pz:
                    char, color = "@", (255, 255, 255)
                self.screen.blit(self.font.render(char, True, color), (proj_x, proj_y))

        # 4. LOG (Bottom)
        for i, m in enumerate(s.log[-3:]):
            self.screen.blit(
                self.font.render(f">> {m}", True, (0, 255, 100)), (40, 640 + i * 20)
            )

    def draw(self):
        self.session.update()
        if self.session.active_container == "BOOT_SEQUENCE":
            self.screen.fill((0, 0, 0))
            for i, line in enumerate(self.session.process_boot()):
                self.screen.blit(
                    self.font.render(line, True, (0, 255, 100)), (100, 100 + i * 30)
                )
        elif self.session.active_container == "TRANSITION":
            self.screen.fill((0, 0, 0))
            txt = self.font.render(
                "CALIBRATING NEURAL TOPOGRAPHY...", True, (0, 255, 255)
            )
            self.screen.blit(txt, (640 - txt.get_width() // 2, 350))
        else:
            self.draw_world()
        pygame.display.flip()
        self.clock.tick(30)

    def run(self):
        while self.session.is_alive:
            self.handle_input()
            self.draw()
        pygame.quit()
