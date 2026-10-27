"""
Tool-választási kísérlet futtatója (egylépéses harness).

Minden futás egyetlen modellhívás: a modell megkapja a kérdést és a tool-listát,
mi pedig rögzítjük, melyik tool-t hívja meg (ha egyáltalán hív).

Futtatás (a projekt mappájából, aktivált .venv-vel):
    python run_selection.py experiment_pilot.json --dry-run     # terv + token-becslés, hívás nélkül
    python run_selection.py experiment_pilot.json --limit 3      # 3 próbahívás
    python run_selection.py experiment_pilot.json                # teljes futás (folytatható)

A kész mérések a konfigurációban megadott JSONL-fájlba kerülnek. Ha a futás
megszakad (pl. elfogy a napi keret), újraindításkor a sikeres méréseket
kihagyja, és csak a hiányzókat (és a hibásakat) futtatja.
"""

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Segédfüggvények
# ---------------------------------------------------------------------------

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def strip_keys(obj, keys):
    """Rekurzívan eltávolítja a megadott kulcsokat (pl. "$schema") a sémából."""
    if isinstance(obj, dict):
        return {k: strip_keys(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [strip_keys(v, keys) for v in obj]
    return obj


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Tool-listák összeállítása
# ---------------------------------------------------------------------------

def load_servers(cfg, base: Path):
    servers = {}
    for name, rel in cfg["servers"].items():
        snap = load_json(base / rel)
        servers[name] = {"version": snap.get("version"), "file": rel,
                         "tools": {t["name"]: t for t in snap["tools"]}}
    return servers


def own_tool_def(variants, own_spec):
    v = next((x for x in variants["description_variants"] if x["id"] == own_spec["description"]), None)
    if v is None:
        raise SystemExit(f"Ismeretlen leírásváltozat: {own_spec['description']}")
    if own_spec["params"] not in variants["param_sets"]:
        raise SystemExit(f"Ismeretlen paraméterkészlet: {own_spec['params']}")
    return {"name": variants["tool_name"], "description": v["description"],
            "inputSchema": variants["param_sets"][own_spec["params"]]}


def build_blocks(cfg, servers, variants, condition):
    """Szerverenként csoportosított tool-blokkok (a hostok is szerverenként sorolják fel a tool-okat)."""
    env_name = condition["environment"]
    env = cfg["environments"].get(env_name)
    if env is None:
        raise SystemExit(f"Ismeretlen környezet: {env_name}")
    blocks = []
    for server, selection in env.items():
        if server not in servers:
            raise SystemExit(f"A(z) '{server}' szerver nincs a 'servers' listában")
        available = servers[server]["tools"]
        names = list(available) if selection == "*" else selection
        missing = [n for n in names if n not in available]
        if missing:
            raise SystemExit(f"Nincs ilyen tool a(z) '{server}' szerverben: {missing}")
        blocks.append((server, [available[n] for n in names]))
    if condition.get("own"):
        if variants is None:
            raise SystemExit(f"A(z) '{condition['id']}' feltétel saját tool-t kér, "
                             f"de a konfigurációban nincs 'own_tool_file'.")
        blocks.append((variants["server_name"], [own_tool_def(variants, condition["own"])]))
    return blocks


def rotation_offsets(n_blocks, spec):
    if spec == "all":
        return list(range(n_blocks))
    k = max(1, min(int(spec), n_blocks))
    return sorted({round(i * n_blocks / k) % n_blocks for i in range(k)})


def flatten(blocks, offset, name_fmt, strip):
    rotated = blocks[offset:] + blocks[:offset]
    tools, name_map = [], {}
    for server, tlist in rotated:
        for t in tlist:
            full = name_fmt.format(server=server, tool=t["name"])
            name_map[full] = (server, t["name"])
            tools.append({"name": full,
                          "description": t.get("description") or "",
                          "schema": strip_keys(t.get("inputSchema") or {"type": "object", "properties": {}}, strip)})
    return rotated, tools, name_map


# ---------------------------------------------------------------------------
# Modellszolgáltatók
# ---------------------------------------------------------------------------

class GeminiProvider:
    name = "gemini"

    def __init__(self, model, mcfg):
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client()  # a GEMINI_API_KEY környezeti változót használja
        self.model = model
        self.mcfg = mcfg

    def call(self, system, tools, query, tool_mode):
        t = self.types
        decls = [t.FunctionDeclaration(name=x["name"], description=x["description"],
                                       parameters_json_schema=x["schema"]) for x in tools]
        extra = {}
        if self.mcfg.get("temperature") is not None:
            extra["temperature"] = self.mcfg["temperature"]
        config = t.GenerateContentConfig(
            system_instruction=system,
            tools=[t.Tool(function_declarations=decls)],
            tool_config=t.ToolConfig(function_calling_config=t.FunctionCallingConfig(mode=tool_mode.upper())),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            **extra,
        )
        resp = self.client.models.generate_content(model=self.model, contents=query, config=config)
        calls, texts = [], []
        cand = resp.candidates[0] if resp.candidates else None
        if cand is not None and cand.content is not None and cand.content.parts:
            for p in cand.content.parts:
                if p.function_call is not None:
                    calls.append({"name": p.function_call.name, "args": p.function_call.args or {}})
                elif p.text and not getattr(p, "thought", False):
                    texts.append(p.text)
        u = resp.usage_metadata
        usage = {}
        if u is not None:
            usage = {"input": u.prompt_token_count, "output": u.candidates_token_count,
                     "thinking": getattr(u, "thoughts_token_count", None)}
        return {"calls": calls, "text": "\n".join(texts),
                "finish_reason": str(cand.finish_reason) if cand is not None else None, "usage": usage,
                # A ténylegesen válaszoló modell verziója (eltérhet a kért névtől, ha az alias).
                "model_version": getattr(resp, "model_version", None)}

    @staticmethod
    def error_code(e):
        return getattr(e, "code", None)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model, mcfg):
        import anthropic
        self.client = anthropic.Anthropic()  # az ANTHROPIC_API_KEY környezeti változót használja
        self.model = model
        self.mcfg = mcfg

    def call(self, system, tools, query, tool_mode):
        extra = {}
        if self.mcfg.get("temperature") is not None:
            extra["temperature"] = self.mcfg["temperature"]
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.mcfg.get("max_tokens", 1024),
            system=system,
            tools=[{"name": x["name"], "description": x["description"], "input_schema": x["schema"]} for x in tools],
            tool_choice={"type": "auto" if tool_mode == "auto" else "any"},
            messages=[{"role": "user", "content": query}],
            **extra,
        )
        calls = [{"name": b.name, "args": b.input} for b in resp.content if b.type == "tool_use"]
        texts = [b.text for b in resp.content if b.type == "text"]
        return {"calls": calls, "text": "\n".join(texts), "finish_reason": resp.stop_reason,
                "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
                "model_version": resp.model}

    @staticmethod
    def error_code(e):
        return getattr(e, "status_code", None)


