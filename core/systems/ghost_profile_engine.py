import json
from pathlib import Path


def _load_profiles():
    p = Path('config/ghost_profiles.json')
    return json.load(open(p)) if p.exists() else {}


# Interview answer → profile affinity mapping
INTERVIEW_AFFINITY = {
    'q8': {
        'seeker':   {'SEEKER': 0.6, 'NATURALIST': 0.2, 'PRECISION_HAND': 0.2},
        'builder':  {'MAKER': 0.5, 'SYSTEMS_THINKER': 0.3, 'GUARDIAN': 0.2},
        'wanderer': {'ENDURANCE_BODY': 0.4, 'PERFORMER': 0.3, 'SEEKER': 0.3},
        'keeper':   {'GUARDIAN': 0.5, 'ENDURANCE_BODY': 0.3, 'MAKER': 0.2},
    },
    'q1': {
        'city':    {'PERFORMER': 0.4, 'SYSTEMS_THINKER': 0.3, 'FORCE_MULTIPLIER': 0.3},
        'nature':  {'NATURALIST': 0.5, 'ENDURANCE_BODY': 0.3, 'SEEKER': 0.2},
        'home':    {'GUARDIAN': 0.4, 'MAKER': 0.4, 'PRECISION_HAND': 0.2},
        'between': {'SEEKER': 0.4, 'ENDURANCE_BODY': 0.3, 'PERFORMER': 0.3},
    },
    'q6': {
        'deliberately': {'PRECISION_HAND': 0.5, 'GUARDIAN': 0.3, 'NATURALIST': 0.2},
        'quickly':      {'FORCE_MULTIPLIER': 0.5, 'RHYTHM_KEEPER': 0.3, 'SEEKER': 0.2},
        'carefully':    {'NATURALIST': 0.4, 'PRECISION_HAND': 0.4, 'GUARDIAN': 0.2},
        'not_sure':     {'ENDURANCE_BODY': 0.4, 'PERFORMER': 0.3, 'SEEKER': 0.3},
    },
    'q5': {
        'crushing': {'ENDURANCE_BODY': 0.4, 'GUARDIAN': 0.3, 'FORCE_MULTIPLIER': 0.3},
        'heavy':    {'GUARDIAN': 0.4, 'ENDURANCE_BODY': 0.3, 'PRECISION_HAND': 0.3},
        'medium':   {'SYSTEMS_THINKER': 0.4, 'MAKER': 0.3, 'PERFORMER': 0.3},
        'light':    {'SEEKER': 0.4, 'RHYTHM_KEEPER': 0.3, 'NATURALIST': 0.3},
    },
}


class GhostProfileEngine:
    """
    Maps interview answers and behavioral fingerprint
    to a weighted blend of ghost profiles.
    The blend seeds world calibration — never shown to player.
    Updated continuously from fingerprint during play.
    """

    def __init__(self):
        self.profiles = _load_profiles()
        self._profile_names = list(self.profiles.keys())

    def map_interview(self, answers):
        """
        Map interview answers to initial profile blend.
        Returns normalized dict of profile_name → weight.
        """
        scores = {name: 0.0 for name in self._profile_names}

        for q_id, affinity_map in INTERVIEW_AFFINITY.items():
            answer = answers.get(q_id)
            if answer and answer in affinity_map:
                for profile, weight in affinity_map[answer].items():
                    if profile in scores:
                        scores[profile] += weight

        # Give every profile a minimum presence
        for name in scores:
            scores[name] = max(0.05, scores[name])

        return self._normalize_blend(scores)

    def update_from_fingerprint(self, fingerprint):
        """
        Update profile blend from behavioral fingerprint.
        fingerprint: dict of behavior_key → 0.0-1.0 intensity
        Returns normalized blend.
        """
        scores = {name: 0.0 for name in self._profile_names}

        for name, profile in self.profiles.items():
            weights = profile.get('fingerprint_weights', {})
            score = 0.0
            total_weight = 0.0
            for key, w in weights.items():
                if key in fingerprint:
                    score += fingerprint[key] * w
                    total_weight += w
            if total_weight > 0:
                scores[name] = score / total_weight
            else:
                scores[name] = 0.05

        for name in scores:
            scores[name] = max(0.05, scores[name])

        return self._normalize_blend(scores)

    def merge_blends(self, blend_a, blend_b, weight_a=0.4, weight_b=0.6):
        """
        Merge two blends with weights.
        Default: fingerprint (b) has more influence than interview (a).
        As play time increases, fingerprint dominates.
        """
        merged = {}
        all_keys = set(list(blend_a.keys()) + list(blend_b.keys()))
        for key in all_keys:
            merged[key] = (
                blend_a.get(key, 0.0) * weight_a +
                blend_b.get(key, 0.0) * weight_b
            )
        return self._normalize_blend(merged)

    def dominant_profile(self, blend):
        """Return the profile with highest weight in blend."""
        return max(blend, key=blend.get)

    def get_combat_style(self, blend):
        """Return combat style of dominant profile."""
        dominant = self.dominant_profile(blend)
        return self.profiles[dominant]['combat_style']

    def get_world_modifiers(self, blend):
        """
        Blend world modifiers from all profiles weighted by blend.
        Returns merged modifier dict for AtmosphereEngine.
        """
        merged = {}
        for name, weight in blend.items():
            if name not in self.profiles:
                continue
            mods = self.profiles[name].get('world_modifiers', {})
            for key, val in mods.items():
                if isinstance(val, bool):
                    if val and weight > 0.3:
                        merged[key] = True
                elif isinstance(val, (int, float)):
                    if key in merged:
                        merged[key] += val * weight
                    else:
                        merged[key] = val * weight
        return merged

    def get_resolution_bias(self, blend):
        """
        Blend resolution biases from all profiles.
        Returns dict of resolution_path → effectiveness modifier.
        """
        merged = {}
        for name, weight in blend.items():
            if name not in self.profiles:
                continue
            bias = self.profiles[name].get('resolution_bias', {})
            for path, val in bias.items():
                if path in merged:
                    merged[path] += val * weight
                else:
                    merged[path] = val * weight
        return merged

    def _normalize_blend(self, scores):
        """Normalize a dict of weights to sum to 1.0."""
        total = sum(scores.values())
        if total == 0:
            equal = 1.0 / len(scores)
            return {k: equal for k in scores}
        return {k: v / total for k, v in scores.items()}