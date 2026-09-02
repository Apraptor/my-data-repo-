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
    if raw_id in special: return special[raw_id]
    return raw_id.replace("_", " ").title()

def normalize_form_modifier(form_part: str) -> str:
    mapping = {
        "alola": "alolan", 
        "galar": "galarian", 
        "hisui": "hisuian", 
        "paldea": "paldean",
        "a": "armored"
    }
    return mapping.get(form_part, form_part)

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
        "little": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-500.json",
        "great": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-1500.json",
        "ultra": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-2500.json",
        "master": "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/rankings/all/overall/rankings-10000.json"
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # ---------------------------------------------------------
    # 1. PARSE MOVES & BUILD RESOLVERS
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
            
            energy_delta = m.get("energyDelta", 0)
            is_fast = energy_delta > 0 or tid.endswith("_FAST")
            
            move_obj = {
                "id": string_id,
                "name": format_name(string_id.replace("_fast", "")),
                "type": normalize_type(m.get("pokemonType")),
                "kind": "fast" if is_fast else "charged",
                "power": round(float(m.get("power", 0.0)), 1),
                "durationMs": m.get("durationMs", 0)
            }
            if is_fast:
                move_obj["energyGain"] = max(0, energy_delta)
            else:
                move_obj["energyCost"] = abs(energy_delta)
                
            moves_list.append(move_obj)

    valid_moves = {m["id"] for m in moves_list}
    
    # Resolver to map PvPoke's stripped strings back to Game Master IDs (e.g. rollout -> rollout_fast)
    pvpoke_move_resolver = {}
    for m in valid_moves:
        pvpoke_move_resolver[m] = m
        if m.endswith("_fast"):
            pvpoke_move_resolver[m[:-5]] = m

    # ---------------------------------------------------------
    # 2. PARSE CORE (POKEMON & SETTINGS)
    # ---------------------------------------------------------
    species_map = {}
    settings_dict = {
        "levelCap": 50, "xlCandyMinPokemonLevel": 40,
        "cpMultiplier": [], "stardustCost": [], "candyCost": [], "xlCandyCost": [],
        "shadowStardustMultiplier": 1.2, "shadowCandyMultiplier": 1.2,
        "purifiedStardustMultiplier": 0.9, "purifiedCandyMultiplier": 0.9
    }

    for entry in raw_gm:
        tid = entry.get("templateId", "")
        data = entry.get("data", {})
        
        # Settings
        if tid == "PLAYER_LEVEL_SETTINGS":
            settings_dict["cpMultiplier"] = data.get("playerLevel", {}).get("cpMultiplier", [])
        elif tid == "POKEMON_UPGRADE_SETTINGS":
            settings_dict["stardustCost"] = data.get("pokemonUpgrades", {}).get("stardustCost", [])
            settings_dict["candyCost"] = data.get("pokemonUpgrades", {}).get("candyCost", [])
            settings_dict["xlCandyCost"] = data.get("pokemonUpgrades", {}).get("xlCandyCost", [])

        # Species
        if re.match(r"^V\d{4}_POKEMON_", tid):
            p = data.get("pokemonSettings")
            if not p: continue
            
            form = p.get("form", "")
            raw_pokemon_id = p.get("pokemonId", "")
            
            if "SHADOW" in form or "PURIFIED" in form:
                continue

            form_part = form.replace(raw_pokemon_id, "").strip("_").lower()
            form_part = form_part.replace("normal", "").strip("_")
            form_part = normalize_form_modifier(form_part)
            
            normalized_id = f"{raw_pokemon_id.lower()}_{form_part}" if form_part else raw_pokemon_id.lower()
            
            stats = p.get("stats") or {}
            types = [normalize_type(p.get("type"))]
            if p.get("type2"): types.append(normalize_type(p.get("type2")))
            
            def resolve_moves(move_list):
                return [move_id_map.get(str(m), str(m).lower()) for m in move_list if str(m) in move_id_map]

            if normalized_id not in species_map:
                s_obj = {
                    "id": normalized_id,
                    "dex": int(re.search(r"^V(\d{4})_", tid).group(1)),
                    "name": format_name(raw_pokemon_id),
                    "form": form_part if form_part else None,
                    "types": types,
                    "atk": stats.get("baseAttack", 0),
                    "def": stats.get("baseDefense", 0),
                    "hp": stats.get("baseStamina", 0),
                    "familyId": p.get("familyId", "").replace("FAMILY_", "").lower(),
                    "fastMoves": resolve_moves(p.get("quickMoves", [])),
                    "chargedMoves": resolve_moves(p.get("cinematicMoves", [])),
                    "eliteFastMoves": resolve_moves(p.get("eliteQuickMove", [])),
                    "eliteChargedMoves": resolve_moves(p.get("eliteCinematicMove", [])),
                    
                    # Temporary fields strictly used for the Tuple dedup algorithm below
                    "_stats_tuple": (
                        stats.get("baseAttack", 0), stats.get("baseDefense", 0), stats.get("baseStamina", 0),
                        types[0], types[1] if len(types) > 1 else ""
                    ),
                    "_base_pokemon_id": raw_pokemon_id.lower()
                }
                
                if not s_obj["eliteFastMoves"]: del s_obj["eliteFastMoves"]
                if not s_obj["eliteChargedMoves"]: del s_obj["eliteChargedMoves"]
                species_map[normalized_id] = s_obj

            current_species = species_map[normalized_id]

            # Parse Regular Evolutions
            evos = current_species.get("evolutions", [])
            for evo in p.get("evolutionBranch", []):
                if not isinstance(evo, dict): continue
                if "temporaryEvolution" in evo: continue 
                
                evo_id_raw = evo.get("form", evo.get("evolution", "")).lower()
                if not evo_id_raw or "mega" in evo_id_raw or "primal" in evo_id_raw: continue
                
                evo_base = evo.get("evolution", "").lower()
                evo_form_part = evo_id_raw.replace(evo_base, "").strip("_")
                evo_form_part = evo_form_part.replace("normal", "").strip("_")
                evo_form_part = normalize_form_modifier(evo_form_part)
                
                evo_id = f"{evo_base}_{evo_form_part}" if evo_form_part else evo_base
                
                e_obj = {"id": evo_id, "fallback_id": evo_base, "candy": evo.get("candyCost", 0)}
                if "candyCostPurified" in evo: e_obj["candyPurified"] = evo["candyCostPurified"]
                if "evolutionItemRequirement" in evo: e_obj["item"] = evo["evolutionItemRequirement"].replace("ITEM_", "").lower()
                if "kmBuddyDistanceRequirement" in evo: e_obj["kmBuddy"] = evo["kmBuddyDistanceRequirement"]
                if "questDisplay" in evo: e_obj["requires"] = "quest"
                
                if e_obj not in evos: evos.append(e_obj)
            current_species["evolutions"] = evos

            # Parse Megas/Primals
            megas = current_species.get("megaEvolutions", [])
            temp_branches = p.get("temporaryEvolutionBranch", [])
            for evo in p.get("evolutionBranch", []):
                if isinstance(evo, dict) and "temporaryEvolution" in evo:
                    temp_branches.append(evo)

            for temp in temp_branches:
                if not isinstance(temp, dict): continue
                temp_id_raw = temp.get("temporaryEvolution", "")
                if "MEGA" not in temp_id_raw and "PRIMAL" not in temp_id_raw: continue
                
                suffix_map = {
                    "TEMP_EVOLUTION_MEGA": "mega",
                    "TEMP_EVOLUTION_MEGA_X": "mega_x",
                    "TEMP_EVOLUTION_MEGA_Y": "mega_y",
                    "TEMP_EVOLUTION_PRIMAL": "primal"
                }
                suffix = suffix_map.get(temp_id_raw, temp_id_raw.lower().replace("temp_evolution_", ""))
                mega_id = f"{normalized_id}_{suffix}"
                
                m_obj = {
                    "id": mega_id,
                    "firstEnergy": temp.get("temporaryEvolutionEnergyCost", temp.get("firstTimeMegaEnergyCost", 0)),
                    "subsequentEnergy": temp.get("temporaryEvolutionEnergyCostSubsequent", temp.get("megaEnergyCost", 0))
                }
                if m_obj not in megas: megas.append(m_obj)
            
            if megas:
                current_species["megaEvolutions"] = megas

    # ---------------------------------------------------------
    # 2.5 APPLY TUPLE DEDUPLICATION RULE
    # ---------------------------------------------------------
    grouped_by_base = {}
    for s in species_map.values():
        grouped_by_base.setdefault(s["_base_pokemon_id"], []).append(s)
        
    deduped_species_list = []
    for base_id, forms in grouped_by_base.items():
        tuple_groups = {}
        for f in forms:
            tuple_groups.setdefault(f["_stats_tuple"], []).append(f)
            
        for t_key, f_list in tuple_groups.items():
            def form_priority(x):
                if x["form"] is None: return 0
                if x["form"] in ["alolan", "galarian", "hisuian", "paldean", "armored"]: return 1
                return 2
            
            best_form = sorted(f_list, key=form_priority)[0]
            del best_form["_stats_tuple"]
            del best_form["_base_pokemon_id"]
            deduped_species_list.append(best_form)
            
    species_map = {s["id"]: s for s in deduped_species_list}

    # ---------------------------------------------------------
    # Validation 1: Fail-fast and remap cosmetic evolution edges
    # ---------------------------------------------------------
    valid_species_ids = set(species_map.keys())
    species_list = list(species_map.values())
    
    for s in species_list:
        valid_evos = []
        seen_evos = set()
        for evo in s.get("evolutions", []):
            target_id = evo["id"]
            fallback_id = evo.pop("fallback_id", target_id)
            
            if target_id not in valid_species_ids:
                resolved = False
                if fallback_id in valid_species_ids:
                    target_id = fallback_id
                    resolved = True
                
                if not resolved:
                    matches = [k for k in valid_species_ids if k.startswith(target_id)]
                    if matches:
                        target_id = matches[0]
                        resolved = True
                        
                if not resolved:
                    matches = [k for k in valid_species_ids if k.startswith(fallback_id)]
                    if matches:
                        target_id = sorted(matches)[0]
                        resolved = True
                        
                if not resolved:
                    raise ValueError(f"CRITICAL: Target '{target_id}' (base: {fallback_id}) from '{s['id']}' doesn't resolve!")
            
            if target_id not in seen_evos:
                evo["id"] = target_id
                valid_evos.append(evo)
                seen_evos.add(target_id)
                
        s["evolutions"] = valid_evos

    with open("pogo_moves.json", "w", encoding="utf-8") as f:
        json.dump({"schemaVersion": 1, "generated": timestamp, "moves": moves_list}, f, separators=(',', ':'))

    with open("pogo_core.json", "w", encoding="utf-8") as f:
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
            
            if base_id not in valid_species_ids:
                continue 
                
            moveset = []
            for m in entry.get("moveset", []):
                m_low = m.lower()
                if m_low == "none":
                    continue
                
                # Resolving custom PvPoke IDs
                if m_low.startswith("hidden_power_"):
                    m_low = "hidden_power_fast"
                elif m_low.startswith("aegislash_"):
                    m_low = re.sub(r"^aegislash_(charge|shield)_", "", m_low)
                    
                m_low = pvpoke_move_resolver.get(m_low, m_low)
                if m_low in valid_moves:
                    moveset.append(m_low)

            # Validation 2: Enforce strict [fast, charged1, charged2] client rule
            # Non-viable Pokémon (like Unown) with fewer than 3 valid moves are dropped entirely
            if len(moveset) < 3 or not moveset[0].endswith("_fast"):
                continue

            league_arr.append({
                "id": base_id,
                "shadow": is_shadow,
                "rank": idx,
                "score": entry.get("score", 0.0),
                "moveset": moveset[:3]
            })
            
        rankings_output[league] = sorted(league_arr, key=lambda x: x["rank"])

    with open("pogo_meta_rankings.json", "w", encoding="utf-8") as f:
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
    
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        
    print("Generation complete.")

if __name__ == "__main__":
    build_pipeline()
