#!/usr/bin/env python3
"""V6 후속 — '조문인식(article-aware) 권고' 변형의 구체성 향상 측정 하네스.

[목적]
V6 측정에서 Layer1 generic 템플릿은 구체율 21%로 바닥이었다. Layer3(LLM 맥락화)는
API키 미설정으로 불가하므로, **키 없이** 템플릿에 그 조문의 고유정보
(조문번호·제목·finding.matched_text/키워드)를 끼워넣은 변형 권고를 만들면
'구체'가 얼마나 오르는지를 동일 채점기로 측정한다.

[원칙]
- 채점 로직(정확/구체/실행가능)·표본(TP 조문, Layer1)·파이프라인은
  scripts/measure_reco_quality.py 를 **그대로 재사용**(동일 잣대).
- engine/recommender.py·config 영구수정 금지. 변형은 **이 스크립트 내부에서만** 생성.
- LLM 미사용. 커밋 금지. 측정 전용.

[출력]
    outputs/reco_article_aware_measure.json
    stdout — [baseline Layer1] vs [조문인식 변형] 3축 비교
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine import fpc, recommender, scorer  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402

# --- baseline 하네스의 채점기/표본/유틸을 그대로 재사용 (동일 잣대 보장) ---
import scripts.measure_reco_quality as base  # noqa: E402

REPORT_PATH = REPO / "outputs" / "reco_article_aware_measure.json"


def make_article_aware(rec_text: str, article_no: str | None,
                       article_title: str | None, matched_text: str | None) -> str:
    """측정용 조문인식 변형 생성 (engine/config 무수정, 이 함수 내부 한정).

    기존 Layer1 템플릿 문장 앞에, 그 조문의 고유정보를 끼워넣은 '지칭 prefix' 를
    붙인다. 끼워넣는 정보:
        - 조문번호 (예: 제25조)  → 구체 채점의 _ARTICLE_REF_RX 매칭 유도
        - 조문제목 (있으면)
        - matched_text 또는 핵심 키워드 (있으면, 작은따옴표 인용)
    이는 '맞춤 처방'이 아니라 '지칭(reference)'만 만든다는 점을 의도적으로 유지
    (자동채점이 이를 과대평가하는지 보기 위함).
    """
    base_text = (rec_text or "").strip()
    if not base_text:
        return base_text

    # 1) 조문 지칭부 (번호 + 제목)
    ref_bits = []
    if article_no:
        if article_title:
            ref_bits.append(f"{article_no}({article_title})")
        else:
            ref_bits.append(article_no)
    elif article_title:
        ref_bits.append(article_title)

    # 2) 문제 문구 인용 (matched_text 우선, 첫 키워드)
    quote = ""
    mt = (matched_text or "").strip()
    if mt:
        # matched_text 가 "A, B, C" 형태면 첫 항목만 인용 (대표 키워드)
        first_kw = mt.split(",")[0].strip()
        if first_kw:
            quote = f" 문제 문구 '{first_kw}'"

    if ref_bits:
        prefix = "".join(ref_bits) + quote + " 관련: "
    elif quote:
        prefix = quote.strip() + " 관련: "
    else:
        # 끼워넣을 조문정보가 전혀 없으면 baseline 과 동일 (변형 효과 없음)
        return base_text

    return prefix + base_text


def main() -> int:
    fid_map = json.loads(base.FID_MAP_PATH.read_text(encoding="utf-8"))

    # 1) TP 행 수집 (baseline 과 동일)
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
                "fid": fid,
                "rule_id": d["rule_id"],
                "law_name": law_name,
                "evidence": d.get("evidence", ""),
                "article": fid_map.get(fid),
            })

    total_tp = len(tp_rows)

    # 2) 표본: baseline 과 동일 (rule_id 별 고르게, 동일 seed)
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

    # 3) 법령별 엔진 1회 실행 (baseline 과 동일 파이프라인)
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
        result = recommender.apply(result)  # Layer1 템플릿 부착

        # 조문 제목 조회용 인덱스
        art_title_idx = {base._normalize_article(a.number): a.title for a in law.articles}

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

            rec = fobj.recommendation or {}
            rec_text = rec.get("template") or ""
            article_title = art_title_idx.get(base._normalize_article(art))
            matched_text = fobj.matched_text

            # --- baseline 채점 (동일 채점기) ---
            b_acc = base.score_accuracy(fobj, rec_text)
            b_spec = base.score_specificity(rec_text, art)
            b_actn = base.score_actionability(rec_text)

            # --- 조문인식 변형 채점 (동일 채점기) ---
            aa_text = make_article_aware(rec_text, art, article_title, matched_text)
            a_acc = base.score_accuracy(fobj, aa_text)
            a_spec = base.score_specificity(aa_text, art)
            a_actn = base.score_actionability(aa_text)

            records.append({
                **r,
                "status": "scored",
                "severity": fobj.severity,
                "pattern_id": fobj.pattern_id,
                "article_title": article_title,
                "matched_text": matched_text,
                "baseline_recommendation": rec_text,
                "article_aware_recommendation": aa_text,
                "baseline": {"accuracy": b_acc, "specificity": b_spec, "actionability": b_actn},
                "article_aware": {"accuracy": a_acc, "specificity": a_spec, "actionability": a_actn},
            })

    scored = [x for x in records if x["status"] == "scored"]
    n = len(scored)

    def axis_summary(variant: str):
        spec_dist = {i: 0 for i in range(3)}
        acc_dist = {i: 0 for i in range(2)}
        actn_dist = {i: 0 for i in range(3)}
        for x in scored:
            v = x[variant]
            spec_dist[v["specificity"]] += 1
            acc_dist[v["accuracy"]] += 1
            actn_dist[v["actionability"]] += 1
        if not n:
            return None
        return {
            "accuracy": {
                "dist": acc_dist,
                "mean": round(sum(x[variant]["accuracy"] for x in scored) / n, 3),
                "max": 1,
            },
            "specificity": {
                "dist": spec_dist,
                "mean": round(sum(x[variant]["specificity"] for x in scored) / n, 3),
                "pct_specific_ge1": round(
                    sum(1 for x in scored if x[variant]["specificity"] >= 1) / n, 3),
                "max": 2,
            },
            "actionability": {
                "dist": actn_dist,
                "mean": round(sum(x[variant]["actionability"] for x in scored) / n, 3),
                "max": 2,
            },
        }

    baseline_ax = axis_summary("baseline")
    aware_ax = axis_summary("article_aware")

    deltas = None
    if n:
        deltas = {
            "specificity_mean": round(
                aware_ax["specificity"]["mean"] - baseline_ax["specificity"]["mean"], 3),
            "specificity_pct_ge1": round(
                aware_ax["specificity"]["pct_specific_ge1"]
                - baseline_ax["specificity"]["pct_specific_ge1"], 3),
            "accuracy_mean": round(
                aware_ax["accuracy"]["mean"] - baseline_ax["accuracy"]["mean"], 3),
            "actionability_mean": round(
                aware_ax["actionability"]["mean"] - baseline_ax["actionability"]["mean"], 3),
        }

    # per-rule 구체 비교
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
                "aware_spec": round(sum(x["article_aware"]["specificity"] for x in xs) / k, 2),
            }
        return out

    summary = {
        "total_tp_rows": total_tp,
        "sample_size": len(sample),
        "scored": n,
        "skipped": skipped,
        "baseline_axes": baseline_ax,
        "article_aware_axes": aware_ax,
        "deltas": deltas,
        "per_rule_specificity": per_rule_spec(),
    }

    report = {
        "_meta": {
            "purpose": "V6 후속 — 조문인식 권고 변형의 구체성 향상 측정 (키 없이 템플릿 정보주입)",
            "pipeline": "run_all -> fpc.correct -> scorer.compute -> recommender.apply (baseline 동일)",
            "llm": False,
            "sample_per_rule": base.SAMPLE_PER_RULE,
            "seed": base.RANDOM_SEED,
            "scoring": "scripts/measure_reco_quality.py 의 score_accuracy/specificity/actionability 그대로 재사용",
            "variant": "조문번호+제목+matched_text 첫 키워드를 baseline 템플릿 앞에 지칭 prefix 로 주입",
            "caveat": (
                "조문번호·키워드 끼워넣기는 '지칭(reference)'은 만들지만 '맞춤 처방'은 아님. "
                "자동 휴리스틱 채점(_ARTICLE_REF_RX/숫자/인용부호 존재)이 이 지칭만으로 구체점수를 "
                "올려주므로 실제 권고 유용성을 과대평가할 수 있음. 진짜 맥락화는 Layer3(LLM) 필요."
            ),
        },
        "summary": summary,
        "records": records,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout 요약
    print(f"\nTP 전체: {total_tp}  표본: {len(sample)}  채점됨: {n}")
    print(f"스킵: {skipped}")
    if n:
        b, a = baseline_ax, aware_ax
        print("\n[3축 비교 — baseline Layer1 vs 조문인식 변형 / 동일 채점기]")
        print(f"  {'축':<14}{'baseline':>22}{'article-aware':>22}")
        print(f"  {'정확(0/1) mean':<14}{b['accuracy']['mean']:>22}{a['accuracy']['mean']:>22}")
        print(f"  {'구체(0/2) mean':<14}{b['specificity']['mean']:>22}{a['specificity']['mean']:>22}")
        print(f"  {'구체율(>=1)':<14}{b['specificity']['pct_specific_ge1']:>22}{a['specificity']['pct_specific_ge1']:>22}")
        print(f"  {'실행(0/2) mean':<14}{b['actionability']['mean']:>22}{a['actionability']['mean']:>22}")
        print(f"\n  구체 분포  baseline={b['specificity']['dist']}  aware={a['specificity']['dist']}")
        print(f"\n[델타]  구체mean {deltas['specificity_mean']:+}  구체율 {deltas['specificity_pct_ge1']:+}  "
              f"정확 {deltas['accuracy_mean']:+}  실행 {deltas['actionability_mean']:+}")
        print("\n[예시 2건]")
        for x in scored[:2]:
            print(f"  - {x['fid']} ({x['article']}, {x.get('severity')})")
            print(f"    baseline    구체={x['baseline']['specificity']}: {x['baseline_recommendation'][:70]}")
            print(f"    aware       구체={x['article_aware']['specificity']}: {x['article_aware_recommendation'][:90]}")
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
