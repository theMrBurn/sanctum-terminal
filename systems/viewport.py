# systems/viewport.py
import pygame
from systems.logic_walker import ASCIICrawler

class VoxelTerminal:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((1024, 768))
        pygame.display.set_caption("SANCTUM TERMINAL")
        self.font = pygame.font.SysFont("Monospace", 22)
        self.crawler = ASCIICrawler()
        self.clock = pygame.time.Clock()

    def run(self):
        while self.crawler.state.is_alive:
            self.screen.fill((10, 10, 15))
            for event in pygame.event.get():
                if event.type == pygame.QUIT: return
                if event.type == pygame.KEYDOWN:
                    # 'f' fight, 'd' defend, 'b' burst, 'r' run, 't' take hit
                    key_map = {pygame.K_w:'w', pygame.K_s:'s', pygame.K_a:'a', pygame.K_d:'d',
                               pygame.K_f:'f', pygame.K_b:'b', pygame.K_r:'r', pygame.K_t:'t'}
                    char = key_map.get(event.key)
                    if char: self.crawler.handle_input(char)

            self._draw_hud()
            if self.crawler.active_combat: self._draw_combat()
            elif self.crawler.active_challenge: self._draw_challenge()
            else: self._draw_map()
            
            pygame.display.flip()
            self.clock.tick(30)

    def _draw_hud(self):
        s = self.crawler.state
        sync = (len(s.visited) / s.total_tiles) * 100
        xp_range = max(1, s.xp_next - s.xp_prev)
        xp_p = int(((s.xp - s.xp_prev) / xp_range) * 200)
        
        self.screen.blit(self.font.render(f"F: {s.floor} | LV: {s.lv} | {s.get_elapsed_time()}", True, (0, 255, 200)), (20, 20))
        self.screen.blit(self.font.render(f"HP: {s.hp}/{s.hp_max} | SYNC: {sync:.1f}%", True, (0, 255, 100)), (20, 50))
        
        # Bars
        pygame.draw.rect(self.screen, (50, 50, 50), (20, 85, 200, 8)) # XP Background
        pygame.draw.rect(self.screen, (0, 150, 255), (20, 85, max(0, xp_p), 8)) # XP
        pygame.draw.rect(self.screen, (255, 200, 0), (20, 100, int(s.grit_meter * 2), 8)) # Grit

    def _draw_map(self):
        px, py = self.crawler.state.pos
        for y_off, y in enumerate(range(py-6, py+7)):
            for x_off, x in enumerate(range(px-6, px+7)):
                if 0 <= x < 32 and 0 <= y < 32:
                    char = self.crawler.grid[y, x]
                    if x == px and y == py: char, col = "@", (255, 50, 50)
                    elif char == "^": char, col = ".", (60, 60, 60)
                    elif char in ["#", "$", "&", "X"]:
                        col = (100,100,100) if char=="#" else (255,255,0) if char=="$" else (0,255,255) if char=="&" else (0,255,0)
                    else: col = (150, 150, 150)
                    self.screen.blit(self.font.render(char, True, col), (320 + x_off*25, 150 + y_off*25))
        for i, m in enumerate(self.crawler.state.log[-4:]):
            self.screen.blit(self.font.render(f"> {m}", True, (150, 150, 150)), (20, 600 + i*25))

    def _draw_combat(self):
        self.screen.blit(self.font.render("--- BATTLE MODE ---", True, (255, 50, 50)), (400, 150))
        for i, e in enumerate(self.crawler.active_combat.enemies):
            hp, m_hp = e.get('hp', 0), e.get('max_hp', 1)
            txt = f"[{e.get('sym','?')}] {e.get('name','...')}: {hp}/{m_hp} HP"
            self.screen.blit(self.font.render(txt, True, (255, 255, 255)), (350, 220 + i*35))
        self.screen.blit(self.font.render("(F)ight (D)efend (B)urst (R)un", True, (200, 200, 200)), (350, 500))

    def _draw_challenge(self):
        c = self.crawler.active_challenge
        self.screen.blit(self.font.render(f"CHALLENGE: {c.name}", True, (0, 255, 255)), (350, 300))
        self.screen.blit(self.font.render("(A)ttempt Bypass | (T)ake Hit", True, (200, 200, 200)), (350, 350))

if __name__ == "__main__":
    VoxelTerminal().run()