#!/usr/bin/env python3
"""LLM 룰별 응답을 모아 통합 보고서 생성.

워크플로:
    1. scripts/bundle_by_rule.py 로 룰별 번들 생성
    2. 사용자가 각 번들을 LLM에 입력 → JSON 응답을 받음
    3. 응답을 outputs/rule_responses/<rule_id>.json 으로 저장
    4. 이 스크립트 실행 → 응답 검증 + 통합 보고서 생성

생성물:
    outputs/rule_enhancement_report.md  — 사람용 읽기 보고서
    outputs/rule_enhancement_report.json — 다음 단계(룰 코드 패치)용 구조화 데이터

다음 단계 (이 스크립트 이후):
    각 룰의 negative_filter_hint / positive_boost_hint 를 engine/rules/<rule>.py
    또는 engine/fpc.py 에 반영. 자동 패치는 휴리스틱이라 미구현 — 사람이
    보고서 보고 PR.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_TOP_KEYS = {"rule_id", "fp_patterns", "tp_patterns", "rule_evaluation"}


def _strip_codeblock(text: str) -> str:
    """LLM이 ```json ... ``` 으로 감싼 응답 정리."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _validate(rule_id: str, data: dict) -> list[str]:
    """응답 스키마 검증 — 오류 메시지 리스트 반환 (빈 리스트면 OK)."""
    errors: list[str] = []
    if data.get("rule_id") != rule_id:
        errors.append(f"rule_id 불일치: 파일명={rule_id} vs 응답={data.get('rule_id')!r}")
    for key in _TOP_KEYS:
        if key not in data:
            errors.append(f"필수 키 누락: {key}")
    for key in ("fp_patterns", "tp_patterns"):
        items = data.get(key)
        if items is not None and not isinstance(items, list):
            errors.append(f"{key} 는 리스트여야 함, got {type(items).__name__}")
    eval_block = data.get("rule_evaluation")
    if eval_block is not None and not isinstance(eval_block, dict):
        errors.append("rule_evaluation 은 객체여야 함")
    return errors


def _format_md(responses: dict[str, dict], missing: list[str]) -> str:
    """사람용 보고서 작성."""
    lines: list[str] = [
        "# 🔧 룰 강화 통합 보고서",
        "",
        f"> 응답 수신: **{len(responses)}개 룰** / 누락: **{len(missing)}개**",
        "",
    ]
    if missing:
        lines.append(f"**응답 미수신 룰**: {', '.join(missing)}")
        lines.append("")

    # 우선순위 테이블
    rows: list[tuple[str, str, int, int, int, str]] = []
    for rid, d in responses.items():
        ev = d.get("rule_evaluation") or {}
        rows.append((
            rid,
            ev.get("priority", "?"),
            int(ev.get("estimated_precision_pct", 0) or 0),
            len(d.get("fp_patterns") or []),
            len(d.get("tp_patterns") or []),
            (ev.get("comment") or "").replace("|", "\\|").replace("\n", " "),
        ))
    # priority high → low, 같으면 precision 낮은 순(과탐 심한 거 위로)
    pri_rank = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (pri_rank.get(r[1], 9), r[2]))

    lines += [
        "## 📊 룰별 강화 우선순위",
        "",
        "| 룰 | 우선순위 | precision% | FP패턴 | TP패턴 | 코멘트 |",
        "|----|----------|-----------:|-------:|-------:|--------|",
    ]
    for rid, pri, prec, nfp, ntp, com in rows:
        lines.append(f"| `{rid}` | {pri} | {prec} | {nfp} | {ntp} | {com} |")
    lines.append("")

    # 룰별 상세
    lines += ["---", "", "## 📝 룰별 상세", ""]
    for rid, d in responses.items():
        ev = d.get("rule_evaluation") or {}
        lines += [
            f"### `{rid}`",
            "",
            f"- **우선순위**: {ev.get('priority', '?')}",
            f"- **추정 precision**: {ev.get('estimated_precision_pct', '?')}%",
            f"- **recall 우려**: {ev.get('recall_concerns', '_없음_')}",
            f"- **코멘트**: {ev.get('comment', '_없음_')}",
            "",
            "#### FP 공통 패턴",
            "",
        ]
        for i, p in enumerate(d.get("fp_patterns") or [], 1):
            examples = ", ".join(f"`{e}`" for e in (p.get("example_finding_ids") or [])[:5])
            lines += [
                f"{i}. **{p.get('name', '?')}** (추정 FP share: {p.get('estimated_fp_share_pct', '?')}%)",
                f"   - negative_filter_hint: `{p.get('negative_filter_hint', '?')}`",
                f"   - rationale: {p.get('rationale', '?')}",
                f"   - 예: {examples}",
                "",
            ]
        lines += ["#### TP 강한 신호", ""]
        for i, p in enumerate(d.get("tp_patterns") or [], 1):
            examples = ", ".join(f"`{e}`" for e in (p.get("example_finding_ids") or [])[:5])
            lines += [
                f"{i}. **{p.get('name', '?')}**",
                f"   - boost_hint: `{p.get('positive_boost_hint', '?')}`",
                f"   - rationale: {p.get('rationale', '?')}",
                f"   - 예: {examples}",
                "",
            ]
        lines += ["---", ""]

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 룰별 응답 검증 + 통합 보고서")
    parser.add_argument("--responses-dir", default="outputs/rule_responses")
    parser.add_argument("--bundles-dir", default="outputs/rule_bundles")
    parser.add_argument("--report-md", default="outputs/rule_enhancement_report.md")
    parser.add_argument("--report-json", default="outputs/rule_enhancement_report.json")
    args = parser.parse_args(argv)

    bundles_dir = Path(args.bundles_dir)
    responses_dir = Path(args.responses_dir)
    responses_dir.mkdir(parents=True, exist_ok=True)

    index_path = bundles_dir / "_index.json"
    if not index_path.exists():
        print(f"번들 인덱스 없음: {index_path}. 먼저 bundle_by_rule.py 실행.",
              file=sys.stderr)
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected = [b["rule_id"] for b in index["bundles"]]

    responses: dict[str, dict] = {}
    missing: list[str] = []
    errors: dict[str, list[str]] = {}
    for rid in expected:
        fp = responses_dir / f"{rid}.json"
        if not fp.exists():
            missing.append(rid)
            continue
        try:
            text = fp.read_text(encoding="utf-8")
            data = json.loads(_strip_codeblock(text))
        except json.JSONDecodeError as exc:
            errors[rid] = [f"JSON 파싱 실패: {exc}"]
            continue
        validation = _validate(rid, data)
        if validation:
            errors[rid] = validation
            # 그래도 부분 데이터는 보고서에 포함
        responses[rid] = data

    if errors:
        print("⚠ 검증 오류:", file=sys.stderr)
        for rid, errs in errors.items():
            print(f"  {rid}: {'; '.join(errs)}", file=sys.stderr)

    report_md = _format_md(responses, missing)
    Path(args.report_md).write_text(report_md, encoding="utf-8")

    Path(args.report_json).write_text(
        json.dumps(
            {
                "responses": responses,
                "missing": missing,
                "validation_errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"\n응답 {len(responses)}/{len(expected)} 처리. "
        f"보고서: {args.report_md} / {args.report_json}",
        file=sys.stderr,
    )
    if missing:
        print(f"누락 룰: {', '.join(missing)}", file=sys.stderr)
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
