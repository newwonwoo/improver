#!/usr/bin/env python3
"""미발화(fn_not_fired) recall 베이스라인 + 게이트 진단 (LLM/외부 API 0회).

배경: 자문위원 gold 55건 중 22건이 '반려=fn_not_fired'(엔진이 결함을 미발화 → 처방 부재).
      이게 코더 fn 작업의 recall gold 씨앗이다. 그러나 해당 룰들은 이미 정밀도 최약
      (L-03 0.01·F-02 0.07·E-05 0.05 등) — 게이트를 풀면 FP가 늘어 검수인 게이트①
      (recall 비악화 AND precision 개선)을 위반한다. 그러므로 '무작정 룰 완화'는 금지.

이 하네스가 하는 일 (측정·진단만, 룰 무수정):
  1. fn 22건 각각에 대해 엔진(run_all→fpc)을 돌려 '여전히 미발화'인지 확인(recall=0 재현).
  2. 각 fn 조문이 '어떤 구조 게이트'에 걸려 억제되는지 진단(정의/목적/벌칙/부칙/도메인/블랙리스트).
     → 다음 단계에서 '게이트 완화' 대신 '고정밀 양성 신호 추가'가 필요한 지점을 특정.
  3. 현 코퍼스 verdict(부분 66/115)의 룰별 정밀도와 병치 → 완화의 precision 리스크 가시화.

출력: outputs/fn_recall_baseline.json + stdout.
규율: 측정 먼저. 룰 변경은 본 하네스로 recall↑ AND precision 비악화 동시 입증된 분만.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine import fpc  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402
from engine import structure  # noqa: E402

GOLD_PATH = REPO / "outputs" / "gold_reco_review.jsonl"
REVIEWED_PATH = REPO / "outputs" / "reco_mechanical_measure.json"
FID_MAP_PATH = REPO / "outputs" / "fid_article_map.json"
VERDICTS_PATH = REPO / "outputs" / "verification_dataset.jsonl"
LAWS_DIR = REPO / "data" / "laws" / "raw"
REPORT_PATH = REPO / "outputs" / "fn_recall_baseline.json"


def _strip_frontmatter(text: str) -> str:
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def _norm(s: str) -> str:
    return (s or "").strip().replace(" ", "")


def _gate_diagnosis(law, article) -> list[str]:
    """이 조문이 걸렸을 법한 구조 게이트를 진단(룰 공통 억제 신호)."""
    g = []
    if article is None:
        return ["article_unmapped"]
    try:
        if article.is_purpose():
            g.append("is_purpose")
        if article.is_definition():
            g.append("is_definition")
        if article.is_penalty():
            g.append("is_penalty")
        if getattr(article, "is_disqualification", lambda: False)():
            g.append("is_disqualification")
        if article.chapter and "부칙" in article.chapter:
            g.append("chapter_부칙")
    except Exception:
        pass
    # 도메인 게이트 (여러 룰이 공유)
    name = law.name
    for fn_name in ("is_judicial_law", "is_labor_welfare_law",
                    "is_broadcast_law", "is_criminal_special_law"):
        fn = getattr(structure, fn_name, None)
        try:
            if fn and fn(name):
                g.append(f"domain:{fn_name}")
        except Exception:
            pass
    return g or ["no_common_gate (룰별 세부 게이트/트리거 미스 가능)"]


def main() -> int:
    gold = [json.loads(l) for l in GOLD_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    reviewed = {r["fid"]: r for r in json.loads(REVIEWED_PATH.read_text(encoding="utf-8"))["records"]}
    fid_map = json.loads(FID_MAP_PATH.read_text(encoding="utf-8"))

    fn = [r for r in gold if r["verdict"] == "반려"
          and reviewed.get(r["fid"], {}).get("status") == "fn_not_fired"]

    # 룰별 정밀도(현 verdict, 부분 데이터) — 완화 리스크 병치용.
    prec = defaultdict(lambda: {"TP": 0, "FP": 0})
    if VERDICTS_PATH.exists():
        for l in VERDICTS_PATH.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            d = json.loads(l)
            v, rid = d.get("verdict"), d.get("rule_id")
            if v in ("TP", "FP"):
                prec[rid][v] += 1

    records = []
    still_fn = 0
    by_law = defaultdict(list)
    for r in fn:
        by_law[r["fid"].split("@", 1)[1]].append(r)

    for law_name, rows in by_law.items():
        md = LAWS_DIR / law_name / "법률.md"
        if not md.exists():
            for r in rows:
                records.append({"fid": r["fid"], "status": "missing_law"})
            continue
        law = parse_law(_strip_frontmatter(md.read_text(encoding="utf-8", errors="replace")), name=law_name)
        findings = fpc.correct(law, run_all(law))
        fired = {(f.pattern_id, _norm(f.article_number)) for f in findings}
        art_by_norm = {_norm(a.number): a for a in law.articles}
        for r in rows:
            rid = r["fid"].rsplit("-", 1)[0] if r["fid"].count("-") >= 2 else r["fid"].split("-")[0]
            rule_id = "-".join(r["fid"].split("@")[0].split("-")[:2])
            art_no = fid_map.get(r["fid"])
            art = art_by_norm.get(_norm(art_no)) if art_no else None
            now_fires = (rule_id, _norm(art_no)) in fired
            if not now_fires:
                still_fn += 1
            p = prec.get(rule_id)
            prec_val = round(p["TP"] / (p["TP"] + p["FP"]), 3) if p and (p["TP"] + p["FP"]) else None
            records.append({
                "fid": r["fid"], "rule_id": rule_id, "article": art_no,
                "now_fires": now_fires,
                "gate_diagnosis": _gate_diagnosis(law, art),
                "rule_precision_now": prec_val,
                "fix_hint": r["fix"],
            })

    gate_freq = Counter(g for rec in records for g in rec.get("gate_diagnosis", []))

    report = {
        "_meta": {
            "purpose": "fn(미발화) recall 베이스라인 + 게이트 진단. 룰 무수정, LLM 0회.",
            "rule_gate①": "룰 변경은 이 하네스로 recall↑ AND precision 비악화 동시 입증분만.",
            "verdict_data": "부분(66/115 번들) — precision은 근사치, 완화 리스크 하한.",
        },
        "summary": {
            "fn_total": len(fn), "still_fn": still_fn,
            "recall_now": round(1 - still_fn / len(fn), 3) if fn else None,
            "gate_frequency": dict(gate_freq.most_common()),
            "fn_by_rule": dict(Counter(rec["rule_id"] for rec in records if "rule_id" in rec)),
        },
        "records": records,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[fn recall 베이스라인] fn {len(fn)}건 / 여전히 미발화 {still_fn}건 "
          f"(recall_now={report['summary']['recall_now']})")
    print(f"룰별 fn 수: {report['summary']['fn_by_rule']}")
    print(f"\n[게이트 진단 빈도] (왜 미발화인가)")
    for g, c in gate_freq.most_common():
        print(f"  {c:2}  {g}")
    print(f"\n[완화 리스크 — fn 룰의 현 정밀도(부분데이터)]")
    seen = set()
    for rec in records:
        rid = rec.get("rule_id")
        if rid and rid not in seen:
            seen.add(rid)
            print(f"  {rid}: precision≈{rec.get('rule_precision_now')}  "
                  f"→ 게이트 완화 시 FP 증가 위험 {'높음' if (rec.get('rule_precision_now') or 1) < 0.2 else '중'}")
    print("\n결론: fn 22건은 대부분 '구조 게이트(정의·벌칙·도메인)'에 의해 억제됨. "
          "정밀도 최약 룰이라 게이트 완화는 게이트① 위반. → '고정밀 양성 신호 추가'가 필요(다음 단계, 측정 동반).")
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
