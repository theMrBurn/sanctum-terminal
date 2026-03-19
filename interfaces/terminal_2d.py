# interfaces/terminal_2d.py
import pygame
import math
from engines.world import WorldEngine


class Terminal2D:
    def __init__(self, session):
        pygame.init()
        self.res = (1024, 768)
        self.screen = pygame.display.set_mode(self.res, pygame.DOUBLEBUF)
        self.is_fullscreen = False
        self.font = pygame.font.SysFont("Monospace", 18)
        self.session = session
        self.world = WorldEngine(self.session.floor, [])
        self.clock = pygame.time.Clock()

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        flags = pygame.FULLSCREEN if self.is_fullscreen else 0
        self.screen = pygame.display.set_mode(self.res, flags | pygame.DOUBLEBUF)

    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.session.is_alive = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RIGHTBRACKET:
                    self.toggle_fullscreen()

                if self.session.active_container == "RECOVERY_STUN":
                    self.session.active_container = None
                    return

                if self.session.active_container == "CALIBRATION":
                    if event.key == pygame.K_RETURN:
                        self.session.calibrate(self.session.input_buffer)
                        self.world = WorldEngine(
                            self.session.floor, self.session.modifiers
                        )
                    elif event.key == pygame.K_BACKSPACE:
                        self.session.input_buffer = self.session.input_buffer[:-1]
                    else:
                        if len(self.session.input_buffer) < 150:
                            self.session.input_buffer += event.unicode
                    return

                if self.session.active_container == "COMBAT":
                    if event.key == pygame.K_1:
                        self.session.combat_tick("ATTACK")
                    return

                if event.key == pygame.K_e:
                    px, pz = int(self.session.pos[0]), int(self.session.pos[2])
                    for dz in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            if self.world.get_tile(px + dx, pz + dz) == "$":
                                if self.session.decrypt_object("$"):
                                    self.world.set_tile(px + dx, pz + dz, "s")
                                    return

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
                    if tile == "R":
                        self.session.recover_data()
                    res = self.session.process_step(tile)
                    if res != "BLOCK":
                        self.session.pos[0], self.session.pos[2] = float(nx), float(nz)

    def draw(self):
        self.screen.fill((5, 5, 10))
        s = self.session
        if s.active_container == "CALIBRATION":
            self.draw_calibration()
        elif s.active_container == "RECOVERY_STUN":
            self.draw_recovery_msg()
        else:
            self.draw_world()
            if s.active_container == "COMBAT":
                self.draw_combat()
        pygame.display.flip()
        self.clock.tick(30)

    def draw_recovery_msg(self):
        msg = "SYSTEM REBOOTED. SIGNAL TRACER ACTIVE at 'R'. PRESS ANY KEY."
        self.screen.blit(self.font.render(msg, True, (255, 50, 50)), (150, 350))

    def draw_calibration(self):
        lines = [
            "--- NEURAL LINK CALIBRATION ---",
            f"> {self.session.input_buffer}_",
            "[RETURN] TO INJECT | [ ] ] FULLSCREEN",
        ]
        for i, line in enumerate(lines):
            self.screen.blit(
                self.font.render(line, True, (0, 255, 100)), (100, 100 + i * 30)
            )

    def draw_world(self):
        s, px, pz = self.session, int(self.session.pos[0]), int(self.session.pos[2])
        tx, tz = self.world.poi_coords
        dist = int(math.sqrt((tx - px) ** 2 + (tz - pz) ** 2))

        # HUD
        pygame.draw.rect(self.screen, (15, 15, 25), (0, 0, 1024, 65))
        self.screen.blit(
            self.font.render(
                f"POS: [{px},{pz}] | HP: {s.hp}% | XP: {s.xp}", True, (0, 255, 100)
            ),
            (20, 20),
        )

        # Status Text (Stealth vs Range)
        status_text = f"NODE_RANGE: {dist}m"
        status_color = (255, 255, 0)
        if s.recovery_grace > 0:
            status_text = f"SIGNAL_STABILIZED: {s.recovery_grace} cycles remaining"
            status_color = (0, 200, 255)
        self.screen.blit(self.font.render(status_text, True, status_color), (600, 20))

        # Viewport
        for z_off, z in enumerate(range(pz - 15, pz + 16)):
            for x_off, x in enumerate(range(px - 15, px + 16)):
                char = self.world.get_tile(x, z, s)
                color = (60, 60, 70)
                if x == px and z == pz:
                    char, color = "@", (
                        (0, 255, 255) if s.recovery_grace > 0 else (255, 255, 255)
                    )
                elif char == "R":
                    color = (0, 255, 255)
                elif char == "~":
                    color = (40, 100, 255)
                elif char == "s":
                    color = (130, 110, 80)
                elif char == "$":
                    color = (255, 255, 0)
                elif char == "X":
                    color = (200, 200, 200)
                elif char == "&":
                    color = (255, 0, 150)
                elif char in ["#", "O", "."]:
                    color = (220, 220, 220)

                d = math.sqrt((x - px) ** 2 + (z - pz) ** 2)
                alpha = max(0.15, 1.0 - (d / 18))
                f_color = tuple(int(c * alpha) for c in color)
                self.screen.blit(
                    self.font.render(char, True, f_color),
                    (230 + x_off * 18, 90 + z_off * 18),
                )

        for i, m in enumerate(s.log[-4:]):
            self.screen.blit(
                self.font.render(f"> {m}", True, (0, 150, 255)), (20, 660 + i * 22)
            )

    def draw_combat(self):
        s = self.session
        overlay = pygame.Surface((1024, 768), pygame.SRCALPHA)
        overlay.fill((40, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        pygame.draw.rect(self.screen, (255, 0, 50), (312, 284, 400, 220), 2)
        hp_pct = max(0, s.target_hp / s.target_max_hp)
        pygame.draw.rect(self.screen, (255, 0, 50), (330, 345, int(360 * hp_pct), 15))
        self.screen.blit(
            self.font.render(f"HOSTILE: {s.target_name}", True, (255, 255, 255)),
            (330, 310),
        )

    def run(self):
        while self.session.is_alive:
            self.handle_input()
            self.draw()
        pygame.quit()
