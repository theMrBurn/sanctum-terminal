# interfaces/terminal.py
import pygame
import math
from engines.world import WorldEngine


class Terminal2D:
    def __init__(self, session):
        pygame.init()
        self.res = (1280, 720)
        self.screen = pygame.display.set_mode(self.res, pygame.DOUBLEBUF)
        self.is_fullscreen = False
        self.font = pygame.font.SysFont("Monospace", 18)
        self.session = session
        self.world = WorldEngine(self.session.floor, [])
        self.clock = pygame.time.Clock()

    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.session.is_alive = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RIGHTBRACKET:
                    self.toggle_fullscreen()

                # BOOT SEQUENCE
                if self.session.active_container == "BOOT_SEQUENCE":
                    if event.key == pygame.K_RETURN:
                        self.session.journal.append(self.session.input_buffer)
                        self.session.finalize_sync()
                        self.world = WorldEngine(self.session.floor, [])
                    elif event.key == pygame.K_BACKSPACE:
                        self.session.input_buffer = self.session.input_buffer[:-1]
                    else:
                        self.session.input_buffer += event.unicode
                    return

                if self.session.active_container in ["TRANSITION", "RECOVERY_STUN"]:
                    self.session.active_container = None
                    return

                if self.session.active_container == "COMBAT":
                    if event.key == pygame.K_1:
                        self.session.combat_tick("PURGE")
                    if event.key == pygame.K_2:
                        self.session.combat_tick("ANALYZE")
                    return

                # SCOUT MODE TOGGLE
                if event.key == pygame.K_v:
                    self.session.is_scouting = not self.session.is_scouting
                    self.session.add_log(
                        f"SCOUT_MODE: {'ON' if self.session.is_scouting else 'OFF'}"
                    )

                # MOVEMENT
                key_map = {
                    pygame.K_w: (0, -1),
                    pygame.K_s: (0, 1),
                    pygame.K_a: (-1, 0),
                    pygame.K_d: (1, 0),
                }
                move = key_map.get(event.key)
                if move:
                    nx, nz = int(self.session.pos[0] + move[0]), int(
                        self.session.pos[2] + move[1]
                    )
                    tile = self.world.get_tile(nx, nz, self.session)
                    if self.session.process_step(tile) != "BLOCK":
                        self.session.pos[0], self.session.pos[2] = float(nx), float(nz)

    def draw(self):
        self.screen.fill((0, 0, 0))
        s = self.session
        if s.active_container == "BOOT_SEQUENCE":
            self.draw_boot()
        elif s.active_container == "TRANSITION":
            self.draw_transition()
        elif s.active_container == "RECOVERY_STUN":
            self.draw_recovery_msg()
        else:
            self.draw_world()
            if s.active_container == "COMBAT":
                self.draw_combat()
        pygame.display.flip()
        self.clock.tick(30)

    def draw_world(self):
        s, px, pz = self.session, int(self.session.pos[0]), int(self.session.pos[2])
        # HUD TOP
        pygame.draw.rect(self.screen, (10, 10, 15), (0, 0, 1280, 80))
        self.screen.blit(
            self.font.render(
                f"ID: SEAN_GOIBURN | HP: {s.hp}% | XP: {s.xp} | LOCALE: {s.user_locale}",
                True,
                (0, 255, 100),
            ),
            (20, 30),
        )

        # VIEWPORT
        start_x, start_y = 145, 100
        # SCOUT MODE: Expand vision from 28 to 40
        view_radius = 40 if s.is_scouting else 25

        for z_off, z in enumerate(range(pz - 15, pz + 16)):
            for x_off, x in enumerate(range(px - 27, px + 28)):
                char = self.world.get_tile(x, z, s)
                color = (50, 50, 60)
                if s.user_locale == "URBAN":
                    color = (100, 110, 130)
                elif s.user_locale == "FOREST":
                    color = (60, 120, 60)
                elif s.user_locale == "DESERT":
                    color = (200, 150, 50)

                if x == px and z == pz:
                    char, color = "@", (255, 255, 255)
                d = math.sqrt((x - px) ** 2 + (z - pz) ** 2)
                alpha = max(0.1, 1.0 - (d / view_radius))
                f_color = tuple(int(c * alpha) for c in color)
                self.screen.blit(
                    self.font.render(char, True, f_color),
                    (start_x + x_off * 18, start_y + z_off * 18),
                )

        # HUD BOTTOM (LOG)
        pygame.draw.rect(self.screen, (10, 10, 15), (0, 640, 1280, 80))
        for i, m in enumerate(s.log[-3:]):
            self.screen.blit(
                self.font.render(f"LOG_{i}: {m}", True, (0, 150, 255)),
                (40, 655 + i * 20),
            )

    def draw_boot(self):
        lines = self.session.process_boot()
        for i, line in enumerate(lines):
            self.screen.blit(
                self.font.render(line, True, (0, 255, 100)), (100, 100 + i * 30)
            )

    def draw_transition(self):
        for i, line in enumerate(self.session.transition_msg):
            self.screen.blit(
                self.font.render(line, True, (0, 200, 255)), (540, 250 + i * 40)
            )

    def draw_recovery_msg(self):
        self.screen.blit(
            self.font.render(
                "SIGNAL COLLAPSE. RECOVERY AT 'R'. PRESS ANY KEY.", True, (255, 50, 50)
            ),
            (300, 350),
        )

    def draw_combat(self):
        overlay = pygame.Surface((1280, 720), pygame.SRCALPHA)
        overlay.fill((20, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        pygame.draw.rect(self.screen, (255, 0, 50), (440, 235, 400, 250), 2)

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.screen = pygame.display.set_mode(
            self.res,
            (pygame.FULLSCREEN if self.is_fullscreen else 0) | pygame.DOUBLEBUF,
        )
