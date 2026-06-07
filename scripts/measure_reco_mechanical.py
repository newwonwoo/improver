#!/usr/bin/env python3
"""V6 후속 — '기계적 조문맞춤 권고' 프로토타입 측정 하네스 (LLM 절대 미사용).

[배경 / 직전 시도의 실패]
- Layer1 generic 템플릿: 구체율 21%, 조문 고유성 ≈0 (measure_reco_quality.py).
- 직전 '조문번호 주입'(measure_reco_article_aware.py): 자동채점기를 게이밍.
  prefix 의 인용이 내부 패턴태그('아날로그(강)', '강한 처분')라 무의미했음.
  → 채점기가 '제N조' 존재만으로 구체점수를 줘서 과대평가.

[이번 지시 — 전부 기계적, LLM 없음]
1. measure_reco_quality.py 와 동일 표본·동일 파이프라인 재사용.
2. 기계적 조문맞춤 권고 생성기 (이 스크립트 내부 함수, engine/config 무수정):
   - 파서 구조(Article.full_text / paragraphs)에서 그 finding 의 **실제 문제 문구를
     verbatim 추출**. 내부 태그(matched_text='아날로그(강)') 가 아니라 조문 본문의
     실제 절(예: 포괄위임이면 "...그 밖에 필요한 사항은 대통령령으로 정한다").
   - 결함유형(pattern_id)별 구조적 처방 합성:
       [verbatim 인용]  +  [결함에 맞는 개정 동작(한정열거/분리/기준명시 등)]
     전부 규칙·템플릿 슬롯 채우기. LLM 없음.
3. 채점기 강화: 기존 구체 채점의 취약점(=조문번호·내부태그 존재만으로 만점) 수정.
   → **권고에 포함된 인용이 그 조문 본문에서 verbatim 으로 실제 추출된 구절일 때만**
     구체 점수. 단순 '제N조'·내부태그는 불인정.
4. [baseline Layer1] vs [기계적 조문맞춤] 을 강화 채점기로 비교.

[출력]
    outputs/reco_mechanical_measure.json
    stdout — 3축 비교 + 예시 3건 + 한계

측정 전용. 프로덕션 무수정. 커밋 금지. LLM/외부 API 호출 0회.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine import fpc, recommender, scorer  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402

# baseline 하네스의 표본/파이프라인/유틸/채점기 재사용 (동일 잣대 보장)
import scripts.measure_reco_quality as base  # noqa: E402

REPORT_PATH = REPO / "outputs" / "reco_mechanical_measure.json"



# ════════════════════════════════════════════════════════════════════════
#  (A)~(C) 추출·처방·채점 — scripts/mechanical_reco 로 단일화 (중복 제거)
#  · extract_verbatim: 인용 결함(L-01/L-02/L-03)을 matched_text 앵커로 추출 [버그 L-03 수정]
#  · _PRESCRIPTION   : '단정→근거기반 검토제시', 근거 없는 숫자 제거 [결정 3]
#  · score_specificity_strong: 구(舊) 자동 구체 채점 (참고용; gold 상관은 score_adoption)
#  gold 검증은 scripts/measure_gold_correlation.py 가 수행한다.
# ════════════════════════════════════════════════════════════════════════
from scripts.mechanical_reco import (  # noqa: E402
    _DEFECT_TRIGGERS, _EXTRACT_GRADE, extract_verbatim,
    _PRESCRIPTION, _FALLBACK, make_mechanical,
    score_specificity_strong,
)


def score_actionability(rec_text: str) -> int:
    return base.score_actionability(rec_text)


# ════════════════════════════════════════════════════════════════════════
#  (D) 메인 — baseline vs mechanical, 강화 채점기로 비교
# ════════════════════════════════════════════════════════════════════════
def main() -> int:
    fid_map = json.loads(base.FID_MAP_PATH.read_text(encoding="utf-8"))

    # 1) TP 행 수집 (baseline 동일)
    tp_rows = []
    with base.VERDICTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("verdict") != "TP":
                continue
            fid = d.get("fid")
            if not fid or "@" not in fid:
                continue
            _, law_name = fid.split("@", 1)
            tp_rows.append({
                "fid": fid, "rule_id": d["rule_id"], "law_name": law_name,
                "evidence": d.get("evidence", ""), "article": fid_map.get(fid),
            })

    total_tp = len(tp_rows)

    # 2) 표본 (baseline 동일: rule_id 별 고르게, 동일 seed)
    import random
    rng = random.Random(base.RANDOM_SEED)
    by_rule = defaultdict(list)
    for r in tp_rows:
        by_rule[r["rule_id"]].append(r)
    sample = []
    for rule_id in sorted(by_rule):
        rows = by_rule[rule_id][:]
        rng.shuffle(rows)
        sample.extend(rows[:base.SAMPLE_PER_RULE])
    sample.sort(key=lambda r: (r["rule_id"], r["law_name"]))

    # 3) 법령별 엔진 1회 (baseline 동일 파이프라인)
    by_law = defaultdict(list)
    for r in sample:
        by_law[r["law_name"]].append(r)

    records = []
    skipped = {"missing_law": 0, "fn_not_fired": 0, "unmapped": 0}

    for law_name, rows in by_law.items():
        md = base.LAWS_DIR / law_name / "법률.md"
        if not md.exists():
            for r in rows:
                skipped["missing_law"] += 1
                records.append({**r, "status": "missing_law"})
            continue
        text = base._strip_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        law = parse_law(text, name=law_name, law_category=base._categorize(law_name))
        findings = run_all(law)
        findings = fpc.correct(law, findings)
        result = scorer.compute(law, findings)
        result = recommender.apply(result)  # Layer1 부착

        art_by_norm = {base._normalize_article(a.number): a for a in law.articles}
        idx = {}
        for fobj in result.findings:
            idx[(fobj.pattern_id, base._normalize_article(fobj.article_number))] = fobj

        for r in rows:
            art = r["article"]
            if not art:
                skipped["unmapped"] += 1
                records.append({**r, "status": "unmapped"})
                continue
            fobj = idx.get((r["rule_id"], base._normalize_article(art)))
            if fobj is None:
                skipped["fn_not_fired"] += 1
                records.append({**r, "status": "fn_not_fired"})
                continue
            article = art_by_norm.get(base._normalize_article(art))
            if article is None:
                skipped["fn_not_fired"] += 1
                records.append({**r, "status": "fn_not_fired"})
                continue

            rec = fobj.recommendation or {}
            baseline_text = rec.get("template") or ""

            # --- baseline 을 강화 채점기로 채점 ---
            b_acc = base.score_accuracy(fobj, baseline_text)
            b_spec, b_reason = score_specificity_strong(baseline_text, article)
            b_actn = score_actionability(baseline_text)

            # --- 기계적 조문맞춤 권고 생성 + 강화 채점 ---
            mech_text, verbatim, method = make_mechanical(article, fobj)
            m_acc = base.score_accuracy(fobj, mech_text)
            m_spec, m_reason = score_specificity_strong(mech_text, article)
            m_actn = score_actionability(mech_text)

            records.append({
                **r,
                "status": "scored",
                "severity": fobj.severity,
                "pattern_id": fobj.pattern_id,
                "internal_matched_text": fobj.matched_text,
                "verbatim_extracted": verbatim,
                "extract_method": method,
                "extract_grade": _EXTRACT_GRADE.get(fobj.pattern_id, "keyword"),
                "baseline_recommendation": baseline_text,
                "mechanical_recommendation": mech_text,
                "baseline": {"accuracy": b_acc, "specificity": b_spec,
                             "actionability": b_actn, "spec_reason": b_reason},
                "mechanical": {"accuracy": m_acc, "specificity": m_spec,
                               "actionability": m_actn, "spec_reason": m_reason},
            })

    scored = [x for x in records if x["status"] == "scored"]
    n = len(scored)

    def axis_summary(variant: str):
        if not n:
            return None
        spec_dist = {i: 0 for i in range(3)}
        actn_dist = {i: 0 for i in range(3)}
        acc_dist = {i: 0 for i in range(2)}
        for x in scored:
            v = x[variant]
            spec_dist[v["specificity"]] += 1
            actn_dist[v["actionability"]] += 1
            acc_dist[v["accuracy"]] += 1
        return {
            "accuracy": {"dist": acc_dist,
                         "mean": round(sum(x[variant]["accuracy"] for x in scored) / n, 3)},
            "specificity": {
                "dist": spec_dist,
                "mean": round(sum(x[variant]["specificity"] for x in scored) / n, 3),
                "pct_specific_ge1": round(
                    sum(1 for x in scored if x[variant]["specificity"] >= 1) / n, 3),
            },
            "actionability": {
                "dist": actn_dist,
                "mean": round(sum(x[variant]["actionability"] for x in scored) / n, 3)},
        }

    baseline_ax = axis_summary("baseline")
    mech_ax = axis_summary("mechanical")

    deltas = None
    if n:
        deltas = {
            "specificity_mean": round(mech_ax["specificity"]["mean"]
                                      - baseline_ax["specificity"]["mean"], 3),
            "specificity_pct_ge1": round(mech_ax["specificity"]["pct_specific_ge1"]
                                         - baseline_ax["specificity"]["pct_specific_ge1"], 3),
            "actionability_mean": round(mech_ax["actionability"]["mean"]
                                        - baseline_ax["actionability"]["mean"], 3),
        }

    # verbatim 추출 성공률 (등급별)
    extract_stats = defaultdict(lambda: {"n": 0, "extracted": 0})
    for x in scored:
        g = x["extract_grade"]
        extract_stats[g]["n"] += 1
        if x["verbatim_extracted"]:
            extract_stats[g]["extracted"] += 1
    extract_summary = {g: {"n": s["n"], "extracted": s["extracted"],
                           "rate": round(s["extracted"] / s["n"], 2) if s["n"] else None}
                       for g, s in extract_stats.items()}

    def per_rule_spec():
        by = defaultdict(list)
        for x in scored:
            by[x["rule_id"]].append(x)
        out = {}
        for rid, xs in sorted(by.items()):
            k = len(xs)
            out[rid] = {
                "n": k,
                "baseline_spec": round(sum(x["baseline"]["specificity"] for x in xs) / k, 2),
                "mech_spec": round(sum(x["mechanical"]["specificity"] for x in xs) / k, 2),
                "verbatim_rate": round(sum(1 for x in xs if x["verbatim_extracted"]) / k, 2),
            }
        return out

    summary = {
        "total_tp_rows": total_tp,
        "sample_size": len(sample),
        "scored": n,
        "skipped": skipped,
        "baseline_axes": baseline_ax,
        "mechanical_axes": mech_ax,
        "deltas": deltas,
        "verbatim_extraction_by_grade": extract_summary,
        "per_rule": per_rule_spec(),
    }

    report = {
        "_meta": {
            "purpose": "기계적 조문맞춤 권고 프로토타입 — verbatim 추출 + 구조적 처방 합성 (LLM 0회)",
            "pipeline": "run_all -> fpc.correct -> scorer.compute -> recommender.apply (baseline 동일)",
            "llm": False,
            "llm_calls": 0,
            "external_api_calls": 0,
            "sample_per_rule": base.SAMPLE_PER_RULE,
            "seed": base.RANDOM_SEED,
            "scoring_change": (
                "강화 구체 채점: '제N조' 존재·내부태그 인용은 0점. "
                "권고의 인용이 조문 full_text 의 verbatim 부분문자열(>=6자)일 때만 +1, "
                "길거나 다어절이면 +1 (최대 2). baseline 도 동일 강화기로 재채점."
            ),
            "anti_gaming": (
                "직전 시도(조문번호 주입)는 _ARTICLE_REF_RX 게이밍이었음. 본 강화기는 조문번호·"
                "내부태그를 무시하고 본문 verbatim 일치만 인정 → 게이밍 차단."
            ),
        },
        "summary": summary,
        "records": records,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout
    print(f"\nTP 전체: {total_tp}  표본: {len(sample)}  채점됨: {n}")
    print(f"스킵: {skipped}")
    print(f"LLM 호출: 0   외부 API 호출: 0")
    if n:
        b, m = baseline_ax, mech_ax
        print("\n[3축 비교 — baseline Layer1 vs 기계적 조문맞춤 / 강화 채점기 동일 적용]")
        print(f"  {'축':<16}{'baseline':>14}{'mechanical':>14}")
        print(f"  {'정확(0/1) mean':<14}{b['accuracy']['mean']:>14}{m['accuracy']['mean']:>14}")
        print(f"  {'구체(0/2) mean':<14}{b['specificity']['mean']:>14}{m['specificity']['mean']:>14}")
        print(f"  {'구체율(>=1)':<16}{b['specificity']['pct_specific_ge1']:>14}"
              f"{m['specificity']['pct_specific_ge1']:>14}")
        print(f"  {'실행(0/2) mean':<14}{b['actionability']['mean']:>14}{m['actionability']['mean']:>14}")
        print(f"\n  구체 분포  baseline={b['specificity']['dist']}  mechanical={m['specificity']['dist']}")
        print(f"\n[델타]  구체mean {deltas['specificity_mean']:+}  "
              f"구체율 {deltas['specificity_pct_ge1']:+}  실행 {deltas['actionability_mean']:+}")
        print(f"\n[verbatim 추출 성공률 / 등급별]")
        for g, s in sorted(extract_summary.items()):
            print(f"  {g:<8} n={s['n']:>2}  추출={s['extracted']:>2}  성공률={s['rate']}")

        # 예시 3건: verbatim 이 실제 조문 문구인지 눈으로 보이게
        print("\n[예시 3건 — verbatim 인용이 실제 조문 본문 문구인가]")
        shown = 0
        for x in scored:
            if not x["verbatim_extracted"]:
                continue
            print(f"  · {x['fid']} ({x['article']}, {x['pattern_id']}/{x['severity']}, "
                  f"grade={x['extract_grade']})")
            print(f"    내부태그(무의미): {x['internal_matched_text']!r}")
            print(f"    verbatim 추출  : 「{x['verbatim_extracted']}」")
            print(f"    baseline  구체={x['baseline']['specificity']}: {x['baseline_recommendation'][:65]}")
            print(f"    mechanical 구체={x['mechanical']['specificity']}: {x['mechanical_recommendation'][:110]}")
            shown += 1
            if shown >= 3:
                break
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
