import hashlib
import json
import os
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
    leagues = {
        "great": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-1500.json",
        "ultra": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-2500.json"
    }

    formatted_rankings = {}

    print("Fetching PvPoke rankings for Great and Ultra Leagues...")
    for league_name, url in leagues.items():
        raw_data = fetch_bytes(url)
        league_json = json.loads(raw_data.decode("utf-8"))

        league_dict = {}
        for idx, entry in enumerate(league_json, start=1):
            species_id = entry.get("speciesId")
            if not species_id:
                continue

            league_dict[species_id] = {
                "rank": idx,
                "score": entry.get("score", 0.0),
                "moveset": entry.get("moveset", [])
            }

        formatted_rankings[league_name] = league_dict

    serialized_data = json.dumps(formatted_rankings, separators=(",", ":")).encode("utf-8")
    new_hash = hashlib.sha256(serialized_data).hexdigest()

    if new_hash == state.get("metaRankingsHash") and os.path.exists("meta_rankings.json"):
        print(f"No PvPoke changes (SHA: {new_hash[:8]}...). Exiting.")
        return

    print(f"New PvPoke data detected (SHA: {new_hash[:8]}...). Writing meta_rankings.json...")
    with open("meta_rankings.json", "wb") as f:
        f.write(serialized_data)

    state["metaRankingsHash"] = new_hash
    state["metaRankingsVersion"] = int(datetime.now(timezone.utc).timestamp())
    state["lastUpdated"] = datetime.now(timezone.utc).isoformat()

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print("Successfully updated meta_rankings.json and version.json.")


if __name__ == "__main__":
    main()
