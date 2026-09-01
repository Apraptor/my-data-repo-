import hashlib
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0"}
INDEX_FILE = "pogo_index.json"

def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as response:
        return response.read()

def normalize_id(raw_id: str) -> str:
    if not raw_id: return ""
    return re.sub(r"^V\d+_POKEMON_", "", raw_id).lower()

def normalize_type(raw_type: str) -> str:
    if not raw_type: return ""
    return raw_type.replace("POKEMON_TYPE_", "").lower()

def format_name(raw_id: str) -> str:
    special = {
        "NIDORAN_FEMALE": "Nidoran♀", "NIDORAN_MALE": "Nidoran♂",
        "MR_MIME": "Mr. Mime", "MIME_JR": "Mime Jr.",
        "FARFETCHD": "Farfetch'd", "SIRFETCHD": "Sirfetch'd",
        "HO_OH": "Ho-Oh", "PORYGON2": "Porygon2", "PORYGON_Z": "Porygon-Z",
        "FLABEBE": "Flabébé"
    }
    if raw_id in special:
        return special[raw_id]
    return raw_id.replace("_", " ").title()

def get_file_stats(filename: str) -> dict:
    with open(filename, "rb") as f:
        data = f.read()
    return {
        "url": filename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "sizeBytes": len(data)
    }

