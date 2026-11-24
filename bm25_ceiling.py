"""Kalibrált plafon és küszöbsöprés a host-oldali kiválasztáshoz (API-hívás nélkül).

Szabály (kérdésenként):
  1. minden tool kap egy pontszámot (BM25, vagy az LLM választási gyakorisága az 5 sorrendben);
  2. plafon: T = k * referencia; a T feletti pontszámok T-re vágódnak, vagyis mindenki,
     aki eléri a plafont, egyformán jónak számít;
  3. a host egyenletesen sorsol a plafont elérők közül; ha senki nem érte el, a legjobb nyer.

  A skála két vége: k = inf -> senki nem éri el -> argmax (a mostani helyzet);
                    k -> 0   -> mindenki eléri -> egyenletes sorsolás (BiasBusters).

Referencia ("anchor"):
  - trim:   a kérdés pontszámainak átlaga a legnagyobb nélkül (trimmed mean). Egyetlen kiugró
    tool nem mozdítja, ezért "kalibrált": a plafon ahhoz igazodik, amit a többiek elérnek.
    (Ez a fő változat. A medián BM25-nél nem jó referencia: rövid kérdéseknél a pontszámok
    többsége 0, így a medián is 0, és a plafon semmit nem vág.)
  - max:    a kérdés legjobb pontszáma (a korábbi relatív küszöb, T = max/k alakban).
    Egy kiugró tool itt magával húzza a küszöböt, és egyedül marad felette.

Mérőszámok k-nként:
  - a saját tool aránya változatonként (összesen, és a célzott változatoknál a célzott kategóriában);
  - ár: a baseline feltételben milyen arányban kapja a kérdést a pontszám szerinti legjobb tool
    (argmax-egyezés), és átlagosan hány tool éri el a plafont.

Futtatás:
  python bm25_ceiling.py                                 # BM25, eredeti leírások
  python bm25_ceiling.py --configs experiment_para.json  # BM25, parafrazált leírások
  python bm25_ceiling.py --source llm                    # LLM-gyakoriság (anon eredmények)
  ... --csv results/ceiling_bm25.csv                     # eredmény mentése (az ábrához)
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from bm25_baseline import BM25, load_jsonl, tokenize, tool_text

TARGET = {"B_t_fresh": "fresh", "B_t_error": "error", "B_t_library": "library", "B_t_academic": "academic"}
SHOW = ["baseline", "A_authoritative", "A_exaggerated", "B_t_fresh", "B_t_error", "B_t_library", "B_t_academic"]
K_TRIM = [0.5, 1, 1.5, 2, 3, 4, 6, 8, math.inf]
K_MAX = [1, 1.25, 1.5, 2, 3, 4, 8, math.inf]
K_LLM = [0.2, 0.4, 0.6, 0.8, 1.0, math.inf]  # LLM-nél abszolút küszöb a gyakoriságra (k * 1)


def select_probs(scores, k, anchor):
    """Választási valószínűségek a plafon-szabály szerint."""
    n = len(scores)
    m = max(scores)
    if m <= 0:
        return [1 / n] * n, n
    if anchor == "trim":
        rest = sorted(scores)[:-1]
        T = k * (sum(rest) / len(rest))
    elif anchor == "max":
        T = m / k  # k = 1 -> csak a legjobb; k -> inf -> mindenki (pozitív pontú)
    else:  # "abs"
        T = k
    elig = [i for i, s in enumerate(scores) if s >= T and s > 0]
    if not elig or (anchor != "max" and math.isinf(k)):
        elig = [i for i, s in enumerate(scores) if s == m]
    p = [0.0] * n
    for i in elig:
        p[i] = 1 / len(elig)
    return p, len(elig)


def bm25_scores(configs, fields):
    """{feltétel: [(kérdés, [pontszámok], saját index)]} a konfigurációk feltételeire."""
    conds, cfg0 = {}, None
    for c in configs:
        cfg = json.loads(Path(c).read_text(encoding="utf-8"))
        cfg0 = cfg0 or cfg
        for cond in cfg["conditions"]:
            conds.setdefault(cond["id"], cond["own"])
    variants = json.loads(Path(cfg0["own_tool_file"]).read_text(encoding="utf-8"))
    vdesc = {v["id"]: v["description"] for v in variants["description_variants"]}
    queries = load_jsonl(cfg0["queries"])
    comp = []
    for srv, f in cfg0["servers"].items():
        for t in json.loads(Path(f).read_text(encoding="utf-8"))["tools"]:
            if t["name"] in cfg0["environments"]["search_only"][srv]:
                comp.append(tokenize(tool_text(t, fields)))
    out = {}
    for cid, own in conds.items():
        if own["description"] not in vdesc:
            continue
        t = {"name": own.get("tool_name", variants["tool_name"]), "description": vdesc[own["description"]],
             "inputSchema": variants["param_sets"][own["params"]]}
        docs = comp + [tokenize(tool_text(t, fields))]
        bm = BM25(docs)
        out[cid] = [(q, bm.scores(tokenize(q["text"])), len(docs) - 1) for q in queries]
    return out


def llm_scores(results_path):
    """Kérdésenként a szerverek választási gyakorisága az összes sorrendben (0..1)."""
    cnt = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    meta = {}
    for r in load_jsonl(results_path):
        if r.get("status") != "ok":
            continue
        cnt[r["condition"]][r["query_id"]][r.get("first_call_server") or "-"] += 1
        meta[r["query_id"]] = r["category"]
    servers = ["brave", "exa", "firecrawl", "tavily", "veld"]
    out = {}
    for cid, per_q in cnt.items():
        rows = []
        for qid, c in per_q.items():
            tot = sum(c.values())
            rows.append(({"id": qid, "category": meta[qid]}, [c[s] / tot for s in servers], servers.index("veld")))
        out[cid] = rows
    return out


def sweep(data, ks, anchor):
    res = []
    for k in ks:
        row = {"k": k}
        for cid in SHOW:
            if cid not in data:
                continue
            own_all, own_cat, agree, size = [], [], [], []
            for q, sc, oi in data[cid]:
                p, n_el = select_probs(sc, k, anchor)
                own_all.append(p[oi])
                if TARGET.get(cid) == q["category"]:
                    own_cat.append(p[oi])
                m = max(sc)
                agree.append(sum(p[i] for i, s in enumerate(sc) if s == m) if m > 0 else 1.0)
                size.append(n_el)
            row[cid] = sum(own_all) / len(own_all)
            if own_cat:
                row[cid + "@cat"] = sum(own_cat) / len(own_cat)
            if cid == "baseline":
                row["cost_agree"] = sum(agree) / len(agree)
                row["cost_size"] = sum(size) / len(size)
        res.append(row)
    return res


def print_table(res, title):
    cols = [c for c in SHOW if c in res[0]]
    short = {"baseline": "base", "A_authoritative": "tekint", "A_exaggerated": "túlzás",
             "B_t_fresh": "fresh", "B_t_error": "error", "B_t_library": "libr", "B_t_academic": "acad"}
    print(f"\n{title}")
    hdr = f"{'k':>6}" + "".join(f"{short[c]:>8}" for c in cols) + "   | célzott kategóriában:" + \
        "".join(f"{short[c]:>7}" for c in cols if c + "@cat" in res[0]) + "   | ár: argmax-egyezés, plafont elérők"
    print(hdr)
    for r in res:
        k = "inf" if math.isinf(r["k"]) else f"{r['k']:g}"
        line = f"{k:>6}" + "".join(f"{r[c]:>8.0%}" for c in cols) + "   |" + " " * 22 + \
            "".join(f"{r[c + '@cat']:>7.0%}" for c in cols if c + "@cat" in r)
        line += f"   | {r.get('cost_agree', float('nan')):>5.0%}  {r.get('cost_size', float('nan')):>4.1f}"
        print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["bm25", "llm"], default="bm25")
    ap.add_argument("--configs", default="experiment_anon_A.json,experiment_anon_B.json")
    ap.add_argument("--results", default="results/anon_gemini-3.6-flash.jsonl")
    ap.add_argument("--fields", default="description,params")
    ap.add_argument("--csv", default=None, help="az összes söprés mentése CSV-be")
    args = ap.parse_args()

    if args.source == "bm25":
        data = bm25_scores(args.configs.split(","), set(args.fields.split(",")))
        runs = [("trim", K_TRIM, "Kalibrált plafon: T = k × a többiek átlaga (BM25)"),
                ("max", K_MAX, "Összevetésül relatív küszöb: T = max / k (BM25)")]
    else:
        data = llm_scores(args.results)
        runs = [("abs", K_LLM, f"Plafon az LLM választási gyakoriságán: T = k ({args.results})")]

    rows_out = []
    for anchor, ks, title in runs:
        res = sweep(data, ks, anchor)
        print_table(res, title)
        for r in res:
            rows_out.append({"source": args.source, "configs": args.configs, "anchor": anchor, **r})
    print("\n  A k = inf sor a mostani helyzet (argmax). Az ár a baseline feltételben: milyen arányban kapja a kérdést"
          "\n  a pontszám szerinti legjobb tool, és átlagosan hány tool éri el a plafont.")

    if args.csv:
        keys = sorted({k for r in rows_out for k in r}, key=lambda x: (x not in ("source", "configs", "anchor", "k"), x))
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in rows_out:
                w.writerow({**r, "k": "inf" if math.isinf(r["k"]) else r["k"]})
        print(f"\nMentve: {args.csv}")


if __name__ == "__main__":
    main()
