import json
from pathlib import Path
from core.systems.curves import apply_scale, normalize


def _load_manifest():
    path = Path(__file__).parent.parent.parent / "config" / "manifest.json"
    if path.exists():
        return json.load(open(path))
    return {}


TORCH = {
    "id":           "TORCH_DEFAULT",
    "name":         "The First Torch",
    "description":  "You made this. It was the first thing.",
    "impact":       1,
    "type":         "craft",
    "ability":      "Illumination",
    "ability_desc": "Reveals one hidden path per session.",
    "transferable": True,
}

LOW_COMMITMENT_SIGNALS = {
    "torch","fire","light","thing","stuff","idk","nothing","something",
    "whatever","dunno","ok","yes","no","maybe","sure","fine","good",
    "bad","meh","hmm","um","uh","eh",
}

DEPTH_PROMPTS = [
    "What do you need to see?",
    "What are you trying to find your way through?",
    "What would having light change for you right now?",
    "What is in the dark that you would rather not look at?",
    "Where are you trying to go?",
]

DEFAULTS = {
    "biome_key":         "VOID",
    "biome_secondary":   "VOID",
    "archetype":         "WANDERER",
    "label":             "Unnamed",
    "encounter_density": 0.3,
    "spawn_radius":      40,
    "karma_baseline":    0.3,
    "karma_decay_rate":  0.08,
    "ambient_intensity": 0.5,
    "camera_speed":      40.0,
    "heat":              0.5,
    "moisture":          0.5,
    "light":             0.5,
    "depth_score":       0,
    "first_relic": {
        "archetypal_name": "unnamed",
        "vibe":            "",
        "impact_rating":   3,
    }
}


def _detect_commitment_depth(word):
    if not word:
        return 0
    word = word.strip().lower()
    if word in LOW_COMMITMENT_SIGNALS:
        return 1
    if len(word) <= 4:
        return 1
    if len(word) <= 8:
        return 2
    return 3


def _depth_prompt(word, rng_index=0):
    return DEPTH_PROMPTS[rng_index % len(DEPTH_PROMPTS)]


