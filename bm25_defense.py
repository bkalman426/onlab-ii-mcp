"""BM25 mint LLM nélküli host-oldali kiválasztás (védekezés) az anon kar változatain.

Mérés nélkül, a meglévő adatokból számol:
  1. BM25-host: kérdésenként a saját tool választási aránya
       - argmax: a legnagyobb pontszámú tool nyer
       - küszöb+sorsolás: a max*tau feletti tool-ok közül egyenletesen sorsol
     összevetve az LLM (Gemini) saját-arányával ugyanazon a feltételen.
  2. Lift: mennyivel nő a saját tool BM25-pontszáma a baseline leíráshoz képest
     (host-oldali "lift audit": a szöveg mennyit "dolgozik" a funkcióhoz képest).
  3. Kilógás-szűrő (plafon) első közelítése az LLM-adatokon: a versenytárs-karból
     kategóriánként kalibrált küszöb (legitim tool max aránya + margó); mely
     változatokat fogná meg, és hány legitim tool–kategória párt jelölne tévesen.

Használat:
  python bm25_defense.py [--tau 0.8] [--margin 0.10] [--fields description,params]
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from bm25_baseline import BM25, tokenize, tool_text, load_jsonl

CATS = ["fresh", "error", "library", "academic"]


def pct(x):
    return f"{x:>5.0%}" if x == x else "    -"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="experiment_anon_A.json,experiment_anon_B.json,experiment_anon_ABL.json")
    ap.add_argument("--results", default="results/anon_gemini-3.6-flash.jsonl")
    ap.add_argument("--calib", default="results/competitors_gemini-3.6-flash.jsonl",
                    help="a kilógás-küszöb kalibrálása (versenytárs-kar, search_only); 'anon' = az anon kar baseline feltételének legitim tool-jai")
    ap.add_argument("--fields", default="description,params")
    ap.add_argument("--tau", type=float, default=0.8, help="küszöb+sorsolás: max*tau feletti tool-ok")
    ap.add_argument("--margin", type=float, default=0.10, help="kilógás-szűrő: küszöb = legitim max + margó")
    args = ap.parse_args()
    fields = set(args.fields.split(","))

    # --- feltételek összegyűjtése a konfigokból ---
    conds, cfg0 = {}, None
    for c in args.configs.split(","):
        if not Path(c).exists():
            continue
        cfg = json.loads(Path(c).read_text(encoding="utf-8"))
        cfg0 = cfg0 or cfg
        for cond in cfg["conditions"]:
            conds.setdefault(cond["id"], cond["own"])
    variants = json.loads(Path(cfg0["own_tool_file"]).read_text(encoding="utf-8"))
    vdesc = {v["id"]: v["description"] for v in variants["description_variants"]}
    queries = load_jsonl(cfg0["queries"])

    comp = []  # (server, tokens) a versenytársak keresőtool-jai
    for srv, f in cfg0["servers"].items():
        tools = json.loads(Path(f).read_text(encoding="utf-8"))["tools"]
        for t in tools:
            if t["name"] in cfg0["environments"]["search_only"][srv]:
                comp.append((srv, tokenize(tool_text(t, fields))))

    def own_tokens(own):
        t = {"name": own.get("tool_name", variants["tool_name"]), "description": vdesc[own["description"]],
             "inputSchema": variants["param_sets"][own["params"]]}
        return tokenize(tool_text(t, fields))

    # --- LLM saját-arányok ---
    llm = defaultdict(lambda: defaultdict(list))         # cond -> cat -> [0/1]
    llm_srv = defaultdict(lambda: defaultdict(Counter))  # cond -> cat -> server -> n
    for r in load_jsonl(args.results):
        if r.get("status") != "ok":
            continue
        llm[r["condition"]][r["category"]].append(1 if r.get("selected_own") else 0)
        llm_srv[r["condition"]][r["category"]][r.get("first_call_server") or "-"] += 1

    # --- 1–2. BM25-host ---
    base_scores = {}
    print(f"BM25-host (mezők: {args.fields}, tau={args.tau}); saját tool aránya, 'mind' + kategóriánként\n")
    hdr = f"{'feltétel':<36}{'LLM':>7}{'argmax':>8}{'küsz+s':>8}{'lift':>7}   " + " ".join(f"{c[:5]:>13}" for c in CATS)
    print(hdr)
    print(f"{'':<36}{'':>7}{'':>8}{'':>8}{'':>7}   " + " ".join(f"{'LLM/arg/küsz':>13}" for _ in CATS))
    for cid, own in conds.items():
        docs = [c[1] for c in comp] + [own_tokens(own)]
        bm = BM25(docs)
        oi = len(docs) - 1
        per_cat = defaultdict(lambda: [[], [], []])
        lifts = []
        for q in queries:
            sc = bm.scores(tokenize(q["text"]))
            m = max(sc)
            arg = 1.0 if m > 0 and sc[oi] == m and sc.count(m) == 1 else (1 / sc.count(m) if sc[oi] == m else 0.0)
            if m == 0:
                arg = 1 / len(sc)
            elig = [s for s in sc if s >= args.tau * m] if m > 0 else sc
            thr = (1 / len(elig)) if (m == 0 or sc[oi] >= args.tau * m) else 0.0
            per_cat[q["category"]][1].append(arg)
            per_cat[q["category"]][2].append(thr)
            if own["description"] == "baseline":
                base_scores[q["id"]] = sc[oi]
            elif q["id"] in base_scores:
                lifts.append(sc[oi] - base_scores[q["id"]])
        mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
        all_llm = [x for c in CATS for x in llm[cid][c]]
        all_arg = [x for c in CATS for x in per_cat[c][1]]
        all_thr = [x for c in CATS for x in per_cat[c][2]]
        cells = " ".join(f"{pct(mean(llm[cid][c]))}/{pct(mean(per_cat[c][1])).strip()}/{pct(mean(per_cat[c][2])).strip()}".rjust(13) for c in CATS)
        lift = f"{mean(lifts):>7.2f}" if lifts else f"{'0':>7}"
        print(f"{cid:<36}{pct(mean(all_llm)):>7}{pct(mean(all_arg)):>8}{pct(mean(all_thr)):>8}{lift}   {cells}")

    # --- 3. Kilógás-szűrő az LLM-adatokon ---
    calib = defaultdict(Counter)
    if args.calib == "anon":
        for c in CATS:
            calib[c] = Counter({s: n for s, n in llm_srv["baseline"][c].items() if s != "veld"})
    elif Path(args.calib).exists():
        for r in load_jsonl(args.calib):
            if r.get("status") == "ok" and r["condition"] == "search_only":
                calib[r["category"]][r.get("first_call_server") or "-"] += 1
    thr = {}
    for c in CATS:
        tot = sum(calib[c].values())
        legit = [n / tot for s, n in calib[c].items() if s != "-"] if tot else [0]
        thr[c] = max(legit) + args.margin
    print(f"\nKilógás-szűrő: küszöb kategóriánként = legitim tool max aránya ({args.calib}) + {args.margin:.0%}")
    print("  " + "  ".join(f"{c}: {thr[c]:.0%}" for c in CATS))
    print(f"\n{'feltétel':<36}" + "".join(f"{c[:8]:>10}" for c in CATS) + "   megfogva")
    fp = fp_n = 0
    for cid in conds:
        row, caught = "", []
        for c in CATS:
            xs = llm[cid][c]
            r = sum(xs) / len(xs) if xs else float("nan")
            flag = r == r and r > thr[c]
            if flag:
                caught.append(c)
            row += f"{pct(r)}{'*' if flag else ' '}".rjust(10)
            tot = sum(llm_srv[cid][c].values())
            for s, n in llm_srv[cid][c].items():
                if s in ("-", "veld"):
                    continue
                fp_n += 1
                fp += n / tot > thr[c]
        print(f"{cid:<36}{row}   {','.join(caught) or '-'}")
    print(f"\nTéves jelzés: legitim tool–kategória–feltétel hármasok {fp}/{fp_n} esetben lépik át a küszöböt")


if __name__ == "__main__":
    main()
