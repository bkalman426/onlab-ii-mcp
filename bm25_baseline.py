"""BM25 baseline a tool-választáshoz (LLM nélkül).

Minden lekérdezéshez BM25-tel rangsorolja a tool-okat a leírásuk alapján,
és a top-1 szerver eloszlását összeveti egy LLM-futás first_call_server értékeivel.

Használat:
  python bm25_baseline.py --experiment experiment_competitors.json \
      --queries queries_pilot_v2.jsonl --results results/competitors_gemini-3.6-flash.jsonl
"""
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

STOP = set("""a an the and or of to in on for with by is are be as at it this that from
your you can use when which what how do does i my any its into via if not than then""".split())


def tokenize(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # camelCase
    return [stem(t) for t in re.findall(r"[a-z0-9]+", text.lower().replace("_", " ")) if t not in STOP]


def stem(t):
    """Nagyon egyszerű többesszám-levágás (papers -> paper, libraries -> library)."""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avg = sum(self.lens) / max(len(docs), 1)
        self.k1, self.b = k1, b
        df = Counter(t for d in self.docs for t in d)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query):
        out = []
        for d, L in zip(self.docs, self.lens):
            s = 0.0
            for t in query:
                f = d.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * L / self.avg))
            out.append(s)
        return out


def tool_text(tool, fields):
    parts = []
    if "name" in fields:
        parts.append(tool["name"])
    if "description" in fields:
        parts.append(tool.get("description", ""))
    if "params" in fields:
        for pname, p in tool.get("inputSchema", {}).get("properties", {}).items():
            parts.append(pname)
            parts.append(p.get("description", "") if isinstance(p, dict) else "")
    return " ".join(parts)


def load_jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", default="experiment_competitors.json")
    ap.add_argument("--queries", default="queries_pilot_v2.jsonl")
    ap.add_argument("--results", default="results/competitors_gemini-3.6-flash.jsonl")
    ap.add_argument("--fields", default="name,description", help="name,description,params")
    ap.add_argument("--show", type=int, default=0, help="ennyi lekérdezés top-3 listáját írja ki")
    args = ap.parse_args()

    cfg = json.loads(Path(args.experiment).read_text(encoding="utf-8"))
    fields = set(args.fields.split(","))
    servers = {s: json.loads(Path(f).read_text(encoding="utf-8"))["tools"] for s, f in cfg["servers"].items()}
    queries = load_jsonl(args.queries)

    llm = defaultdict(Counter)       # condition -> server counts
    llm_by_q = defaultdict(Counter)  # (condition, qid) -> server counts
    if args.results and Path(args.results).exists():
        for r in load_jsonl(args.results):
            if r.get("status") != "ok":
                continue
            srv = r.get("first_call_server") or "(nincs hívás)"
            llm[r["condition"]][srv] += 1
            llm_by_q[(r["condition"], r["query_id"])][srv] += 1

    for env_name, env in cfg["environments"].items():
        corpus = []  # (server, tool_name, tokens)
        for srv, sel in env.items():
            for t in servers[srv]:
                if sel == "*" or t["name"] in sel:
                    corpus.append((srv, t["name"], tokenize(tool_text(t, fields))))
        bm = BM25([c[2] for c in corpus])

        top1 = Counter()
        agree = n_cmp = 0
        print(f"\n=== környezet: {env_name}  ({len(corpus)} tool, mezők: {args.fields}) ===")
        for i, q in enumerate(queries):
            sc = bm.scores(tokenize(q["text"]))
            ranked = sorted(range(len(corpus)), key=lambda j: -sc[j])
            best = corpus[ranked[0]][0] if sc[ranked[0]] > 0 else "(0 pont)"
            top1[best] += 1
            lq = llm_by_q.get((env_name, q["id"]))
            if lq:
                n_cmp += 1
                agree += lq.most_common(1)[0][0] == best
            if i < args.show:
                tops = ", ".join(f"{corpus[j][0]}/{corpus[j][1]}={sc[j]:.2f}" for j in ranked[:3])
                print(f"  {q['id']}: {tops}")

        allsrv = sorted(set(top1) | set(llm.get(env_name, {})))
        ltot = sum(llm.get(env_name, {}).values())
        print(f"  {'szerver':<16}{'BM25 top-1':>12}{'LLM első hívás':>18}")
        for s in allsrv:
            b = top1[s] / len(queries)
            l = llm[env_name][s] / ltot if ltot else float("nan")
            print(f"  {s:<16}{b:>11.0%}{l:>17.0%}")
        if n_cmp:
            print(f"  egyezés (BM25 top-1 vs LLM leggyakoribb első szerver / lekérdezés): {agree}/{n_cmp}")


if __name__ == "__main__":
    main()
