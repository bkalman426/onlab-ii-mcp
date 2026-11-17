"""
A run_selection.py eredményeinek gyors összesítése.

Futtatás:
    python summarize.py results/pilot_gemini-3.5-flash.jsonl

Kiírja feltételenként:
  - hány sikeres mérés van, és hány hiba,
  - milyen arányban nem hívott tool-t a modell,
  - melyik szerver tool-ját hívta először (arányok),
  - a saját tool választási arányát a pozíciója és a kérdéskategória szerint.
"""

import json
import sys
from collections import Counter, defaultdict


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "   - "


def paired_vs_baseline(own_rows, cats, baseline_id="baseline"):
    """Párosított összevetés a baseline-nal.

    Egy pár = ugyanaz a modell, kérdés, rotáció és ismétlés; a két mérés csak a saját
    tool leírásában különbözik (a kevert alapsorrend miatt a tool-sorrend is azonos).
    Csak azok a párok számítanak, ahol a két mérés eltérő eredményt adott:
      b = a változatnál választotta a saját tool-t, a baseline-nál nem
      c = a baseline-nál választotta, a változatnál nem
    Nullhipotézis: b és c egyformán valószínű (McNemar-próba, egzakt binomiális változat).
    """
    try:
        from scipy.stats import binomtest
    except ImportError:
        binomtest = None

    def key(r):
        return (r["model"], r["query_id"], r["rotation"], r["repeat"])

    base = {key(r): r for r in own_rows if r["condition"] == baseline_id}
    if not base:
        return
    conds = sorted({r["condition"] for r in own_rows if r["condition"] != baseline_id})
    if not conds:
        return

    def compare(pairs):
        b = sum(1 for v, s in pairs if v and not s)
        c = sum(1 for v, s in pairs if s and not v)
        n = len(pairs)
        delta = 100 * (b - c) / n if n else 0.0
        p = binomtest(b, b + c, 0.5).pvalue if (binomtest and b + c) else None
        return n, b, c, delta, p

    print(f"\nPárosított összevetés a '{baseline_id}' feltétellel "
          "(ugyanaz a kérdés és pozíció, csak a leírás más)")
    print(f"{'feltétel':<22}{'párok':>6}{'változat':>10}{'baseline':>10}{'különbség':>11}"
          f"{'+':>5}{'-':>5}{'p':>10}")
    for cond in conds:
        pairs = [(r["selected_own"], base[key(r)]["selected_own"])
                 for r in own_rows if r["condition"] == cond and key(r) in base]
        if not pairs:
            continue
        n, b, c, delta, p = compare(pairs)
        rate_v = sum(v for v, _ in pairs) / n
        rate_b = sum(s for _, s in pairs) / n
        p_txt = f"{p:.3g}" if p is not None else "-"
        print(f"{cond:<22}{n:>6}{100 * rate_v:>9.1f}%{100 * rate_b:>9.1f}%{delta:>+9.1f} pp"
              f"{b:>5}{c:>5}{p_txt:>10}")
    if binomtest is None:
        print("  (p-értékhez: pip install scipy)")
    print("  +: csak a változatnál választotta a saját tool-t, -: csak a baseline-nál")

    print("\nPárosított különbség kérdéskategóriánként (százalékpont; * = p < 0,05)")
    print(f"{'feltétel':<22}" + "".join(f"{c:>11}" for c in cats))
    for cond in conds:
        line = f"{cond:<22}"
        for cat in cats:
            pairs = [(r["selected_own"], base[key(r)]["selected_own"])
                     for r in own_rows if r["condition"] == cond and r["category"] == cat and key(r) in base]
            if not pairs:
                line += f"{'-':>11}"
                continue
            n, b, c, delta, p = compare(pairs)
            star = "*" if (p is not None and p < 0.05) else " "
            line += f"{delta:>+9.1f}{star} "
        print(line)


