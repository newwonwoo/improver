#!/usr/bin/env python3
"""LLM(GPT/Gemini) JSON 응답을 엔진 분석 결과에 다시 반영.

워크플로:
    1) python scripts/analyze.py <law.md> --output result.json --judgment-md prompt.md
    2) prompt.md 내용을 LLM(GPT/Gemini)에 입력 → JSON 응답 받음
    3) 응답을 response.json으로 저장
    4) python scripts/import_judgment.py result.json --llm-response response.json \\
           --output result_with_llm.json [--html report.html]

처리:
    - judgments[].verdict가 FP면 is_false_positive=True + severity="양호"
    - adjusted_severity 변경 시 등급/점수 갱신
    - improved_recommendation → recommendation.contextual + layer=3
    - reference → recommendation.reference_note
    - missed_findings → 새 Finding 추가 (detection_method="llm")
    - checklist, overall_assessment 결과 객체에 메타로 부착
    - 최종 점수 재계산 (scorer.compute)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import html_report, scorer  # noqa: E402
from engine.schema import (  # noqa: E402
    AnalysisResult,
    Article,
    ArticleScore,
    CategoryScore,
    Finding,
    Law,
    Paragraph,
)
from engine.severity import SEVERITY_ORDER, score_of  # noqa: E402


def _law_from_dict(data: dict) -> Law:
    articles = [
        Article(
            article_id=a["article_id"],
            number=a["number"],
            number_raw=a["number_raw"],
            is_inserted=a.get("is_inserted", False),
            insert_depth=a.get("insert_depth", 0),
            title=a.get("title"),
            full_text=a.get("full_text", ""),
            paragraphs=[],
            chapter=a.get("chapter"),
        )
        for a in data.get("articles", [])
    ]
    return Law(
        law_id=data["law_id"],
        name=data["name"],
        short_name=data.get("short_name"),
        type=data.get("type", "법률"),
        law_category=data.get("law_category", "일반"),
        enacted_date=data.get("enacted_date"),
        last_amended_date=data.get("last_amended_date"),
        effective_date=data.get("effective_date"),
        articles=articles,
    )


def _finding_from_dict(d: dict) -> Finding:
    return Finding(
        finding_id=d["finding_id"],
        pattern_id=d["pattern_id"],
        pattern_name=d["pattern_name"],
        category=d["category"],
        article_id=d["article_id"],
        article_number=d["article_number"],
        matched_text=d.get("matched_text", ""),
        severity=d["severity"],
        severity_score=d["severity_score"],
        summary=d.get("summary", ""),
        detection_method=d.get("detection_method", "rule"),
        fix_type=d.get("fix_type"),
        recommendation=d.get("recommendation") or {},
        is_false_positive=d.get("is_false_positive", False),
        false_positive_reason=d.get("false_positive_reason"),
    )


def _result_from_dict(data: dict) -> AnalysisResult:
    law = _law_from_dict(data["law"])
    findings = [_finding_from_dict(f) for f in data["findings"]]
    return AnalysisResult(
        law=law,
        findings=findings,
        article_scores=[],
        category_scores={},
        law_score=0.0,
        law_grade="A",
        engine_version=data.get("engine_version", "0.1.0"),
    )


def _apply_judgments(result: AnalysisResult, judgments: list[dict]) -> dict:
    """LLM 판정을 finding에 적용. 통계 반환."""
    by_id = {f.finding_id: f for f in result.findings}
    stats = {"applied": 0, "fp_marked": 0, "severity_changed": 0, "missing_ids": []}
    for j in judgments:
        fid = j.get("finding_id")
        f = by_id.get(fid)
        if f is None:
            stats["missing_ids"].append(fid)
            continue
        verdict = j.get("verdict")
        new_sev = j.get("adjusted_severity")

        if verdict == "FP":
            f.is_false_positive = True
            f.false_positive_reason = j.get("reasoning") or "LLM 오탐 판정"
            f.severity = "양호"
            f.severity_score = 0
            f.detection_method = "rule+llm"
            stats["fp_marked"] += 1
        elif verdict in {"TP", "BORDER"} and new_sev in SEVERITY_ORDER:
            if new_sev != f.severity:
                # 2단계+ 변경은 reasoning 있어야 적용
                delta = abs(SEVERITY_ORDER.index(new_sev) - SEVERITY_ORDER.index(f.severity))
                if delta >= 2 and not (j.get("reasoning") or "").strip():
                    continue  # 사유 없으면 보존
                f.severity = new_sev
                f.severity_score = score_of(new_sev)
                stats["severity_changed"] += 1
            f.detection_method = "rule+llm"

        # 권고 보강
        rec = dict(f.recommendation or {})
        if j.get("improved_recommendation"):
            rec["contextual"] = j["improved_recommendation"]
            rec["layer"] = 3
        if j.get("reference"):
            rec["reference_note"] = j["reference"]
        if j.get("reasoning"):
            rec["llm_reasoning"] = j["reasoning"]
        rec["verdict"] = verdict
        f.recommendation = rec
        stats["applied"] += 1
    return stats


def _add_missed_findings(result: AnalysisResult, missed: list[dict]) -> int:
    """LLM이 발견한 미탐을 새 Finding으로 추가."""
    if not missed:
        return 0
    category_map = {"S": "구조", "F": "공정성", "L": "적법성", "G": "거버넌스", "E": "효율성"}
    by_number = {a.number: a.article_id for a in result.law.articles}
    added = 0
    for i, m in enumerate(missed):
        article_num = m.get("article_number", "법령 전체")
        article_id = by_number.get(article_num, "law_level")
        pattern_id = m.get("pattern_id", "X-NEW")
        prefix = pattern_id[0] if pattern_id and pattern_id[0] in category_map else "S"
        severity = m.get("severity", "주의")
        if severity not in SEVERITY_ORDER:
            severity = "주의"
        rec = {"layer": 3, "contextual": m.get("recommendation", "")}
        if m.get("reference"):
            rec["reference_note"] = m["reference"]
        result.findings.append(Finding(
            finding_id=f"LLM-MISS-{i:03d}",
            pattern_id=pattern_id,
            pattern_name=m.get("name") or pattern_id,
            category=category_map.get(prefix, "구조"),
            article_id=article_id,
            article_number=article_num,
            matched_text="LLM 미탐 식별",
            severity=severity,
            severity_score=score_of(severity),
            summary=m.get("summary", ""),
            detection_method="llm",
            recommendation=rec,
        ))
        added += 1
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM JSON 응답을 엔진 결과에 import")
    parser.add_argument("analysis", help="엔진 분석 결과 JSON (analyze.py --output)")
    parser.add_argument("--llm-response", required=True,
                        help="LLM이 반환한 JSON 응답 파일")
    parser.add_argument("--output", default="-", help="갱신된 결과 출력 경로")
    parser.add_argument("--html", default=None, help="HTML 리포트 동시 출력 (선택)")
    args = parser.parse_args(argv)

    analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    llm = json.loads(Path(args.llm_response).read_text(encoding="utf-8"))
    result = _result_from_dict(analysis)

    judgments = llm.get("judgments", [])
    missed = llm.get("missed_findings", [])
    checklist = llm.get("checklist", [])
    overall = llm.get("overall_assessment", {})

    stats = _apply_judgments(result, judgments)
    added = _add_missed_findings(result, missed)

    # 점수 재계산
    result = scorer.compute(result.law, result.findings)

    payload = result.to_dict()
    payload["llm_review"] = {
        "judgments_applied": stats["applied"],
        "fp_marked": stats["fp_marked"],
        "severity_changed": stats["severity_changed"],
        "missing_finding_ids": stats["missing_ids"],
        "missed_findings_added": added,
        "checklist": checklist,
        "overall_assessment": overall,
    }
    out_json = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output == "-":
        sys.stdout.write(out_json + "\n")
    else:
        Path(args.output).write_text(out_json, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    if args.html:
        Path(args.html).write_text(html_report.render(result), encoding="utf-8")
        print(f"Wrote {args.html}", file=sys.stderr)
    print(
        f"Import 완료 — applied={stats['applied']} fp={stats['fp_marked']} "
        f"sev_changed={stats['severity_changed']} missed_added={added}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
