import json
from pathlib import Path


def _load_manifest():
    path = Path(__file__).parent.parent.parent / "config" / "manifest.json"
    if path.exists():
        return json.load(open(path))
    return {}


DEFAULTS = {
    "biome_key":         "VOID",
    "ambient_intensity":  0.4,
    "karma_baseline":     0.3,
    "spawn_radius":       40,
    "encounter_density":  0.3,
    "camera_speed":       40.0,
    "karma_decay_rate":   0.08,
    "first_relic": {
        "archetypal_name": "unnamed",
        "vibe":            "",
        "impact_rating":   3,
    }
}


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
    "torch", "fire", "light", "thing", "stuff", "idk",
    "nothing", "something", "whatever", "dunno", "ok",
    "yes", "no", "maybe", "sure", "fine", "good",
    "bad", "meh", "hmm", "um", "uh", "eh",
}

DEPTH_PROMPTS = [
    "What do you need to see?",
    "What are you trying to find your way through?",
    "What would having light change for you right now?",
    "What is in the dark that you would rather not look at?",
    "Where are you trying to go?",
]


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
    idx = rng_index % len(DEPTH_PROMPTS)
    return DEPTH_PROMPTS[idx]


class InterviewEngine:
    """
    World seed interview — 7 optional prompts that build a render config.
    No PII. No wrong answers. Your words stay in your vault.
    run_in_terminal() drives the interview from the CLI on first boot.
    """

    def __init__(self, config=None):
        self._config  = config or _load_manifest()
        self.prompts  = self._config.get("questionnaire", {}).get("prompts", [])
        self.answers     = {}
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
        required = [p["id"] for p in self.prompts
                    if not p.get("optional", False)]
        answered = all(qid in self.answers for qid in required)
        q7_done  = "q7" in self.answers
        if answered and q7_done:
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
                    f"InterviewEngine: '{value}' is not valid for {prompt_id}. "
                    f"Valid: {list(prompt['options'].keys())}"
                )
        if prompt_id == "q7":
            self.depth_score = _detect_commitment_depth(value)
            self._enhance_torch(value)
        self.answers[prompt_id] = value
        self._check_complete()
        return self

    def skip(self, prompt_id):
        prompt = self._get_prompt(prompt_id)
        if prompt is None:
            raise ValueError(f"InterviewEngine: unknown prompt '{prompt_id}'")
        if prompt_id == "q7":
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
            self.torch["name"]        = f"The {word.title()} Torch"
            self.torch["description"] = f"Made in the time of {word}. It carries that weight."
            self.torch["impact"]      = 4
            self.torch["ability"]     = "Wayfinding"
            self.torch["ability_desc"] = f"In moments of {word}, reveals a path others cannot see."
        elif self.depth_score == 3:
            self.torch["name"]        = f"The Torch of {word.title()}"
            self.torch["description"] = f"This torch was made in the time of {word}. Whoever carried this knew what they were walking toward."
            self.torch["impact"]      = 7
            self.torch["ability"]     = f"{word.title()} Light"
            self.torch["ability_desc"] = f"Born from {word}. Reveals hidden encounters in dense biomes. Can be shared."
            self.torch["transferable"] = True
            self.torch["rare"]         = True

    def resolve(self):
        config = dict(DEFAULTS)
        config["first_relic"] = dict(DEFAULTS["first_relic"])

        for prompt in self.prompts:
            pid    = prompt["id"]
            answer = self.answers.get(pid)
            if answer is None:
                answer = prompt.get("default")

            if prompt["type"] == "choice" and answer:
                options = prompt.get("options", {})
                params  = options.get(answer, {})
                for key, val in params.items():
                    if key == "label":
                        continue
                    if key in config:
                        config[key] = val

            elif prompt["type"] == "open":
                word = self.answers.get(pid)
                if word:
                    config["first_relic"]["archetypal_name"] = word
                    config["first_relic"]["vibe"] = ", ".join(
                        str(v) for v in self.answers.values()
                        if v and isinstance(v, str) and v != word
                    )
                else:
                    config["first_relic"]["archetypal_name"] = "unnamed"

        q5_prompt = self._get_prompt("q5")
        if q5_prompt:
            q5 = self.answers.get("q5", q5_prompt.get("default"))
            if q5:
                impact = q5_prompt["options"].get(q5, {}).get("impact_rating", 3)
                config["first_relic"]["impact_rating"] = impact

        config['torch']       = self.torch
        config['depth_score'] = self.depth_score
        return config

    def next_prompt(self):
        for prompt in self.prompts:
            if prompt["id"] not in self.answers:
                return prompt
        return None

    def run_in_terminal(self):
        """
        Drive the interview from the CLI.
        Prints each prompt, collects input, returns resolved config.
        Called by boot_biome_scene on first boot (no checkpoint).
        """
        print("\n" + "="*50)
        print("  SANCTUM TERMINAL — World Seed Interview")
        print("  All questions optional. Press Enter to skip.")
        print("="*50 + "\n")

        for prompt in self.prompts:
            pid  = prompt["id"]
            text = prompt["prompt"]

            if prompt["type"] == "choice":
                options = prompt["options"]
                print(f"  {text}")
                for key, opt in options.items():
                    print(f"    [{key}] {opt['label']}")
                raw = input("  > ").strip().lower().replace(" ", "_")
                if raw in options:
                    self.answer(pid, raw)
                else:
                    self.skip(pid)

            elif prompt["type"] == "open":
                print(f"  {text}")
                raw = input("  > ").strip()
                if raw:
                    self.answer(pid, raw)
                else:
                    self.skip(pid)

            print()

        result = self.resolve()
        print("="*50)
        print(f"  World seeded — {result['biome_key']}")
        print("="*50 + "\n")
        return result