class MockProvider:
    """Teszteléshez: véletlenszerűen választ egy tool-t, API-hívás nélkül."""
    name = "mock"

    def __init__(self, model, mcfg):
        self.rng = random.Random(mcfg.get("seed", 0))

    def call(self, system, tools, query, tool_mode):
        if tool_mode == "auto" and self.rng.random() < 0.1:
            return {"calls": [], "text": "(mock) válasz tool nélkül", "finish_reason": "MOCK", "usage": {}}
        t = self.rng.choice(tools)
        return {"calls": [{"name": t["name"], "args": {"query": query}}], "text": "",
                "finish_reason": "MOCK", "usage": {}}

    @staticmethod
    def error_code(e):
        return None


PROVIDERS = {"gemini": GeminiProvider, "anthropic": AnthropicProvider, "mock": MockProvider}
RETRYABLE = {429, 500, 502, 503, 504, 529}


# ---------------------------------------------------------------------------
# Futtatás
# ---------------------------------------------------------------------------

def plan_runs(cfg, servers, variants, queries, model_name):
    runs = []
    for cond in cfg["conditions"]:
        blocks = build_blocks(cfg, servers, variants, cond)
        for offset in rotation_offsets(len(blocks), cfg.get("rotations", "all")):
            for q in queries:
                for rep in range(cfg.get("repeats", 1)):
                    key = f"{model_name}|{cond['id']}|{q['id']}|rot{offset}|rep{rep}"
                    runs.append({"key": key, "condition": cond, "blocks": blocks,
                                 "offset": offset, "query": q, "repeat": rep})
    return runs