def ablation_pairs(rows, cond):
    """Feature ablation: a kitakart változat (ABL__<szülő>__<feature>) párjai a szülővel.
    Visszaad: [(szülő választotta, kitakart választotta, kategória)], ugyanazon kérdés/sorrend/ismétlés."""
    parent = cond.split("__")[1]

    def key(r):
        return (r["model"], r["query_id"], r["rotation"], r["repeat"])
    par = {key(r): r["selected_own"] for r in rows if r["condition"] == parent}
    return [(par[key(r)], r["selected_own"], r["category"]) for r in rows
            if r["condition"] == cond and key(r) in par]


def paired_ablation(own_rows, cats):
    """Az egyes feature-ök hozzájárulása: szülő − kitakart (párosítva).
    Pozitív érték: a rész növeli a saját tool választását (nélküle ritkábban választja)."""
    conds = sorted({r["condition"] for r in own_rows if r["condition"].startswith("ABL__")})
    if not conds:
        return
    try:
        from scipy.stats import binomtest
    except ImportError:
        binomtest = None

    def stats(pairs):
        n = len(pairs)
        b = sum(1 for p, a, *_ in pairs if p and not a)   # csak a szülőnél választotta
        c = sum(1 for p, a, *_ in pairs if a and not p)   # csak a kitakartnál
        d = (b - c) / n if n else 0.0
        p = binomtest(b, b + c, 0.5).pvalue if (binomtest and b + c) else None
        return n, b, c, d, p

    print("\nFeature ablation: az egyes részek hozzájárulása (szülő − kitakart, párosítva)")
    print(f"{'szülő':<18}{'kitakart rész':<16}{'párok':>6}{'szülő':>8}{'kitakart':>10}{'hozzájárulás':>14}"
          f"{'+':>5}{'-':>5}{'p':>10}")
    for cond in conds:
        _, parent, feat = cond.split("__")
        pairs = ablation_pairs(own_rows, cond)
        if not pairs:
            continue
        n, b, c, d, p = stats(pairs)
        rp = sum(x[0] for x in pairs) / n
        ra = sum(x[1] for x in pairs) / n
        p_txt = f"{p:.3g}" if p is not None else "-"
        print(f"{parent:<18}{feat:<16}{n:>6}{100 * rp:>7.1f}%{100 * ra:>9.1f}%{100 * d:>+11.1f} pp"
              f"{b:>5}{c:>5}{p_txt:>10}")
    print("  +: csak a teljes (szülő) változatnál választotta a saját tool-t, -: csak a kitakartnál")

    print("\nHozzájárulás kérdéskategóriánként (százalékpont; * = p < 0,05)")
    print(f"{'kitakart változat':<36}" + "".join(f"{c:>11}" for c in cats))
    for cond in conds:
        line = f"{cond[5:]:<36}"
        all_pairs = ablation_pairs(own_rows, cond)
        for cat in cats:
            pairs = [x for x in all_pairs if x[2] == cat]
            if not pairs:
                line += f"{'-':>11}"
                continue
            n, b, c, d, p = stats(pairs)
            star = "*" if (p is not None and p < 0.05) else " "
            line += f"{100 * d:>+9.1f}{star} "
        print(line)


