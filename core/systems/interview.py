import json
from pathlib import Path


def _load_manifest():
    path = Path(__file__).parent.parent.parent / "config" / "manifest.json"
    if path.exists():
        return json.load(open(path))
    return {}


# Default render config — used when questions are skipped
DEFAULTS = {
    "biome_key":        "VOID",
    "ambient_intensity": 0.4,
    "karma_baseline":    0.3,
    "spawn_radius":      40,
    "encounter_density": 0.3,
    "camera_speed":      40.0,
    "karma_decay_rate":  0.08,
    "first_relic": {
        "archetypal_name": "unnamed",
        "vibe":            "",
        "impact_rating":   3,
    }
}


class InterviewEngine:
    """
    World seed interview — 7 optional prompts that build a render config.
    No PII. No wrong answers. Your words stay in your vault.
    Each answer maps directly to BiomeRenderer + SeedEngine parameters.
    Fires on_complete callback when all non-optional prompts are answered.
    """

    def __init__(self, config=None):
        self._config  = config or _load_manifest()
        self.prompts  = self._config.get("questionnaire", {}).get("prompts", [])
        self.answers  = {}
        self.complete = False
        self.on_complete = None

    # ── Private ───────────────────────────────────────────────────────────────

    def _get_prompt(self, prompt_id):
        for p in self.prompts:
            if p["id"] == prompt_id:
                return p
        return None

    def _check_complete(self):
        """
        Complete when all non-optional prompts have answers.
        Q7 is optional — skipped answers count as None.
        """
        required = [p["id"] for p in self.prompts
                    if not p.get("optional", False)]
        answered = all(qid in self.answers for qid in required)
        # q7 always counts — None is a valid answer
        q7_done  = "q7" in self.answers
        if answered and q7_done:
            self.complete = True
            if callable(self.on_complete):
                self.on_complete(self.resolve())

    # ── Public API ────────────────────────────────────────────────────────────

    def answer(self, prompt_id, value):
        """
        Record an answer to a prompt.
        Raises ValueError for unknown prompts or invalid options.
        Open questions (q7) accept any string or None.
        """
        prompt = self._get_prompt(prompt_id)
        if prompt is None:
            raise ValueError(
                f"InterviewEngine: unknown prompt '{prompt_id}'"
            )

        if prompt["type"] == "choice":
            if value not in prompt["options"]:
                raise ValueError(
                    f"InterviewEngine: '{value}' is not a valid option for {prompt_id}. "
                    f"Valid: {list(prompt['options'].keys())}"
                )

        self.answers[prompt_id] = value
        self._check_complete()
        return self

    def resolve(self):
        """
        Resolve all answers into a render config dict.
        Missing answers fall back to DEFAULTS.
        Returns dict ready for boot_biome_scene().
        """
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

        # impact_rating from q5
        q5 = self.answers.get("q5", prompt.get("default") if (prompt := self._get_prompt("q5")) else None)
        if q5:
            q5_prompt = self._get_prompt("q5")
            if q5_prompt:
                impact = q5_prompt["options"].get(q5, {}).get("impact_rating", 3)
                config["first_relic"]["impact_rating"] = impact

        return config

    def next_prompt(self):
        """Returns the next unanswered prompt or None if complete."""
        for prompt in self.prompts:
            if prompt["id"] not in self.answers:
                return prompt
        return None

    def skip(self, prompt_id):
        """Skip an optional prompt — records None as the answer."""
        prompt = self._get_prompt(prompt_id)
        if prompt is None:
            raise ValueError(f"InterviewEngine: unknown prompt '{prompt_id}'")
        self.answers[prompt_id] = None
        self._check_complete()
        return self