def estimate_tokens(cfg, run):
    _, tools, _ = flatten(run["blocks"], run["offset"], cfg["tool_name_format"], cfg.get("strip_schema_keys", []))
    chars = len(json.dumps(tools, ensure_ascii=False)) + len(cfg["system_prompt"]) + len(run["query"]["text"])
    return chars // 4


def write_manifest(cfg, cfg_path, servers, variants, out_path):
    manifest_path = out_path.with_suffix(".manifest.json")
    if manifest_path.exists():
        return
    manifest = {
        "created": now_iso(),
        "config_file": str(cfg_path),
        "config": cfg,
        "server_snapshots": {k: {"version": v["version"], "file": v["file"]} for k, v in servers.items()},
        "own_tool": None if variants is None else {
            "tool_name": variants["tool_name"], "server_name": variants["server_name"],
            "description_variants": variants["description_variants"],
            "param_sets": variants["param_sets"]},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--dry-run", action="store_true", help="csak a tervet és a token-becslést írja ki")
    ap.add_argument("--limit", type=int, default=None, help="legfeljebb ennyi hívás ebben a futásban")
    ap.add_argument("--conditions", default=None,
                    help="csak ezeket a feltételeket futtatja, vesszővel elválasztva (pl. search_only)")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    base = cfg_path.parent
    cfg = load_json(cfg_path)
    cfg.setdefault("tool_name_format", "mcp__{server}__{tool}")
    if args.conditions:
        wanted = [c.strip() for c in args.conditions.split(",") if c.strip()]
        known = [c["id"] for c in cfg["conditions"]]
        unknown = [c for c in wanted if c not in known]
        if unknown:
            raise SystemExit(f"Ismeretlen feltétel: {unknown}. Elérhetők: {known}")
        cfg["conditions"] = [c for c in cfg["conditions"] if c["id"] in wanted]

    servers = load_servers(cfg, base)
    # A saját tool opcionális: ha nincs 'own_tool_file', csak a versenytársakkal fut.
    variants = load_json(base / cfg["own_tool_file"]) if cfg.get("own_tool_file") else None
    queries = load_jsonl(base / cfg["queries"])
    mcfg = cfg["model"]
    runs = plan_runs(cfg, servers, variants, queries, mcfg["name"])

    out_path = base / cfg["output"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {r["key"] for r in load_jsonl(out_path) if r.get("status") == "ok"}
    todo = [r for r in runs if r["key"] not in done]

    # Véletlen sorrend: az időben változó hatások (szerverterhelés, modellfrissítés)
    # így nem egy-egy feltételre esnek. A seed miatt a sorrend reprodukálható.
    random.Random(cfg.get("seed", 0)).shuffle(todo)

    print(f"Tervezett mérések: {len(runs)}  |  kész: {len(done)}  |  hátravan: {len(todo)}")
    per_cond = {}
    for r in runs:
        c = per_cond.setdefault(r["condition"]["id"], {"runs": 0, "tokens": 0, "n_tools": 0})
        c["runs"] += 1
        c["tokens"] += estimate_tokens(cfg, r)
        c["n_tools"] = sum(len(t) for _, t in r["blocks"])
    for cid, c in per_cond.items():
        print(f"  {cid:<24}{c['runs']:>6} mérés  {c['n_tools']:>3} tool  ~{c['tokens'] // max(c['runs'], 1):>6} token/hívás")
    total = sum(estimate_tokens(cfg, r) for r in todo)
    print(f"Becsült input token a hátralévő mérésekre: ~{total:,} (karakter/4 alapon, tájékoztató jellegű)")
    rl = cfg.get("rate_limit", {})
    rpm = rl.get("rpm", 60)
    print(f"Becsült időtartam {rpm} kérés/perc mellett: ~{len(todo) / rpm:.0f} perc")
    if args.dry_run:
        return

    write_manifest(cfg, cfg_path, servers, variants, out_path)
    provider = PROVIDERS[mcfg["provider"]](mcfg["name"], mcfg)
    min_interval = 60.0 / rpm
    max_retries = rl.get("max_retries", 5)
    backoff_base = rl.get("backoff_base_s", 10)
    backoff_max = rl.get("backoff_max_s", 300)
    max_consecutive_errors = rl.get("max_consecutive_errors", 5)
    tool_mode = cfg.get("tool_mode", "auto")
    strip = cfg.get("strip_schema_keys", [])
    jitter = random.Random()

    last_call = 0.0
    consecutive_errors = 0
    n_done = 0
    with out_path.open("a", encoding="utf-8") as out:
        for run in todo:
            if args.limit is not None and n_done >= args.limit:
                break
            rotated, tools, name_map = flatten(run["blocks"], run["offset"], cfg["tool_name_format"], strip)
            own_server = variants["server_name"] if (variants and run["condition"].get("own")) else None
            block_order = [s for s, _ in rotated]

            result, error, error_code, latency = None, None, None, None
            for attempt in range(max_retries + 1):
                wait = min_interval - (time.time() - last_call)
                if wait > 0:
                    time.sleep(wait)
                last_call = time.time()
                t0 = time.time()
                try:
                    result = provider.call(cfg["system_prompt"], tools, run["query"]["text"], tool_mode)
                    latency = round(time.time() - t0, 2)
                    error = None
                    break
                except Exception as e:  # noqa: BLE001 - minden hibát naplózunk
                    error_code = provider.error_code(e)
                    error = f"{type(e).__name__}: {str(e)[:500]}"
                    if error_code in RETRYABLE and attempt < max_retries:
                        delay = min(backoff_base * 2 ** attempt, backoff_max) + jitter.uniform(0, 3)
                        print(f"  [{error_code}] újrapróbálás {delay:.0f} mp múlva ({attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        continue
                    break

            calls = result["calls"] if result else []
            first = calls[0]["name"] if calls else None
            first_server = name_map.get(first, (None, None))[0] if first else None
            rec = {
                "key": run["key"],
                "status": "ok" if error is None else "error",
                "timestamp": now_iso(),
                "provider": mcfg["provider"],
                "model": mcfg["name"],
                "model_version": (result or {}).get("model_version"),
                "temperature": mcfg.get("temperature"),
                "tool_mode": tool_mode,
                "condition": run["condition"]["id"],
                "environment": run["condition"]["environment"],
                "own_description": (run["condition"].get("own") or {}).get("description"),
                "own_params": (run["condition"].get("own") or {}).get("params"),
                "query_id": run["query"]["id"],
                "category": run["query"].get("category"),
                "query": run["query"]["text"],
                "rotation": run["offset"],
                "repeat": run["repeat"],
                "block_order": block_order,
                "own_block_position": block_order.index(own_server) if own_server else None,
                "tool_order": [t["name"] for t in tools],
                "n_tools": len(tools),
                "calls": calls,
                "n_calls": len(calls),
                "first_call": first,
                "first_call_server": first_server,
                "selected_own": (first_server == own_server) if (own_server and first) else (False if own_server else None),
                "text": (result or {}).get("text", "")[:2000],
                "finish_reason": (result or {}).get("finish_reason"),
                "usage": (result or {}).get("usage"),
                "latency_s": latency,
                "error": error,
                "error_code": error_code,
            }
            out.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            out.flush()
            n_done += 1

            if error is None:
                consecutive_errors = 0
                print(f"[{n_done}/{len(todo)}] {run['condition']['id']:<20} {run['query']['id']:<8} rot{run['offset']} -> {first_server or '(nincs hívás)'}")
            else:
                consecutive_errors += 1
                print(f"[{n_done}/{len(todo)}] HIBA: {error}")
                if error_code == 429:
                    print("Tartósan 429-es hiba: valószínűleg elfogyott a keret. "
                          "Futtasd újra később; a kész mérések megmaradnak.")
                    sys.exit(2)
                if consecutive_errors >= max_consecutive_errors:
                    print(f"{consecutive_errors} egymást követő hiba, leállás. Futtasd újra később.")
                    sys.exit(3)

    print(f"Kész. Ebben a futásban {n_done} mérés. Eredmények: {out_path}")


if __name__ == "__main__":
    main()