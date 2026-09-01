import json
import os
import re
import urllib.request
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0"}
STATE_FILE = "version.json"


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as response:
        return response.read()


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def main():
    state = load_state()
    ts_url = "https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/timestamp.txt"
    gm_url = "https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/latest.json"

    print("Checking PokeMiners Game Master timestamp...")
    latest_ts = fetch_bytes(ts_url).decode("utf-8").strip()

    if latest_ts == state.get("pogoDataTimestamp") and os.path.exists("clean_pogo_data.json"):
        print(f"No Game Master changes (Timestamp: {latest_ts}). Exiting.")
        return

    print(f"New Game Master detected ({latest_ts}). Downloading and filtering...")
    raw_json = json.loads(fetch_bytes(gm_url).decode("utf-8"))

    pokemon_list = []
    moves_list = []
    settings = {}

    pokemon_pattern = re.compile(r"^V\d{4}_POKEMON_")
    move_pattern = re.compile(r"^V\d{4}_MOVE_")

    for entry in raw_json:
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

    clean_payload = {
        "pokemon": pokemon_list,
        "moves": moves_list,
        "settings": settings
    }

    with open("clean_pogo_data.json", "w", encoding="utf-8") as f:
        json.dump(clean_payload, f, separators=(",", ":"))

    state["pogoDataTimestamp"] = latest_ts
    state["pogoDataVersion"] = int(datetime.now(timezone.utc).timestamp())
    state["lastUpdated"] = datetime.now(timezone.utc).isoformat()

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print("Successfully updated clean_pogo_data.json and version.json.")


if __name__ == "__main__":
    main()