def build_pipeline():
    print("Fetching Game Master and PvPoke datasets...")
    gm_url = "https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/latest.json"
    raw_gm = json.loads(fetch_bytes(gm_url).decode("utf-8"))

    pvpoke_urls = {
        "great": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-1500.json",
        "ultra": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-2500.json",
        "master": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-10000.json"
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # ---------------------------------------------------------
    # 1. PARSE MOVES & BUILD LOOKUP DICT
    # ---------------------------------------------------------
    moves_list = []
    move_id_map = {} 
    
    for entry in raw_gm:
        tid = entry.get("templateId", "")
        if re.match(r"^V\d{4}_MOVE_", tid):
            m = entry.get("data", {}).get("moveSettings", {})
            if not m: continue
            
            numeric_id = str(m.get("movementId", ""))
            string_id = tid.split("_MOVE_")[1].lower()
            move_id_map[numeric_id] = string_id
            move_id_map[string_id.upper()] = string_id
            
            is_fast = m.get("energyDelta", 0) > 0
            
            move_obj = {
                "id": string_id,
                "name": format_name(string_id.replace("_fast", "")),
                "type": normalize_type(m.get("pokemonType")),
                "kind": "fast" if is_fast else "charged",
                "power": m.get("power", 0.0),
                "durationMs": m.get("durationMs", 0)
            }
            if is_fast:
                move_obj["energyGain"] = m.get("energyDelta", 0)
            else:
                move_obj["energyCost"] = abs(m.get("energyDelta", 0))
                
            buffs = m.get("vfxName", "") # Fallback simplification, proper buff extraction omitted for brevity if nested deeply
            
            moves_list.append(move_obj)
            
    with open("pogo_moves.json", "w") as f:
        json.dump({"schemaVersion": 1, "generated": timestamp, "moves": moves_list}, f, separators=(',', ':'))

    # ---------------------------------------------------------
    # 2. PARSE CORE (POKEMON & SETTINGS)
    # ---------------------------------------------------------
    species_list = []
    settings_dict = {
        "levelCap": 50,
        "xlCandyMinPokemonLevel": 40,
        "cpMultiplier": [], "stardustCost": [], "candyCost": [], "xlCandyCost": [],
        "shadowStardustMultiplier": 1.2, "shadowCandyMultiplier": 1.2,
        "purifiedStardustMultiplier": 0.9, "purifiedCandyMultiplier": 0.9
    }
    
    base_stats_cache = {}

    for entry in raw_gm:
        tid = entry.get("templateId", "")
        data = entry.get("data", {})
        
        # Parse Settings
        if tid == "PLAYER_LEVEL_SETTINGS":
            settings_dict["cpMultiplier"] = data.get("playerLevel", {}).get("cpMultiplier", [])
        elif tid == "POKEMON_UPGRADE_SETTINGS":
            settings_dict["stardustCost"] = data.get("pokemonUpgrades", {}).get("stardustCost", [])
            settings_dict["candyCost"] = data.get("pokemonUpgrades", {}).get("candyCost", [])
            settings_dict["xlCandyCost"] = data.get("pokemonUpgrades", {}).get("xlCandyCost", [])

        # Parse Pokemon
        if re.match(r"^V\d{4}_POKEMON_", tid):
            p = data.get("pokemonSettings")
            if not p: continue
            
            form = p.get("form", "")
            raw_pokemon_id = p.get("pokemonId", "")
            
            # Filter out shadows, purified, and standard normal duplicates
            if "SHADOW" in form or "PURIFIED" in form or form.endswith("_NORMAL"):
                continue

            base_key = raw_pokemon_id
            stats = p.get("stats", {})
            types = [normalize_type(p.get("type"))]
            if p.get("type2"): types.append(normalize_type(p.get("type2")))
            
            # Meaningful form check
            is_base = (form == "" or form == base_key)
            if is_base:
                base_stats_cache[base_key] = {"stats": stats, "types": types}
            else:
                # If not a regional variant and stats/types match base, skip cosmetic duplicate
                is_regional = any(reg in form for reg in ["ALOLAN", "GALARIAN", "HISUIAN", "PALDEAN"])
                base_ref = base_stats_cache.get(base_key)
                if base_ref and not is_regional:
                    if base_ref["stats"] == stats and base_ref["types"] == types:
                        continue

            normalized_id = form.lower() if form else raw_pokemon_id.lower()
            display_form = normalized_id.replace(raw_pokemon_id.lower(), "").strip("_")
            
            def resolve_moves(move_list):
                return [move_id_map.get(str(m), str(m).lower()) for m in move_list if str(m) in move_id_map]

            s_obj = {
                "id": normalized_id,
                "dex": int(re.search(r"^V(\d{4})_", tid).group(1)),
                "name": format_name(raw_pokemon_id),
                "form": display_form if display_form else None,
                "types": types,
                "atk": stats.get("baseAttack", 0),
                "def": stats.get("baseDefense", 0),
                "hp": stats.get("baseStamina", 0),
                "familyId": p.get("familyId", "").replace("FAMILY_", "").lower(),
                "fastMoves": resolve_moves(p.get("quickMoves", [])),
                "chargedMoves": resolve_moves(p.get("cinematicMoves", []))
            }
            
            # Elite Moves
            elite_fast = resolve_moves(p.get("eliteQuickMove", []))
            elite_charged = resolve_moves(p.get("eliteCinematicMove", []))
            if elite_fast: s_obj["eliteFastMoves"] = elite_fast
            if elite_charged: s_obj["eliteChargedMoves"] = elite_charged

            # Evolutions (Stripping nulls)
            evos = []
            for evo in p.get("evolutionBranch", []):
                evo_id = evo.get("form", evo.get("evolution", "")).lower()
                if not evo_id or "mega" in evo_id.lower(): continue
                
                e_obj = {"id": evo_id, "candy": evo.get("candyCost", 0)}
                if "candyCostPurified" in evo: e_obj["candyPurified"] = evo["candyCostPurified"]
                if "evolutionItemRequirement" in evo: e_obj["item"] = evo["evolutionItemRequirement"].replace("ITEM_", "").lower()
                if "kmBuddyDistanceRequirement" in evo: e_obj["kmBuddy"] = evo["kmBuddyDistanceRequirement"]
                if "questDisplay" in evo: e_obj["requires"] = "quest"
                evos.append(e_obj)
                
            s_obj["evolutions"] = evos

            # Megas
            megas = []
            evo_overrides = {o["tempEvoId"]: o for o in p.get("tempEvoOverrides", [])}
            
            for temp in p.get("temporaryEvolutionBranch", []):
                temp_id_raw = temp.get("temporaryEvolution", "")
                if "MEGA" not in temp_id_raw and "PRIMAL" not in temp_id_raw: continue
                
                # Suffix formatting (e.g. charizard_mega_x)
                suffix = temp_id_raw.replace("TEMP_EVOLUTION_", "").lower()
                mega_id = f"{normalized_id}_{suffix}"
                
                mega_obj = {
                    "id": mega_id,
                    "firstEnergy": temp.get("firstTimeMegaEnergyCost", 0),
                    "subsequentEnergy": temp.get("megaEnergyCost", 0)
                }
                
                # Attach stats/types if present in overrides
                override = evo_overrides.get(temp_id_raw)
                if override:
                    o_stats = override.get("stats", {})
                    mega_obj["atk"] = o_stats.get("baseAttack", 0)
                    mega_obj["def"] = o_stats.get("baseDefense", 0)
                    mega_obj["hp"] = o_stats.get("baseStamina", 0)
                    m_types = [normalize_type(override.get("typeOverride1"))]
                    if override.get("typeOverride2"): m_types.append(normalize_type(override.get("typeOverride2")))
                    mega_obj["types"] = m_types
                    
                megas.append(mega_obj)

            if megas:
                s_obj["megaEvolutions"] = megas

            species_list.append(s_obj)

    with open("pogo_core.json", "w") as f:
        json.dump({"schemaVersion": 1, "generated": timestamp, "species": species_list, "settings": settings_dict}, f, separators=(',', ':'))

    # ---------------------------------------------------------
    # 3. PARSE RANKINGS
    # ---------------------------------------------------------
    rankings_output = {}
    for league, url in pvpoke_urls.items():
        try:
            raw_data = fetch_bytes(url)
            league_json = json.loads(raw_data.decode("utf-8"))
        except Exception:
            continue
            
        league_arr = []
        for idx, entry in enumerate(league_json, start=1):
            species_id = entry.get("speciesId", "")
            if not species_id: continue
            
            is_shadow = species_id.endswith("_shadow")
            base_id = species_id.replace("_shadow", "")
            
            moveset = [m.lower() for m in entry.get("moveset", [])]

            league_arr.append({
                "id": base_id,
                "shadow": is_shadow,
                "rank": idx,
                "score": entry.get("score", 0.0),
                "moveset": moveset
            })
            
        rankings_output[league] = league_arr

    with open("pogo_meta_rankings.json", "w") as f:
        json.dump({"schemaVersion": 1, "generated": timestamp, "leagues": rankings_output}, f, separators=(',', ':'))

    # ---------------------------------------------------------
    # 4. GENERATE MANIFEST
    # ---------------------------------------------------------
    manifest = {
        "schemaVersion": 1,
        "generated": timestamp,
        "gameMasterCommit": "latest",
        "files": {
            "core": get_file_stats("pogo_core.json"),
            "moves": get_file_stats("pogo_moves.json"),
            "rankings": get_file_stats("pogo_meta_rankings.json")
        }
    }
    
    with open(INDEX_FILE, "w") as f:
        json.dump(manifest, f, indent=2)
        
    print("Generation complete.")

if __name__ == "__main__":
    build_pipeline()
