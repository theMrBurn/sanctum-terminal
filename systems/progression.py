import math


class Progression:
    @staticmethod
    def get_player_power(level):
        # Logarithmic growth: gains slow down but never stop
        return 10 + (level * math.log10(level + 1))

    @staticmethod
    def get_enemy_stats(level):
        # Exponential growth: the world eventually outpaces a stagnant player
        hp = 10 * (1.15**level)
        atk = 2 * (1.10**level)
        return {"hp": hp, "atk": atk}

    @staticmethod
    def get_overclock_threshold(level):
        # How many 'Perception Points' (voxels seen) to trigger Overclock
        return 100 + (level * 25)
