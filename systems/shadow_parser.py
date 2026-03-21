import hashlib
import json
from pathlib import Path


class ShadowParser:
    VECTORS = {
        "cold": {"thermal": -0.8, "friction": 0.5},
        "trapped": {"claustrophobia": 0.9, "anxiety_gain": 1.5},
        "unstable": {"jitter": 0.8, "pulse": 1.4},
        "dark": {"visibility": -0.7, "anxiety_gain": 1.2},
    }

    @staticmethod
    def get_latest_scout_tokens():
        report_path = Path("data/scout_report.json")
        if not report_path.exists():
            return ShadowParser.tokenize_discomfort("initial_sync")
        try:
            with open(report_path, "r") as f:
                data = json.load(f)
                combined = f"{data.get('location', '')} {data.get('status', '')}"
                return ShadowParser.tokenize_discomfort(combined)
        except Exception:
            return ShadowParser.tokenize_discomfort("error_fallback")

    @staticmethod
    def tokenize_discomfort(text):
        tokens = {
            "anxiety_gain": 1.0,
            "thermal": 0.0,
            "hash_seed": 42,
            "jitter": 0.1,
            "claustrophobia": 0.0,
        }
        input_string = text.lower()
        for key, weights in ShadowParser.VECTORS.items():
            if key in input_string:
                for attr, val in weights.items():
                    if attr in tokens:
                        tokens[attr] += val
        tokens["hash_seed"] = (
            int(hashlib.md5(input_string.encode()).hexdigest(), 16) % 10**8
        )
        return tokens
