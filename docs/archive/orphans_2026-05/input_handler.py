import pygame


class InputHandler:
    DEFAULT_MAPPING = {
        "w": pygame.K_w,
        "s": pygame.K_s,
        "a": pygame.K_a,
        "d": pygame.K_d,
        "space": pygame.K_SPACE,
        "ctrl": pygame.K_LCTRL,
    }

    def __init__(self, mapping=None):
        if not pygame.get_init():
            pygame.init()
        if not pygame.display.get_init():
            pygame.display.set_mode((1, 1), pygame.NOFRAME | pygame.HIDDEN)
        self.mapping = mapping if mapping is not None else dict(self.DEFAULT_MAPPING)
        self.active_keys = set()
        self.mouse_sensitivity = 0.1
        self.yaw = 0.0
        self.pitch = 0.0
        try:
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)
        except pygame.error:
            pass

    def process_input(self, event):
        if event.type == pygame.QUIT:
            return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return True
            self.active_keys.add(event.key)
        elif event.type == pygame.KEYUP:
            self.active_keys.discard(event.key)
        return False

    def handle_keyboard(self, keys, dt):
        direction = [0, 0, 0]
        if keys[pygame.K_w]:
            direction[2] += 1
        if keys[pygame.K_s]:
            direction[2] -= 1
        if keys[pygame.K_a]:
            direction[0] -= 1
        if keys[pygame.K_d]:
            direction[0] += 1
        if keys[pygame.K_SPACE]:
            direction[1] += 1
        if keys[pygame.K_LCTRL]:
            direction[1] -= 1
        return direction

    def get_active_direction(self, dt):
        direction = [0, 0, 0]
        if pygame.K_w in self.active_keys:
            direction[2] += 1
        if pygame.K_s in self.active_keys:
            direction[2] -= 1
        if pygame.K_a in self.active_keys:
            direction[0] -= 1
        if pygame.K_d in self.active_keys:
            direction[0] += 1
        if pygame.K_SPACE in self.active_keys:
            direction[1] += 1
        if pygame.K_LCTRL in self.active_keys:
            direction[1] -= 1
        return direction

    def handle_mouse(self):
        dx, dy = pygame.mouse.get_rel()
        self.yaw += dx * self.mouse_sensitivity
        self.pitch = max(-90, min(90, self.pitch - (dy * self.mouse_sensitivity)))
        return self.yaw, self.pitch

    def check_quit_events(self):
        for event in pygame.event.get():
            if self.process_input(event):
                return True
        return False
