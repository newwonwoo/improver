"""하이브리드 SLM (학습 MLP + hand-tuned) 앙상블 평가.

룰 + hybrid_brain → 카테고리별 진단의 verdict 일치도.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.parser import parse_law
from engine.rules import run_all
from engine.slm.hybrid_brain import diagnose_hybrid


RULE_CAT = {
    "S-01": "구조", "S-02": "구조", "S-03": "구조", "S-04": "구조",
    "F-01": "공정성", "F-02": "공정성", "F-03": "공정성", "F-04": "공정성", "F-05": "공정성",
    "L-01": "적법성", "L-02": "적법성", "L-03": "적법성",
    "G-01": "거버넌스", "G-02": "거버넌스", "G-03": "거버넌스", "G-04": "거버넌스", "G-05": "거버넌스",
    "E-01": "효율성", "E-02": "효율성", "E-03": "효율성", "E-04": "효율성", "E-05": "효율성",
}


def main():
    with open("outputs/verification_dataset.jsonl") as f:
        rows = [json.loads(l) for l in f]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    per_cat: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    )
    overall = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

    by_law: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["verdict"] not in ("TP", "FP"):
            continue
        rule_id = r["rule_id"]
        if rule_id not in RULE_CAT:
            continue
        if "@" not in r["fid"]:
            continue
        _, ln = r["fid"].split("@", 1)
        by_law[ln].append(r)

    for ln, verdicts in by_law.items():
        md = Path(f"data/laws/raw/{ln}/법률.md")
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2]
        try:
            law = parse_law(text, name=ln)
        except Exception:
            continue
        findings = run_all(law)

        def _norm(s): return s.replace(" ", "").strip() if s else ""
        # 룰 fire 인덱스
        rule_fire: dict[tuple[str, str], bool] = {}
        for f in findings:
            cat = RULE_CAT.get(f.pattern_id)
            if cat:
                rule_fire[(cat, _norm(f.article_number))] = True

        # 하이브리드 SLM 진단 — article 별
        art_idx = {a.number.replace(" ", ""): a for a in law.articles}
        slm_fire: dict[tuple[str, str], bool] = {}
        for an_key, art in art_idx.items():
            if art.is_definition() or art.is_purpose():
                continue
            diag = diagnose_hybrid(art)
            for cat, d in diag.items():
                if d.severity is not None:
                    slm_fire[(cat, an_key)] = True

        # 평가
        for r in verdicts:
            an = fid_map.get(r["fid"])
            if not an: continue
            cat = RULE_CAT[r["rule_id"]]
            key = (cat, _norm(an))
            fired = rule_fire.get(key, False) or slm_fire.get(key, False)
            if r["verdict"] == "TP":
                if fired:
                    per_cat[cat]["tp"] += 1; overall["tp"] += 1
                else:
                    per_cat[cat]["fn"] += 1; overall["fn"] += 1
            else:
                if fired:
                    per_cat[cat]["fp"] += 1; overall["fp"] += 1
                else:
                    per_cat[cat]["tn"] += 1; overall["tn"] += 1

    def f1(m):
        p = m["tp"] / max(m["tp"] + m["fp"], 1)
        r = m["tp"] / max(m["tp"] + m["fn"], 1)
        return 2 * p * r / max(p + r, 1e-9)

    print(f"\n{'카테고리':<10} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5} {'P':>6} {'R':>6} {'F1':>6}")
    print("-" * 60)
    for cat in ("구조", "공정성", "적법성", "거버넌스", "효율성"):
        m = per_cat[cat]
        if not (m["tp"] + m["fp"] + m["fn"] + m["tn"]):
            continue
        p = m["tp"] / max(m["tp"] + m["fp"], 1)
        r = m["tp"] / max(m["tp"] + m["fn"], 1)
        ff = f1(m)
        print(f"{cat:<10} {m['tp']:>5} {m['fp']:>5} {m['fn']:>5} {m['tn']:>5} "
              f"{p:>6.3f} {r:>6.3f} {ff:>6.3f}")
    print("-" * 60)
    p = overall["tp"] / max(overall["tp"] + overall["fp"], 1)
    r = overall["tp"] / max(overall["tp"] + overall["fn"], 1)
    ff = f1(overall)
    print(f"{'TOTAL':<10} {overall['tp']:>5} {overall['fp']:>5} {overall['fn']:>5} {overall['tn']:>5} "
          f"{p:>6.3f} {r:>6.3f} {ff:>6.3f}")


if __name__ == "__main__":
    main()
