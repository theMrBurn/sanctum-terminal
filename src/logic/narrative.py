# src/logic/narrative.py
import random

SUCCESS_TEMPLATES = [
    "Scout successful in {city}. Recovered {fragment_type} fragments from a derelict server.",
    "Bypassed {city} security nodes. Vault balance synchronized.",
    "Environmental sensors in {city} provided cover for a clean data extraction.",
    "Signal strength peaked in {city}. Transmitted digital relics to the Sanctum."
]

FAILURE_TEMPLATES = [
    "Scout compromised in {city}. Signal lost due to {condition}.",
    "Sanctum uplink failed. {city} interference levels too high.",
    "Resource extraction aborted. {city} hazards exceeded safety thresholds.",
    "Static discharge in {city} corrupted the local fragment cache."
]

def get_mission_log(success: bool, city: str, condition: str) -> str:
    templates = SUCCESS_TEMPLATES if success else FAILURE_TEMPLATES
    # We can eventually map fragment_type to player bias
    return random.choice(templates).format(
        city=city, 
        condition=condition, 
        fragment_type="encrypted"
    )