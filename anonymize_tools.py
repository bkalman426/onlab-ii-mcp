"""
A versenytárs kereső tool-ok anonimizált változatának elkészítése.

A csere-táblázat (anon_replacements.json) alapján:
  - minden kereső tool neve egységesen 'web_search' lesz,
  - a leírásokból és a paraméterleírásokból kikerülnek a márka- és szolgáltatónevek,
  - a márkára utaló paraméternevek és enum-értékek semleges nevet kapnak.
A képesség-állítások és a szerkezet változatlanok maradnak.

A szerver valódi neve (brave, exa, ...) a fájlban megmarad: a modell nem ezt látja,
hanem a harness által kérdésenként kiosztott álnevet (server_aliases).

Futtatás:  python anonymize_tools.py            → clean_anon/<szerver>_anon.json
           python anonymize_tools.py --diff     → a változások kiírása is
"""

import argparse
import json
import re
from datetime import date
from pathlib import Path


def replace_text(s, pairs, used):
    for find, repl in pairs:
        if find in s:
            used.add(find)
            s = s.replace(find, repl)
    return s


def transform(obj, pairs, enum_map, prop_map, used, path=""):
    """Rekurzívan cseréli a szövegeket (description), az enum-értékeket és a paraméterneveket."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            new_k = k
            if path.endswith("properties") and k in prop_map:
                new_k = prop_map[k]
                used.add(f"property:{k}")
            if k == "required" and isinstance(v, list):
                out[new_k] = [prop_map.get(x, x) for x in v]
                continue
            if k == "enum" and isinstance(v, list):
                out[new_k] = [enum_map.get(x, x) if isinstance(x, str) else x for x in v]
                used.update(f"enum:{x}" for x in v if isinstance(x, str) and x in enum_map)
                continue
            if k == "description" and isinstance(v, str):
                out[new_k] = replace_text(v, pairs, used)
                continue
            out[new_k] = transform(v, pairs, enum_map, prop_map, used, f"{path}/{k}")
        return out
    if isinstance(obj, list):
        return [transform(v, pairs, enum_map, prop_map, used, path) for v in obj]
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="anon_replacements.json")
    ap.add_argument("--out", default="clean_anon")
    ap.add_argument("--diff", action="store_true", help="a régi és új leírás kiírása")
    args = ap.parse_args()

    table = json.loads(Path(args.table).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    forbidden = [re.compile(p, re.IGNORECASE) for p in table["forbidden_patterns"]]
    problems = []

    for server, spec in table["tools"].items():
        snap = json.loads(Path(spec["source"]).read_text(encoding="utf-8"))
        tool = next(t for t in snap["tools"] if t["name"] == spec["tool"])
        pairs = table["text_replacements"].get(server, [])
        enum_map = table.get("enum_replacements", {}).get(server, {})
        prop_map = table.get("property_renames", {}).get(server, {})
        used = set()

        new_tool = {
            "name": table["new_tool_name"],
            "description": replace_text(tool.get("description", ""), pairs, used),
            "inputSchema": transform(tool.get("inputSchema", {}), pairs, enum_map, prop_map, used),
        }

        # Minden csere-szabálynak illeszkednie kell valahol (különben elírás vagy változott a forrás).
        unused = [f for f, _ in pairs if f not in used]
        unused += [f"property:{k}" for k in prop_map if f"property:{k}" not in used]
        unused += [f"enum:{k}" for k in enum_map if f"enum:{k}" not in used]
        if unused:
            problems.append(f"{server}: nem illeszkedő csere-szabályok: {unused}")

        # Nem maradhat márkanév (a tool nevében, a leírásban, a sémában és a paraméternevekben sem).
        blob = json.dumps(new_tool, ensure_ascii=False)
        left = sorted({m.group(0) for p in forbidden for m in p.finditer(blob)})
        if left:
            problems.append(f"{server}: maradt márkautalás: {left}")

        snapshot = {
            "server": server,
            "version": f"{snap.get('version')}-anon",
            "anonymized_from": spec["source"],
            "original_tool_name": spec["tool"],
            "processed_date": date.today().isoformat(),
            "tools": [new_tool],
        }
        out_path = out_dir / f"{server}_anon.json"
        out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] {server}: {spec['tool']} -> {new_tool['name']}  ({len(used)} csere)  -> {out_path}")
        if args.diff:
            print(f"   RÉGI: {tool['description'][:300]!r}")
            print(f"   ÚJ:   {new_tool['description'][:300]!r}")

    if problems:
        print("\nHIBA:")
        for p in problems:
            print("  " + p)
        raise SystemExit(1)
    print("\nEllenőrzés rendben: minden szabály illeszkedett, és nem maradt márkautalás.")


if __name__ == "__main__":
    main()