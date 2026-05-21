"""SLM 가중치 캘리브레이션 (R3 — verdict-fitted).

verdict 데이터로부터 각 카테고리 신경망의 신호별 평균 분포를 추출하여
TP vs FP 분리도가 높은 신호를 자동 부각.

출력:
- outputs/slm_signal_stats.json: 카테고리별 신호 통계 (TP/FP mean, gap)
- 표준 출력: 권장 가중치 조정 표
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.parser import parse_law
from engine.structure import decompose
from engine.slm import extract_features
from engine.slm.brain import CATEGORIES, WEIGHTS


# Rule → category
RULE_CAT = {
    "S-01": "구조", "S-02": "구조", "S-03": "구조", "S-04": "구조",
    "F-01": "공정성", "F-02": "공정성", "F-03": "공정성", "F-04": "공정성", "F-05": "공정성",
    "L-01": "적법성", "L-02": "적법성", "L-03": "적법성",
    "G-01": "거버넌스", "G-02": "거버넌스", "G-03": "거버넌스", "G-04": "거버넌스", "G-05": "거버넌스",
    "E-01": "효율성", "E-02": "효율성", "E-03": "효율성", "E-04": "효율성", "E-05": "효율성",
}


def load_verdicts() -> list[dict]:
    rows = []
    p = Path("outputs/verification_dataset.jsonl")
    with p.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def load_fid_map() -> dict[str, str]:
    p = Path("outputs/fid_article_map.json")
    return json.loads(p.read_text(encoding="utf-8"))


def calibrate():
    rows = load_verdicts()
    fid_map = load_fid_map()

    # 카테고리별 signal 분포 수집
    # signal_stats[cat][signal] = {'tp': [vals], 'fp': [vals]}
    signal_stats: dict[str, dict[str, dict[str, list[float]]]] = {
        c: defaultdict(lambda: {"tp": [], "fp": []}) for c in CATEGORIES
    }

    for r in rows:
        rule_id = r["rule_id"]
        verdict = r["verdict"]
        if verdict not in ("TP", "FP"):
            continue
        cat = RULE_CAT.get(rule_id)
        if not cat:
            continue
        fid = r["fid"]
        if "@" not in fid:
            continue
        _, law_name = fid.split("@", 1)
        an = fid_map.get(fid)
        if not an:
            continue

        md = Path(f"data/laws/raw/{law_name}/법률.md")
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2]
        try:
            law = parse_law(text, name=law_name)
        except Exception:
            continue
        art = next((a for a in law.articles if a.number.replace(" ", "") == an.replace(" ", "")), None)
        if not art:
            continue
        d = decompose(art)
        fv = extract_features(art, d).to_dict()

        bucket = "tp" if verdict == "TP" else "fp"
        for sig, val in fv.items():
            signal_stats[cat][sig][bucket].append(val)

    # 신호별 분리도 계산
    report: dict[str, list[dict]] = {}
    for cat in CATEGORIES:
        rows_for_cat = []
        for sig, vals in signal_stats[cat].items():
            tp_vals = vals["tp"]
            fp_vals = vals["fp"]
            if not tp_vals and not fp_vals:
                continue
            tp_mean = sum(tp_vals) / len(tp_vals) if tp_vals else 0.0
            fp_mean = sum(fp_vals) / len(fp_vals) if fp_vals else 0.0
            gap = tp_mean - fp_mean  # 양수 → TP 가 더 자주 high → 결함 신호
            rows_for_cat.append({
                "signal": sig,
                "tp_mean": round(tp_mean, 3),
                "fp_mean": round(fp_mean, 3),
                "gap": round(gap, 3),
                "n_tp": len(tp_vals),
                "n_fp": len(fp_vals),
            })
        rows_for_cat.sort(key=lambda x: -abs(x["gap"]))
        report[cat] = rows_for_cat[:30]

    Path("outputs/slm_signal_stats.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 보고서 출력
    for cat in CATEGORIES:
        print(f"\n=== {cat} (상위 신호별 TP-FP gap) ===")
        print(f"{'signal':<25} {'TP_mean':>8} {'FP_mean':>8} {'gap':>8} {'n_tp':>5} {'n_fp':>5}")
        for r in report[cat][:15]:
            print(f"{r['signal']:<25} {r['tp_mean']:>8.3f} {r['fp_mean']:>8.3f} "
                  f"{r['gap']:>+8.3f} {r['n_tp']:>5} {r['n_fp']:>5}")

    print("\n캘리브레이션 데이터: outputs/slm_signal_stats.json")

    # 권장 가중치 — gap 이 큰 신호를 기준으로 카테고리별 자동 생성
    print("\n=== 권장 WEIGHTS (verdict-fitted, gap 기반) ===")
    suggested = {}
    for cat in CATEGORIES:
        weights_for_cat = {}
        for r in report[cat]:
            # 최소 표본 + 최소 gap 임계
            if r["n_tp"] < 5 or r["n_fp"] < 5:
                continue
            if abs(r["gap"]) < 0.05:
                continue
            # gap 을 가중치로 직접 활용 (scale 1.0)
            weights_for_cat[r["signal"]] = round(r["gap"], 3)
        suggested[cat] = weights_for_cat

    Path("outputs/slm_weights_calibrated.json").write_text(
        json.dumps(suggested, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("권장 가중치 저장: outputs/slm_weights_calibrated.json")


if __name__ == "__main__":
    calibrate()
