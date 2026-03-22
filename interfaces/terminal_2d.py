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

        # Kinetic Upgrade State
        self.action_state = "IDLE"
        self.action_timer = 0
        self.creature_pos = [5, 5]

    def run_action(self, entity_id=None):
        self.action_state = "PROCESSING"
        self.action_timer = 30

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
                if move and self.action_state == "IDLE":
                    s.process_step(
                        int(s.pos[0] + move[0]), int(s.pos[2] + move[1]), self.world
                    )

                if event.key == pygame.K_SPACE and self.action_state == "IDLE":
                    node = self.world.get_node(int(s.pos[0]), int(s.pos[2]), s)
                    if node["char"] == "$" or getattr(s, "is_lab_mode", False):
                        # Use new state handler function
                        self.run_action(node.get("id"))

        if self.joystick and not s.active_container:
            hat = self.joystick.get_hat(0)
            if hat != (0, 0):
                s.process_step(
                    int(s.pos[0] + hat[0]), int(s.pos[2] - hat[1]), self.world
                )

    def draw_world(self):
        s, px, pz = self.session, int(self.session.pos[0]), int(self.session.pos[2])
        self.screen.fill((2, 2, 8))

        # Kinetic Upgrades: Logic updates
        if self.action_state == "PROCESSING":
            self.action_timer -= 1
            if self.action_timer <= 0:
                # Based on session XP vs standard difficulty
                difficulty = 50
                if s.xp >= difficulty:
                    self.action_state = "SUCCESS"
                    self.action_timer = 30
                    s.add_log("VAULT OPENED.")
                else:
                    self.action_state = "FAILURE"
                    self.action_timer = 30
                    s.add_log("MECHANISM JAMMED.")
        elif self.action_state in ["SUCCESS", "FAILURE"]:
            self.action_timer -= 1
            if self.action_timer <= 0:
                self.action_state = "IDLE"

        # Creature Movement Logic (Every 60 frames roughly, we use ticks)
        # Using a simple frame counter attached to time or a separate tick counter
        if pygame.time.get_ticks() % 2000 < 30:  # roughly every 60 frames @ 30fps
            # Move towards player
            cx, cz = self.creature_pos
            if cx < px:
                cx += 1
            elif cx > px:
                cx -= 1
            if cz < pz:
                cz += 1
            elif cz > pz:
                cz -= 1
            self.creature_pos = [cx, cz]

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
        if getattr(s, "is_lab_mode", False):
            diag = f"XP: {s.xp} | COMPASS: LAB-MODE | RGB: {rgb_hex}"
        else:
            try:
                heading = s.get_compass_heading(self.world.poi_coords)
            except AttributeError:
                heading = "ERR_NO_POI"
            diag = f"XP: {s.xp} | COMPASS: {heading} | RGB: {rgb_hex}"
        self.screen.blit(self.font.render(diag, True, (255, 255, 0)), (920, 18))

        # 3. TOPOGRAPHY RENDER
        if getattr(s, "is_lab_mode", False):
            # In Lab Mode, we draw a flat 2D viewport, bypassing topography warping and scaling logic
            # Calculate global pulse for Lab objects
            ticks = pygame.time.get_ticks() / 1000.0  # Ticks in seconds

            for z_off, z in enumerate(range(pz - 10, pz + 11)):
                for x_off, x in enumerate(range(px - 10, px + 11)):
                    node = self.world.get_node(x, z, s)
                    proj_x, proj_y = 400 + (x_off * 20), 150 + (z_off * 20)
                    color = node["color"]
                    char = node["char"]

                    # Apply specific visual sine-wave flicker to lab diagnostic objects
                    if char == "L" and "flicker_hz" in node["meta"]:
                        hz = node["meta"]["flicker_hz"]
                        pulse = (
                            math.sin(ticks * math.pi * hz) + 1.0
                        ) / 2.0  # 0.0 to 1.0
                        # Modulate intensity between 20% and 100%
                        intensity = 0.2 + (0.8 * pulse)
                        color = (
                            int(color[0] * intensity),
                            int(color[1] * intensity),
                            int(color[2] * intensity),
                        )

                    if x == px and z == pz:
                        char, color = "@", (255, 255, 255)
                        # Animation Overrides
                        if self.action_state == "PROCESSING":
                            char, color = "?", (255, 255, 0)  # Yellow
                        elif self.action_state == "SUCCESS":
                            char, color = "O", (0, 255, 0)  # Green
                        elif self.action_state == "FAILURE":
                            char, color = "!", (255, 0, 0)  # Red

                    # Creature override
                    if x == self.creature_pos[0] and z == self.creature_pos[1]:
                        char, color = "C", (255, 100, 100)

                    self.screen.blit(
                        self.font.render(char, True, color), (proj_x, proj_y)
                    )
        else:
            raster_warp = int(s.tension / 15.0)
            for z_off, z in enumerate(range(pz - 15, pz + 16)):
                line_shift = math.sin(z * 0.4) * raster_warp
                for x_off, x in enumerate(range(px - 25, px + 26)):
                    node = self.world.get_node(x, z, s)
                    proj_x, proj_y = 180 + (x_off * 18) + int(line_shift), (
                        120 + z_off * 16
                    ) - int(node["pos"][1] * 9)
                    # Simplified coloring fallback if 'rel' intensity missing (e.g. in lab mode or standard grid)
                    if "rel" in node and "intensity" in node["rel"]:
                        lum = node["rel"]["intensity"]
                        color = (int(80 * lum), int(200 * lum), int(255 * lum))
                        if s.is_glitched and node["rel"]["noise"] > 0.7:
                            color = (255, 50, 50)
                    else:
                        color = node["color"]
                    char = node["char"]
                    if x == px and z == pz:
                        char, color = "@", (255, 255, 255)
                        # Animation Overrides
                        if self.action_state == "PROCESSING":
                            char, color = "?", (255, 255, 0)  # Yellow
                        elif self.action_state == "SUCCESS":
                            char, color = "O", (0, 255, 0)  # Green
                        elif self.action_state == "FAILURE":
                            char, color = "!", (255, 0, 0)  # Red

                    # Creature override
                    if x == self.creature_pos[0] and z == self.creature_pos[1]:
                        char, color = "C", (255, 100, 100)

                    self.screen.blit(
                        self.font.render(char, True, color), (proj_x, proj_y)
                    )

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
