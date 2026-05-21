"""SLM 가중치 캘리브레이션 v2 — verdict + corpus-wide signal frequency.

v1: gap × (1 - fp_mean) — verdict 데이터 내부 통계만 활용
v2: gap × (1 - corpus_fire_rate) — 외부 corpus 의 일반 발화율로 정규화
    → verdict 셋에 over-fit 되지 않은 가중치 도출

추가: 외부 reference corpus (legalize-kr 등) 의 article 신호 평균을 활용해
     "정상 입법에서도 자주 등장하는 신호" 자동 감쇄.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.parser import parse_law
from engine.slm import extract_features
from engine.slm.brain import CATEGORIES

RULE_CAT = {
    "S-01": "구조", "S-02": "구조", "S-03": "구조", "S-04": "구조",
    "F-01": "공정성", "F-02": "공정성", "F-03": "공정성", "F-04": "공정성", "F-05": "공정성",
    "L-01": "적법성", "L-02": "적법성", "L-03": "적법성",
    "G-01": "거버넌스", "G-02": "거버넌스", "G-03": "거버넌스", "G-04": "거버넌스", "G-05": "거버넌스",
    "E-01": "효율성", "E-02": "효율성", "E-03": "효율성", "E-04": "효율성", "E-05": "효율성",
}

# 외부 reference 법령 — legalize-kr 에서 import 한 5개
# 일반 입법 신호의 baseline (verdict 셋에 없는 corpus-wide 패턴)
EXTERNAL_REFS = [
    ("대한민국헌법", "헌법.md"),
    ("공간정보의구축및관리등에관한법률", "시행령.md"),
    ("댐건설ㆍ관리및주변지역지원등에관한법률", "시행령.md"),
    ("혁신도시조성및발전에관한특별법", "시행규칙.md"),
    ("송유관안전관리법", "시행령.md"),
]


def _read_law(law_name: str, file_name: str = "법률.md"):
    md = Path(f"data/laws/raw/{law_name}/{file_name}")
    if not md.exists():
        return None
    text = md.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    try:
        return parse_law(text, name=law_name)
    except Exception:
        return None


def collect_external_signal_baseline():
    """외부 5개 법령에서 신호별 평균 발화율 측정 → corpus baseline."""
    baselines: dict[str, list[float]] = defaultdict(list)
    total_articles = 0
    for law_name, fname in EXTERNAL_REFS:
        law = _read_law(law_name, fname)
        if not law:
            continue
        for art in law.articles:
            if art.is_definition() or art.is_purpose():
                continue
            fv = extract_features(art).to_dict()
            total_articles += 1
            for sig, val in fv.items():
                baselines[sig].append(val)
    return baselines, total_articles


def collect_verdict_stats():
    """verdict 데이터에서 카테고리별 신호 분포 추출."""
    with open("outputs/verification_dataset.jsonl") as f:
        rows = [json.loads(l) for l in f]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    stats: dict[str, dict[str, dict[str, list[float]]]] = {
        c: defaultdict(lambda: {"tp": [], "fp": []}) for c in CATEGORIES
    }

    for r in rows:
        if r["verdict"] not in ("TP", "FP"):
            continue
        rule_id = r["rule_id"]
        cat = RULE_CAT.get(rule_id)
        if not cat:
            continue
        fid = r["fid"]
        if "@" not in fid:
            continue
        _, ln = fid.split("@", 1)
        an = fid_map.get(fid)
        if not an:
            continue
        law = _read_law(ln)
        if not law:
            continue
        art = next((a for a in law.articles if a.number.replace(" ", "") == an.replace(" ", "")), None)
        if not art:
            continue
        fv = extract_features(art).to_dict()
        bucket = "tp" if r["verdict"] == "TP" else "fp"
        for sig, val in fv.items():
            stats[cat][sig][bucket].append(val)
    return stats


def main():
    print("=== Step 1: 외부 reference 5개 법령 baseline 측정 ===")
    baselines, n_ext = collect_external_signal_baseline()
    print(f"외부 corpus: {n_ext} 조문")

    print("\n=== Step 2: verdict 데이터 신호 분포 ===")
    stats = collect_verdict_stats()

    # 신호별 verdict TP/FP mean + corpus baseline mean 산출
    print("\n=== Step 3: 가중치 자동 산출 (verdict_gap × external_correction) ===")
    suggested: dict[str, dict[str, float]] = {}
    for cat in CATEGORIES:
        cat_weights = {}
        print(f"\n--- {cat} ---")
        rows_for_cat = []
        for sig, vals in stats[cat].items():
            tp_vals = vals["tp"]
            fp_vals = vals["fp"]
            if len(tp_vals) < 5 or len(fp_vals) < 5:
                continue
            tp_mean = sum(tp_vals) / len(tp_vals)
            fp_mean = sum(fp_vals) / len(fp_vals)
            gap = tp_mean - fp_mean
            if abs(gap) < 0.05:
                continue
            ext_baseline = (sum(baselines[sig]) / len(baselines[sig])) if baselines[sig] else 0.0
            # 핵심 보정: gap × (1 - max(fp_mean, ext_baseline))
            # → verdict FP 빈출 + 외부 일반 빈출 신호 둘 다 감쇄
            damping = max(fp_mean, ext_baseline)
            adjusted = gap * (1.0 - damping)
            if abs(adjusted) < 0.025:
                continue
            cat_weights[sig] = round(adjusted, 3)
            rows_for_cat.append({
                "signal": sig,
                "tp_mean": round(tp_mean, 3),
                "fp_mean": round(fp_mean, 3),
                "ext_baseline": round(ext_baseline, 3),
                "damping": round(damping, 3),
                "gap": round(gap, 3),
                "weight": round(adjusted, 3),
            })
        suggested[cat] = cat_weights
        rows_for_cat.sort(key=lambda x: -abs(x["weight"]))
        for r in rows_for_cat[:10]:
            print(f"  {r['signal']:<25} gap={r['gap']:+.2f} fp={r['fp_mean']:.2f} "
                  f"ext={r['ext_baseline']:.2f} → w={r['weight']:+.3f}")

    Path("outputs/slm_weights_calibrated.json").write_text(
        json.dumps(suggested, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n가중치 저장: outputs/slm_weights_calibrated.json (v2)")


if __name__ == "__main__":
    main()