class InterviewEngine:
    """
    World seed interview — 10 prompts filling all seed parameters.
    Every answer maps to a normalized float via apply_scale().
    No hardcoded values — everything flows through curves.py.
    """

    def __init__(self, config=None):
        self._config     = config or _load_manifest()
        self.prompts     = self._config.get("questionnaire", {}).get("prompts", [])
        self.answers     = {}
        self.scales      = {}
        self.complete    = False
        self.torch       = dict(TORCH)
        self.depth_score = 0
        self.on_complete = None

    def _get_prompt(self, prompt_id):
        for p in self.prompts:
            if p["id"] == prompt_id:
                return p
        return None

    def _check_complete(self):
        required  = [p["id"] for p in self.prompts if not p.get("optional", False)]
        open_pids = [p["id"] for p in self.prompts if p["type"] == "open"]
        if (all(qid in self.answers for qid in required) and
                all(qid in self.answers for qid in open_pids)):
            self.complete = True
            if callable(self.on_complete):
                self.on_complete(self.resolve())

    def answer(self, prompt_id, value):
        prompt = self._get_prompt(prompt_id)
        if prompt is None:
            raise ValueError(f"InterviewEngine: unknown prompt '{prompt_id}'")
        if prompt["type"] == "choice":
            if value not in prompt["options"]:
                raise ValueError(
                    f"InterviewEngine: '{value}' not valid for {prompt_id}. "
                    f"Valid: {list(prompt['options'].keys())}"
                )
            self.scales[prompt_id] = normalize(
                prompt["options"][value].get("scale", 0.5)
            )
        if prompt_id == "q10":
            self.depth_score = _detect_commitment_depth(value)
            self._enhance_torch(value)
        self.answers[prompt_id] = value
        self._check_complete()
        return self

    def skip(self, prompt_id):
        prompt = self._get_prompt(prompt_id)
        if prompt is None:
            raise ValueError(f"InterviewEngine: unknown prompt '{prompt_id}'")
        if prompt_id == "q10":
            self.depth_score = 0
        self.answers[prompt_id] = None
        self._check_complete()
        return self

    def _enhance_torch(self, word):
        if not word or self.depth_score == 0:
            return
        if self.depth_score == 1:
            self.torch["name"]        = "A Dim Torch"
            self.torch["description"] = "It lights something. You are not sure what yet."
            self.torch["impact"]      = 2
        elif self.depth_score == 2:
            self.torch["name"]         = f"The {word.title()} Torch"
            self.torch["description"]  = f"Made in the time of {word}. It carries that weight."
            self.torch["impact"]       = 4
            self.torch["ability"]      = "Wayfinding"
            self.torch["ability_desc"] = f"In moments of {word}, reveals a path others cannot see."
        elif self.depth_score == 3:
            self.torch["name"]         = f"The Torch of {word.title()}"
            self.torch["description"]  = f"This torch was made in the time of {word}."
            self.torch["impact"]       = 7
            self.torch["ability"]      = f"{word.title()} Light"
            self.torch["ability_desc"] = f"Born from {word}. Reveals hidden encounters. Can be shared."
            self.torch["transferable"] = True
            self.torch["rare"]         = True

    def resolve(self):
        config = dict(DEFAULTS)
        config["first_relic"] = dict(DEFAULTS["first_relic"])

        for prompt in self.prompts:
            pid    = prompt["id"]
            # Only apply curves for explicitly answered prompts
            answer = self.answers.get(pid)
            if answer is None:
                continue

            if prompt["type"] == "choice" and answer in prompt.get("options", {}):
                option  = prompt["options"].get(answer, {})
                scale   = normalize(option.get("scale", 0.5))
                curve   = prompt.get("curve", "weight")
                derived = apply_scale(curve, scale)
                # Only apply keys that belong to this curve
                from core.systems.curves import _SCALE_CURVES
                curve_keys = set(_SCALE_CURVES.get(curve, {}).keys())
                for key, val in derived.items():
                    if key in config and key in curve_keys:
                        config[key] = val
                for key in ("biome_key", "biome_secondary", "archetype"):
                    if key in option:
                        config[key] = option[key]

            elif prompt["type"] == "open":
                if pid == "q9" and answer:
                    config["label"] = answer
                elif pid == "q10":
                    if answer:
                        config["first_relic"]["archetypal_name"] = answer
                        config["first_relic"]["vibe"] = ", ".join(
                            str(v) for v in self.answers.values()
                            if v and isinstance(v, str) and v != answer
                        )
                    else:
                        config["first_relic"]["archetypal_name"] = "unnamed"

        weight_scale = self.scales.get("q5", 0.4)
        config["first_relic"]["impact_rating"] = max(1, min(10, int(1 + weight_scale * 9)))
        config["torch"]       = self.torch
        config["depth_score"] = self.depth_score
        return config

    def next_prompt(self):
        for prompt in self.prompts:
            if prompt["id"] not in self.answers:
                return prompt
        return None

    def run_in_terminal(self):
        print("\n" + "="*52)
        print("  SANCTUM TERMINAL")
        print("  All questions optional. Press Enter to skip.")
        print("="*52 + "\n")
        depth_index = 0
        for prompt in self.prompts:
            pid  = prompt["id"]
            text = prompt["prompt"]
            if prompt["type"] == "choice":
                print(f"  {text}")
                for key, opt in prompt["options"].items():
                    print(f"    [{key}] {opt['label']}")
                raw = input("  > ").strip().lower().replace(" ", "_")
                if raw in prompt["options"]:
                    self.answer(pid, raw)
                else:
                    self.skip(pid)
            elif prompt["type"] == "open":
                print(f"  {text}")
                raw = input("  > ").strip()
                if raw:
                    if _detect_commitment_depth(raw) == 1 and pid == "q10":
                        follow = _depth_prompt(raw, depth_index)
                        depth_index += 1
                        print(f"\n  > {follow}")
                        deeper = input("  > ").strip()
                        if deeper:
                            raw = deeper
                    self.answer(pid, raw)
                else:
                    self.skip(pid)
            print()
        result = self.resolve()
        print("="*52)
        print(f"  World seeded — {result['biome_key']}")
        print(f"  {result['torch']['name']}")
        print("="*52 + "\n")
        return result
