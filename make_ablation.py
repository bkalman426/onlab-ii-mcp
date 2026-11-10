"""
Feature ablation: kitakart leírásváltozatok és konfiguráció előállítása.

Bemenet:
  ablation_spec.json   melyik változat mely részeit (feature-eit) takarjuk ki
  variants.json        a saját tool leírásváltozatai
  <alapkonfiguráció>   pl. experiment_anon_B.json (ebből veszi a közös beállításokat)

Kimenet:
  variants.json        kiegészítve a kitakart változatokkal (family = "ABL")
  experiment_anon_ABL.json   konfiguráció: baseline + a szülők + a kitakart változatok

A szülő feltételek (pl. A_authoritative, B_t_fresh) és a baseline már le vannak futtatva
ugyanabba az eredményfájlba, ezért a harness azokat kihagyja; csak a kitakart változatok futnak.

Futtatás:  python make_ablation.py
           python make_ablation.py --base experiment_anon_B.json --out experiment_anon_ABL.json
"""

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="ablation_spec.json")
    ap.add_argument("--variants", default="variants.json")
    ap.add_argument("--base", default="experiment_anon_B.json",
                    help="alapkonfiguráció: ebből jön minden közös beállítás és az eredményfájl")
    ap.add_argument("--out", default="experiment_anon_ABL.json")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    vpath = Path(args.variants)
    variants = json.loads(vpath.read_text(encoding="utf-8"))
    template = variants["template"]
    by_id = {v["id"]: v for v in variants["description_variants"]}
    base_words = len(by_id["baseline"]["description"].split())

    # Korábbi futásból maradt kitakart változatok cseréje (a script újrafuttatható).
    variants["description_variants"] = [v for v in variants["description_variants"] if v.get("family") != "ABL"]

    new_variants, conditions = [], []
    for abl in spec["ablations"]:
        parent = by_id[abl["parent_variant"]]
        slot = parent["slot_sentence"]
        print(f"\n{abl['parent_condition']}  (szülő: {parent['id']})")
        print(f"  teljes:      {slot}")
        for f in abl["features"]:
            n = slot.count(f["find"])
            if n != 1:
                raise SystemExit(f"[{parent['id']}/{f['id']}] a 'find' szöveg {n}-szor szerepel, pontosan 1 kell: {f['find']!r}")
            new_slot = slot.replace(f["find"], f["replace"])
            vid = f"abl_{parent['id']}__{f['id']}"
            desc = template.replace("{SLOT}", new_slot)
            w = len(desc.split())
            new_variants.append({
                "id": vid, "family": "ABL", "parent": parent["id"], "feature": f["id"],
                "feature_label": f["label"], "mpma_category": parent.get("mpma_category"),
                "target_category": parent.get("target_category"),
                "slot_sentence": new_slot, "description": desc, "words": w,
                "length_vs_baseline_pct": round(100 * (w - base_words) / base_words, 1),
            })
            conditions.append({"id": f"ABL__{abl['parent_condition']}__{f['id']}", "variant": vid})
            print(f"  -{f['id']:<12} {new_slot}   ({w} szó)")

    variants["description_variants"] += new_variants
    vpath.write_text(json.dumps(variants, ensure_ascii=False, indent=2), encoding="utf-8")

    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    template_cond = next(c for c in base["conditions"] if c["id"] == "baseline")

    def cond(cid, desc):
        c = json.loads(json.dumps(template_cond))
        c["id"] = cid
        c["own"]["description"] = desc
        return c

    cfg = {k: v for k, v in base.items() if k not in ("conditions", "name", "_comment")}
    cfg["name"] = "anon_ablation"
    cfg["_comment"] = (
        "Feature ablation (make_ablation.py, ablation_spec.json). Ugyanabba az eredményfájlba ír, mint az "
        "anonimizált A és B család: a baseline és a szülő feltételek már készek, csak a kitakart változatok "
        "futnak. A sorrendek ugyanazok (rotations és seed az alapkonfigurációból), így minden kitakart mérés "
        "párosítható a szülője azonos kérdésű és sorrendű mérésével.")
    parents = {}
    for abl in spec["ablations"]:
        parents[abl["parent_condition"]] = abl["parent_variant"]
    cfg["conditions"] = ([template_cond]
                         + [cond(pc, pv) for pc, pv in parents.items()]
                         + [cond(c["id"], c["variant"]) for c in conditions])
    Path(args.out).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(new_variants)} kitakart változat -> {vpath}")
    print(f"Konfiguráció -> {args.out}  (feltételek: {[c['id'] for c in cfg['conditions']]})")


if __name__ == "__main__":
    main()