def paired_specificity(own_rows, targets, cats, baseline_id="baseline"):
    """Specifikusság: a célzott kategóriában mért párosított hatás mínusz a nem-célzott
    kategóriák átlagos hatása. Nagy érték = 'sebészi' (szinte csak a célzottban emel);
    0 körül = általános emelő (mindenhol hasonlóan hat). Külön kiírja a célzó változat és
    a mindent állító t_all hatását is kategóriánként."""
    def key(r):
        return (r["model"], r["query_id"], r["rotation"], r["repeat"])
    base = {key(r): r["selected_own"] for r in own_rows if r["condition"] == baseline_id}
    if not base:
        return

    def delta(cond, cat):
        pairs = [(r["selected_own"], base[key(r)]) for r in own_rows
                 if r["condition"] == cond and r["category"] == cat and key(r) in base]
        if not pairs:
            return None
        b = sum(1 for v, s in pairs if v and not s)
        c = sum(1 for v, s in pairs if s and not v)
        return 100 * (b - c) / len(pairs)

    cond_target, cond_id = {}, {}
    for r in own_rows:
        cond_target.setdefault(r["condition"], targets.get(r["own_description"]))
        cond_id.setdefault(r["condition"], r["own_description"])

    single = [(c, t) for c, t in cond_target.items() if t in cats]  # a t_all ('all') kimarad
    if not single:
        return

    print("\nSpecifikusság: célzott hatás − az átlagos nem-célzott hatás (párosított, pp)")
    print(f"{'változat':<16}{'célzott kat.':<12}{'célzott Δ':>11}{'nem-célz. átlag':>17}{'specifikusság':>15}")
    for cond, tgt in sorted(single, key=lambda x: cond_id[x[0]]):
        dt = delta(cond, tgt)
        others = [o for o in (delta(cond, c) for c in cats if c != tgt) if o is not None]
        if dt is None or not others:
            continue
        mo = sum(others) / len(others)
        print(f"{cond_id[cond]:<16}{tgt:<12}{dt:>+9.1f}{mo:>+16.1f}{dt - mo:>+14.1f}")
    print("  Nagy specifikusság = sebészi (csak a célzottban emel); 0 körül = általános emelő.")

    broad = next((c for c, t in cond_target.items() if t == "all"), None)
    if broad:
        print("\nCélzott vs. széles (t_all) kérdéskategóriánként — párosított hatás a baseline-hoz (pp)")
        print(f"{'kategória':<12}{'célzó változat':>16}{'célzott Δ':>11}{'t_all Δ':>10}")
        for cat in cats:
            cands = [c for c, t in cond_target.items() if t == cat]
            cands.sort(key=lambda c: (not cond_id[c].startswith("t_"), c))
            if not cands:
                continue
            tc = cands[0]
            dt, da = delta(tc, cat), delta(broad, cat)
            dt_s = f"{dt:+.1f}" if dt is not None else "-"
            da_s = f"{da:+.1f}" if da is not None else "-"
            print(f"{cat:<12}{cond_id[tc]:>16}{dt_s:>11}{da_s:>10}")


