import json
import re
import urllib.request

URL = "https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/latest.json"
OUTPUT_FILE = "clean_pogo_data.json"

print("Downloading Game Master from PokeMiners...")
req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as response:
    raw_data = json.loads(response.read().decode())

pokemon_list = []
moves_list = []
settings = {}

pokemon_pattern = re.compile(r"^V\d{4}_POKEMON_")
move_pattern = re.compile(r"^V\d{4}_MOVE_")

print("Filtering categories...")
for entry in raw_data:
    tid = entry.get("templateId", "")
    data = entry.get("data", {})

    if pokemon_pattern.match(tid):
        p_settings = data.get("pokemonSettings")
        if p_settings:
            pokemon_list.append({
                "templateId": tid,
                "pokemonId": p_settings.get("pokemonId"),
                "form": p_settings.get("form"),
                "type": p_settings.get("type"),
                "type2": p_settings.get("type2"),
                "stats": p_settings.get("stats"),
                "quickMoves": p_settings.get("quickMoves", []),
                "cinematicMoves": p_settings.get("cinematicMoves", []),
                "eliteQuickMove": p_settings.get("eliteQuickMove", []),
                "eliteCinematicMove": p_settings.get("eliteCinematicMove", []),
                "evolutionBranch": p_settings.get("evolutionBranch", []),
                "temporaryEvolutionBranch": p_settings.get("temporaryEvolutionBranch", []),
                "familyId": p_settings.get("familyId")
            })

    elif move_pattern.match(tid):
        m_settings = data.get("moveSettings")
        if m_settings:
            moves_list.append({
                "templateId": tid,
                "movementId": m_settings.get("movementId"),
                "pokemonType": m_settings.get("pokemonType"),
                "power": m_settings.get("power", 0),
                "energyDelta": m_settings.get("energyDelta", 0),
                "durationMs": m_settings.get("durationMs", 0),
                "damageWindowStartMs": m_settings.get("damageWindowStartMs", 0),
                "damageWindowEndMs": m_settings.get("damageWindowEndMs", 0)
            })

    elif tid in ["POKEMON_UPGRADE_SETTINGS", "COMBAT_SETTINGS", "PLAYER_LEVEL_SETTINGS"]:
        settings[tid] = data

clean_output = {
    "pokemon": pokemon_list,
    "moves": moves_list,
    "settings": settings
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(clean_output, f, indent=2)

print("Done! Saved to", OUTPUT_FILE)
