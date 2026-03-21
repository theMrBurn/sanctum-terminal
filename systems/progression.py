import json, random, math
from pathlib import Path
from types import SimpleNamespace


class ProgressionManager:
    @staticmethod
    def load_session(seed):
        Path("data").mkdir(exist_ok=True)
        random.seed(seed)
        # Generate mission target far from origin
        angle = random.uniform(0, 2 * math.pi)
        dist = 800.0

        return SimpleNamespace(
            pos=[0.0, 0.0],
            target=[math.cos(angle) * dist, math.sin(angle) * dist],
            tension=0.0,
            anxiety=0.0,
            battery=100.0,
            kit={
                "neural_link": {"integrity": 100, "status": "nominal"},
                "scout_drone": {"integrity": 100, "status": "nominal"},
                "thermal_reg": {"integrity": 100, "status": "nominal"},
            },
        )

    @staticmethod
    def find_nearest_anchor(x, y, seed):
        ax, ay = (round(x / 200)) * 200, (round(y / 200)) * 200
        best_dist, best_pos = 9999, (ax, ay)
        for ox in [-200, 0, 200]:
            for oy in [-200, 0, 200]:
                tx, ty = ax + ox, ay + oy
                if (tx * 73856093 ^ ty * 19349663 ^ seed) % 100 > 95:
                    d = math.sqrt((x - tx) ** 2 + (y - ty) ** 2)
                    if d < best_dist:
                        best_dist, best_pos = d, (tx, ty)
        return best_pos, best_dist

    @staticmethod
    def apply_neural_snap(session):
        item = random.choice(list(session.kit.keys()))
        session.kit[item]["integrity"] = max(0, session.kit[item]["integrity"] - 20)
        session.pos, session.tension, session.anxiety = [0.0, 0.0], 0.0, 0.0
        return item
