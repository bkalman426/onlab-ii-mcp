"""
MCP tool-definíciók tisztítása és statisztikák.

Bemenet:  tools/<szerver>_tools_v<verzió>.json   (nyers `tools/list` kimenet)
Kimenet:  clean/<szerver>_v<verzió>.json         (csak name, description, inputSchema)
          stats.csv                              (tool-onkénti statisztikák)

Futtatás:  python extract_tools.py
           python extract_tools.py --in tools --out clean
"""

import argparse
import csv
import json
import re
from datetime import date, datetime
from pathlib import Path

# A modellnek átadott mezők (a hostok jellemzően csak ezeket adják át).
KEEP_FIELDS = ("name", "description", "inputSchema")

# Heurisztikus jelzőszavak a leírásokban. Csak segítség az átnézéshez, nem besorolás.
FLAG_PATTERNS = {
    "steering": r"\b(always|default|prefer(red)?|instead of|must|should use|use this)\b",
    "superlative": r"\b(best|most|fastest|highest|leading|top|powerful|unparalleled)\b",
    "capability": r"\b(comprehensive|rich|optimi[sz]ed|accurate|reliable|precise|advanced|clean|ready-to-use)\b",
    "freshness": r"\b(real-?time|fresh(est)?|up-to-date|latest|current|live)\b",
    "ai_target": r"\b(llm|ai agents?|rag|grounding|agentic)\b",
}

FILENAME_RE = re.compile(r"^(?P<server>.+?)_tools_v(?P<version>[\d_]+)\.json$", re.IGNORECASE)


def load_raw(path: Path) -> dict:
    """Beolvassa a nyers fájlt; kezeli az UTF-16-ot (PowerShell) és a JSON előtti szemetet (npx kérdés)."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    start = text.find("{")
    if start == -1:
        raise ValueError("nincs JSON objektum a fájlban")
    return json.loads(text[start:])


def count_tokens_factory():
    """tiktoken, ha telepítve van; különben kb. 4 karakter = 1 token becslés."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s))), "tiktoken cl100k_base"
    except ImportError:
        return (lambda s: round(len(s) / 4)), "becslés (karakter/4)"


def tool_stats(server: str, version: str, tool: dict, count_tokens) -> dict:
    desc = tool.get("description") or ""
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    schema_json = json.dumps(schema, ensure_ascii=False)
    tool_json = json.dumps(tool, ensure_ascii=False)

    row = {
        "server": server,
        "version": version,
        "tool": tool.get("name", ""),
        "desc_chars": len(desc.strip()),
        "desc_words": len(desc.split()),
        "n_params": len(props),
        "n_required": len(required),
        "n_params_with_desc": sum(1 for p in props.values() if isinstance(p, dict) and p.get("description")),
        "schema_chars": len(schema_json),
        "desc_tokens": count_tokens(desc),
        "total_tokens": count_tokens(tool_json),
    }
    low = desc.lower()
    for key, pattern in FLAG_PATTERNS.items():
        hits = sorted({m.group(0) for m in re.finditer(pattern, low)})
        row[f"flag_{key}"] = ";".join(hits)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", default="tools")
    ap.add_argument("--out", dest="out_dir", default="clean")
    ap.add_argument("--stats", default="stats.csv")
    args = ap.parse_args()

    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    count_tokens, tok_method = count_tokens_factory()

    rows = []
    for path in sorted(in_dir.glob("*.json")):
        m = FILENAME_RE.match(path.name)
        if not m:
            print(f"[kihagyva] {path.name}: a név nem <szerver>_tools_v<verzió>.json formájú")
            continue
        server = m.group("server").lower()
        version = m.group("version").replace("_", ".")
        try:
            raw = load_raw(path)
        except Exception as e:
            print(f"[HIBA] {path.name}: {e}")
            continue

        tools = [{k: t[k] for k in KEEP_FIELDS if k in t} for t in raw.get("tools", [])]
        snapshot = {
            "server": server,
            "version": version,
            "snapshot_date": datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
            "processed_date": date.today().isoformat(),
            "source_file": path.name,
            "tools": tools,
        }
        out_path = out_dir / f"{server}_v{m.group('version')}.json"
        out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        for t in tools:
            rows.append(tool_stats(server, version, t, count_tokens))
        print(f"[ok] {path.name}: {len(tools)} tool -> {out_path}")

    if not rows:
        print("Nem készült statisztika.")
        return

    with open(args.stats, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel is jól nyitja
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Rövid összesítő a konzolra
    print(f"\nTokenszámolás: {tok_method}")
    header = f"{'szerver':<12}{'tool':<34}{'leírás(szó)':>12}{'param':>7}{'kötelező':>10}{'token':>8}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['server']:<12}{r['tool'][:33]:<34}{r['desc_words']:>12}{r['n_params']:>7}{r['n_required']:>10}{r['total_tokens']:>8}")

    print("\nSzerverenként (az összes tool együtt, ennyit kap a modell, ha a teljes szerver telepítve van):")
    totals = {}
    for r in rows:
        t = totals.setdefault(r["server"], {"tools": 0, "tokens": 0})
        t["tools"] += 1
        t["tokens"] += r["total_tokens"]
    for s, t in totals.items():
        print(f"  {s:<12}{t['tools']:>3} tool  {t['tokens']:>7} token")

    print(f"\nRészletek (jelzőszavakkal): {args.stats}")


if __name__ == "__main__":
    main()