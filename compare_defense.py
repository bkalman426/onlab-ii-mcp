"""Védekezés hatása: párosított összevetés egy védekezés nélküli és egy védekezéses futás között.

A két futás mérési kulcsai egyeznek (ugyanaz a feltétel, kérdés, sorrend, álnév), így
minden mérés párosítható. Kiírja feltételenként (összesítve és a célzott kategóriában):
  - a saját tool arányát védekezés nélkül és védekezéssel,
  - a támadás hatását a saját baseline-hoz képest mindkét futásban (pp),
  - McNemar-próbát (egzakt binomiális) a védekezés nélküli vs. védekezéses párokra.

Futtatás:
  python compare_defense.py results/anon_gemini-3.6-flash.jsonl results/para_gemini-3.6-flash.jsonl
"""
import argparse
import json
from collections import defaultdict

TARGET = {"B_t_fresh": "fresh", "B_t_error": "error", "B_t_library": "library", "B_t_academic": "academic"}


def load(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("status") == "ok":
                rows[r["key"]] = r
    return rows


def mcnemar(b, c):
    if b + c == 0:
        return float("nan")
    try:
        from scipy.stats import binomtest
        return binomtest(b, b + c, 0.5).pvalue
    except ImportError:
        return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="védekezés nélküli futás")
    ap.add_argument("defense", help="védekezéses futás")
    ap.add_argument("--label", default="parafrázis")
    args = ap.parse_args()
    A, D = load(args.base), load(args.defense)
    common = [k for k in D if k in A]
    conds = sorted({D[k]["condition"] for k in common}, key=lambda c: (c != "baseline", c))

    def rate(rows, keys):
        return sum(1 for k in keys if rows[k].get("selected_own")) / len(keys) if keys else float("nan")

    def subset(cond, cat=None):
        return [k for k in common if D[k]["condition"] == cond and (cat is None or D[k]["category"] == cat)]

    print(f"Párosított mérések: {len(common)}  (védekezés nélkül: {args.base}, {args.label}: {args.defense})\n")
    print(f"{'feltétel':<18}{'szűrés':<10}{'n':>5}{'nélküle':>9}{args.label:>12}{'hatás nélk.':>13}{'hatás véd.':>12}{'b/c':>9}{'p':>8}")
    for cond in conds:
        for cat in [None] + ([TARGET[cond]] if cond in TARGET else []):
            keys = subset(cond, cat)
            bkeys = subset("baseline", cat)
            ra, rd = rate(A, keys), rate(D, keys)
            ea = ra - rate(A, bkeys) if cond != "baseline" else float("nan")
            ed = rd - rate(D, bkeys) if cond != "baseline" else float("nan")
            b = sum(1 for k in keys if D[k].get("selected_own") and not A[k].get("selected_own"))
            c = sum(1 for k in keys if A[k].get("selected_own") and not D[k].get("selected_own"))
            p = mcnemar(b, c)
            f = lambda x: f"{x:+.0%}".replace("%", " pp") if x == x else "-"
            print(f"{cond:<18}{(cat or 'mind'):<10}{len(keys):>5}{ra:>9.0%}{rd:>12.0%}{f(ea):>13}{f(ed):>12}{f'{b}/{c}':>9}{p:>8.3f}")

    # versenytársak megoszlása baseline-ban (a parafrázis a versenytársakat is átírta)
    print("\nElső hívás megoszlása a baseline feltételben:")
    for name, rows in (("nélküle", A), (args.label, D)):
        cnt = defaultdict(int)
        keys = subset("baseline")
        for k in keys:
            cnt[rows[k].get("first_call_server") or "(nincs)"] += 1
        print(f"  {name:<12}" + "  ".join(f"{s}: {n / len(keys):.0%}" for s, n in sorted(cnt.items())))


if __name__ == "__main__":
    main()