def main(path, variants_path="variants.json"):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    ok = [r for r in rows if r["status"] == "ok"]
    errors = [r for r in rows if r["status"] != "ok"]
    # Ha egy mérés először hibás volt, majd újrafuttatva sikeres, csak a sikerest számoljuk.
    ok_keys = {r["key"] for r in ok}
    open_errors = {r["key"] for r in errors if r["key"] not in ok_keys}
    print(f"Sikeres mérések: {len(ok)}   Hibás (még nem pótolt): {len(open_errors)}")
    versions = Counter((r["model"], r.get("model_version")) for r in ok)
    print("Kért modell -> ténylegesen válaszoló verzió:")
    for (asked, served), n in versions.most_common():
        print(f"  {asked} -> {served or '(nincs rögzítve)'}: {n} mérés")
    print()

    by_cond = defaultdict(list)
    for r in ok:
        by_cond[(r["model"], r["condition"])].append(r)

    servers = sorted({r["first_call_server"] for r in ok if r["first_call_server"]})

    print("Első tool-hívás szerverenként (a 'nincs' = válasz tool nélkül)")
    header = f"{'modell':<18}{'feltétel':<20}{'n':>5}" + "".join(f"{s:>11}" for s in servers) + f"{'nincs':>9}{'több hívás':>12}"
    print(header)
    print("-" * len(header))
    for (model, cond), rs in sorted(by_cond.items()):
        n = len(rs)
        c = Counter(r["first_call_server"] for r in rs)
        multi = sum(1 for r in rs if r["n_calls"] > 1)
        print(f"{model:<18}{cond:<20}{n:>5}" + "".join(f"{pct(c[s], n):>11}" for s in servers)
              + f"{pct(c[None], n):>9}{pct(multi, n):>12}")

    # Statisztikai próba: egyenletes-e a választás a listán lévő szerverek között?
    # (Csak a tool-hívással záruló méréseket nézi; a tool nélküli válaszokat kihagyja.)
    try:
        from scipy.stats import chisquare
    except ImportError:
        chisquare = None
    print("\nEgyenletes választástól való eltérés (khi-négyzet próba, csak a tool-hívásos mérések)")
    for (model, cond), rs in sorted(by_cond.items()):
        offered = sorted({s for r in rs for s in r["block_order"]})
        called = [r["first_call_server"] for r in rs if r["first_call_server"]]
        if len(offered) < 2 or not called:
            continue
        obs = [sum(1 for s in called if s == srv) for srv in offered]
        exp = len(called) / len(offered)
        stat = sum((o - exp) ** 2 / exp for o in obs)
        p = chisquare(obs).pvalue if chisquare else None
        detail = ", ".join(f"{srv}={o}" for srv, o in zip(offered, obs))
        p_txt = f"p = {p:.2g}" if p is not None else "p: telepítsd a scipy-t (pip install scipy)"
        print(f"  {cond}: khi² = {stat:.1f}, szabadságfok = {len(offered) - 1}, {p_txt}   [{detail}, várt: {exp:.1f}]")

    # Minden szerver választási aránya aszerint, hogy hányadik blokkban szerepelt.
    print("\nSzerverek választási aránya a saját pozíciójuk szerint (0 = a lista eleje)")
    for (model, cond), rs in sorted(by_cond.items()):
        offered = sorted({s for r in rs for s in r["block_order"]})
        n_pos = max(len(r["block_order"]) for r in rs)
        print(f"  [{cond}]")
        print(f"  {'szerver':<14}" + "".join(f"{'poz ' + str(p):>9}" for p in range(n_pos)))
        for srv in offered:
            line = f"  {srv:<14}"
            for p in range(n_pos):
                at = [r for r in rs if p < len(r["block_order"]) and r["block_order"][p] == srv]
                line += f"{pct(sum(r['first_call_server'] == srv for r in at), len(at)):>9}"
            print(line)
        line = f"  {'(bármelyik)':<14}"
        for p in range(n_pos):
            line += f"{pct(sum(1 for r in rs if r['first_call_server'] and p < len(r['block_order']) and r['block_order'][p] == r['first_call_server']), len(rs)):>9}"
        print(line + "   <- az első hívás ennyiszer esett az adott pozícióra")

    # Kérdéskategóriánként: melyik szervert választja, és mikor nem keres.
    print("\nElső választás kérdéskategóriánként")
    for (model, cond), rs in sorted(by_cond.items()):
        offered = sorted({s for r in rs for s in r["block_order"]})
        cats = sorted({r["category"] for r in rs})
        print(f"  [{cond}]")
        print(f"  {'kategória':<12}{'n':>5}" + "".join(f"{s:>11}" for s in offered) + f"{'nincs':>9}")
        for cat in cats:
            cr = [r for r in rs if r["category"] == cat]
            c = Counter(r["first_call_server"] for r in cr)
            print(f"  {cat:<12}{len(cr):>5}" + "".join(f"{pct(c[s], len(cr)):>11}" for s in offered)
                  + f"{pct(c[None], len(cr)):>9}")

    # Mely kérdéseknél válaszolt tool nélkül?
    no_call = Counter(r["query_id"] for r in ok if not r["first_call"])
    if no_call:
        totals = Counter(r["query_id"] for r in ok)
        print("\nKérdések, amelyekre (legalább egyszer) tool nélkül válaszolt:")
        for qid, n in sorted(no_call.items(), key=lambda x: (-x[1], x[0])):
            q = next(r["query"] for r in ok if r["query_id"] == qid)
            print(f"  {qid:<6}{n}/{totals[qid]}  {q[:90]}")

    own_rows = [r for r in ok if r["own_block_position"] is not None]
    if own_rows:
        print("\nSaját tool választási aránya a pozíciója szerint (0 = első szerverblokk)")
        by_pos = defaultdict(list)
        for r in own_rows:
            by_pos[(r["condition"], r["own_block_position"])].append(r)
        conds = sorted({k[0] for k in by_pos})
        positions = sorted({k[1] for k in by_pos})
        print(f"{'feltétel':<20}" + "".join(f"{'poz ' + str(p):>10}" for p in positions))
        for cond in conds:
            line = f"{cond:<20}"
            for p in positions:
                rs = by_pos.get((cond, p), [])
                line += f"{pct(sum(r['selected_own'] for r in rs), len(rs)):>10}"
            print(line)

        print("\nSaját tool választási aránya kérdéskategóriánként")
        by_cat = defaultdict(list)
        for r in own_rows:
            by_cat[(r["condition"], r["category"])].append(r)
        cats = sorted({k[1] for k in by_cat})
        print(f"{'feltétel':<20}" + "".join(f"{c:>11}" for c in cats))
        for cond in conds:
            line = f"{cond:<20}"
            for cat in cats:
                rs = by_cat.get((cond, cat), [])
                line += f"{pct(sum(r['selected_own'] for r in rs), len(rs)):>11}"
            print(line)

        targets = {}
        try:
            from pathlib import Path as _Path
            if variants_path and _Path(variants_path).exists():
                vj = json.loads(_Path(variants_path).read_text(encoding="utf-8"))
                targets = {x["id"]: x.get("target_category")
                           for x in vj.get("description_variants", []) if x.get("family") != "ABL"}
        except Exception:
            targets = {}

        paired_vs_baseline(own_rows, cats)
        if targets:
            paired_specificity(own_rows, targets, cats)
        paired_ablation(own_rows, cats)

    tokens =[r["usage"].get("input") for r in ok if r.get("usage") and r["usage"].get("input")]
    if tokens:
        print(f"\nTényleges input token/hívás (átlag): {sum(tokens) / len(tokens):,.0f}   összesen: {sum(tokens):,}")


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="A run_selection.py eredményeinek összesítése.")
    ap.add_argument("results", help="eredményfájl (.jsonl)")
    ap.add_argument("--plots", nargs="?", const="", default=None,
                    help="ábrák mentése PNG-be; opcionálisan a mappa "
                         "(alapértelmezés: results/plots/<eredményfájl neve>/)")
    ap.add_argument("--variants", default="variants.json",
                    help="a saját tool változatai (a célzott kategóriák kiemeléséhez); alapértelmezés: variants.json")
    ap.add_argument("--label", default=None,
                    help="az eredményhalmaz neve az összevető ábrákon (alapértelmezés: a fájl neve)")
    ap.add_argument("--compare", default=None,
                    help="második eredményfájl az ábrákhoz (pl. márkanevekkel futtatott mérés): az első választás "
                         "ábrája mindkettőt mutatja, és készül egy összevető ábra a saját tool arányáról")
    ap.add_argument("--compare-label", default=None,
                    help="a második eredményhalmaz neve (alapértelmezés: a fájl neve)")
    ap.add_argument("--skip", default="",
                    help="kihagyandó ábrák vesszővel elválasztva: pozicio, ablacio "
                         "(az 'ablacio' az ablation-feltételeket az összes ábráról kiszűri)")
    args = ap.parse_args()

    main(args.results, args.variants)

    if args.plots is not None:
        try:
            import plots
        except ImportError as e:
            raise SystemExit(f"Az ábrákhoz telepítsd a matplotlibot: pip install matplotlib  ({e})")

        def load_ok(path):
            # Kulcsonként az utolsó sikeres mérés (az újrafuttatott mérések ne számítsanak kétszer).
            rows = {}
            for line in open(path, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    if r["status"] == "ok":
                        rows[r["key"]] = r
            return list(rows.values())

        res = Path(args.results)
        out_dir = Path(args.plots) if args.plots else res.parent / "plots" / res.stem
        compare = None
        if args.compare:
            cmp_path = Path(args.compare)
            compare = (args.compare_label or cmp_path.stem, load_ok(cmp_path))
        skip = {s.strip() for s in args.skip.split(",") if s.strip()}
        made = plots.make_all(load_ok(res), out_dir, args.variants, label=args.label or res.stem,
                              compare=compare, skip=skip)
        print(f"\nÁbrák ({out_dir}):")
        for p in made:
            print(f"  {p.name}")