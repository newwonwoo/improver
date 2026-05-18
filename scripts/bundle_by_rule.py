#!/usr/bin/env python3
"""룰별 finding 번들 — 엔진 강화용.

설계 배경 (법령별 번들과의 차이):

법령별(bundle_judgments.py): 한 법령 안의 모든 룰 finding을 모아서
LLM에게 "이 법령의 결함 판정해줘" 라고 묻는 방식. 신호가 흩어진다 —
같은 룰의 FP 패턴이 1,704개 법령에 분산되어, 패턴 추출 어려움.

룰별(이 파일): 한 룰의 모든 finding을 1,704 법령에서 끌어모아
LLM에게 "이 룰의 FP/TP 공통 패턴 뽑아줘" 라고 묻는 방식. 신호 집중 —
한 호출로 한 룰의 negative filter / positive boost / precision 추정.

각 룰 = 한 번들 (총 ~21개, X-CROSS/X-PATTERN 제외).
finding 많은 룰(>1,000건)은 severity stratified sample 1,000건.

워크플로:
    1. python scripts/bundle_by_rule.py --output-dir outputs/rule_bundles
       (--sample-size 1000 기본)
    2. 사용자가 각 번들을 LLM에 하나씩 입력 (Gemini Pro 2 무료 quota 권장)
    3. 응답을 outputs/rule_responses/<rule_id>.json 으로 저장
    4. (다음 단계) scripts/apply_rule_proposals.py 로 룰 설정 보강
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

# 메타 패턴 — 룰 자체가 아니라 다른 finding 위에 만들어지는 파생이므로 제외
_META_PATTERNS = {"X-CROSS", "X-PATTERN"}

# severity 표시 순서 (LLM이 위로 갈수록 심각한 케이스를 먼저 보도록)
_SEVERITY_ORDER = ["심각", "경고", "주의", "개선", "양호"]


_RULE_BUNDLE_PROMPT = """\
당신은 한국 법제 전문가이자 룰 엔진 튜너입니다.

규정개선 분석 엔진의 룰 `{rule_id}` ({rule_name}) 이 1,704개 한국 법령에서
잡은 후보 finding 목록을 검토하여, 이 룰을 강화할 패턴을 추출하세요.

[작업 — 한 응답으로 모두]
1. **FP 공통 패턴 (3~5개)** — 어떤 조건이면 거의 확실히 FP(과탐)인지
2. **TP 강한 신호 (2~3개)** — 어떤 조건이면 거의 확실히 TP(진성결함)인지
3. **룰 자체 평가** — precision 추정 / recall 우려 / 우선순위

[FP 판정 기준 — 다음 중 하나면 거의 FP]
- 용어정의 조문에서 잡힌 모호표현/위임/포괄어 (FPC-02)
- 벌칙 조문에서 잡힌 권리제한 (FPC-04)
- 절차법의 제재공백 (FPC-03)
- 정책의무(노력하여야/진흥/촉진/육성)에 대한 제재공백
- 룰 키워드가 다른 의미로 사용된 경우 (지위의제, 사실추정 등)
- 협조요청·수익적 재량 (침익적이 아님)
- 위임이지만 시행령에 이미 구체화된 경우 (S-02 한정)

[negative_filter_hint 작성]
- 룰 엔진에 추가할 negative 조건을 구체적으로:
  · "조문 제목에 '정의'/'벌칙' 포함" 같은 article-level 조건
  · "matched_text 가 '~할 수 있다' 만 포함하고 침익조 아님" 같은 텍스트 조건
  · "summary 가 '포괄위임 N건' 인데 시행령에 매핑 후보 ≥1" 같은 메타 조건
- 가능하면 정규식, 키워드 리스트, boolean 식으로 표기

[positive_boost 작성]
- 가중치 제안 (예: +1, +2점)
- 어떤 조건이면 boost 적용할지 명시

[출력 — 반드시 아래 JSON 형식 단독 응답]
{{
  "rule_id": "{rule_id}",
  "fp_patterns": [
    {{
      "name": "<패턴명 한 줄>",
      "negative_filter_hint": "<negative 조건 — 구체적, 코드화 가능한 형태>",
      "example_finding_ids": ["<예시 finding_id 3~5개>"],
      "estimated_fp_share_pct": <0~100 정수>,
      "rationale": "<근거 1~2문장>"
    }}
  ],
  "tp_patterns": [
    {{
      "name": "<패턴명>",
      "positive_boost_hint": "<+N점 또는 우선 처리>",
      "example_finding_ids": ["<예시 3~5개>"],
      "rationale": "<근거 1~2문장>"
    }}
  ],
  "rule_evaluation": {{
    "estimated_precision_pct": <0~100 정수>,
    "recall_concerns": "<놓칠 만한 유형 — 한 문단>",
    "priority": "high|medium|low",
    "comment": "<룰 강화 ROI 한 문장>"
  }}
}}

**위 JSON만 출력하세요. 마크다운 코드블록, 설명문, 인사말 모두 금지.**
"""


def _load_all_findings() -> dict[str, list[dict]]:
    """모든 result JSON을 읽어 rule_id별 finding 리스트로 그룹화."""
    by_rule: dict[str, list[dict]] = defaultdict(list)
    results_dir = Path("outputs/results")
    for fp in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        law_name = data.get("law", {}).get("name") or fp.stem
        law_category = data.get("law", {}).get("category", "")
        for f in data.get("findings", []):
            pid = f.get("pattern_id")
            if not pid or pid in _META_PATTERNS:
                continue
            # law 컨텍스트를 finding에 주입 (번들 출력용)
            f["_law_name"] = law_name
            f["_law_category"] = law_category
            by_rule[pid].append(f)
    return by_rule


def _stratified_sample(findings: list[dict], target_size: int, seed: int) -> list[dict]:
    """severity별 비례 샘플링. target_size 이하면 전부 반환."""
    if len(findings) <= target_size:
        return findings
    rng = random.Random(seed)
    by_sev: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_sev[f.get("severity", "기타")].append(f)
    total = len(findings)
    out: list[dict] = []
    for sev in _SEVERITY_ORDER + sorted(set(by_sev) - set(_SEVERITY_ORDER)):
        bucket = by_sev.get(sev, [])
        if not bucket:
            continue
        n = max(1, round(target_size * len(bucket) / total))
        out.extend(rng.sample(bucket, min(n, len(bucket))))
    # 정렬: severity 순 → 법령명 순
    sev_rank = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
    out.sort(key=lambda f: (sev_rank.get(f.get("severity"), 99), f.get("_law_name", "")))
    return out[:target_size]


def _format_finding_line(f: dict) -> str:
    """finding 한 줄 압축. ~250bytes."""
    fid = f.get("finding_id", "?")
    law = f.get("_law_name", "?")
    cat = f.get("_law_category", "")
    art = f.get("article_number", "?")
    sev = f.get("severity", "?")
    matched = (f.get("matched_text") or "").replace("\n", " ").strip()
    if len(matched) > 80:
        matched = matched[:77] + "..."
    summary = (f.get("summary") or "").replace("\n", " ").strip()
    if len(summary) > 100:
        summary = summary[:97] + "..."
    cat_tag = f"({cat})" if cat else ""
    return f"- `{fid}` [{sev}] 「{law}」{cat_tag} {art} | 매칭=「{matched}」 | {summary}"


def _bundle_for_rule(
    rule_id: str,
    findings: list[dict],
    sample_size: int,
    seed: int,
) -> tuple[str, dict]:
    """한 룰의 번들 .md 본문 + 메타 dict 반환."""
    total = len(findings)
    rule_name = next((f.get("pattern_name") for f in findings if f.get("pattern_name")), rule_id)
    sampled = _stratified_sample(findings, sample_size, seed=seed)

    # severity 분포 (전체 vs 샘플)
    def _dist(items: list[dict]) -> dict[str, int]:
        d: dict[str, int] = defaultdict(int)
        for f in items:
            d[f.get("severity", "기타")] += 1
        return dict(d)

    full_dist = _dist(findings)
    sample_dist = _dist(sampled)

    # 카테고리(법령 카테고리) 분포 상위 10
    cat_counter: dict[str, int] = defaultdict(int)
    for f in findings:
        cat = f.get("_law_category") or "(미분류)"
        cat_counter[cat] += 1
    top_cats = sorted(cat_counter.items(), key=lambda x: -x[1])[:10]

    header = f"""# 📦 룰 강화용 번들 — `{rule_id}` ({rule_name})

> **이 룰의 전체 finding**: {total:,}건 (1,704개 법령 누적)
> **이 번들에 포함된 샘플**: {len(sampled):,}건 (severity stratified)
>
> **사용 방법**:
> 1. 아래 "🤖 LLM 시스템 프롬프트" 블록을 LLM 시스템 프롬프트로 설정
> 2. 그 아래 "📋 finding 목록" 전체를 user 메시지로 입력
> 3. JSON 응답을 `outputs/rule_responses/{rule_id}.json` 으로 저장
>
> **권장 LLM**: Gemini Pro 2 (1M 토큰, 무료 quota 안) 또는 Claude Pro

---

## 📊 분포 요약

### Severity 분포 (전체 / 샘플)

| Severity | 전체 | 샘플 |
|----------|------|------|
"""
    for sev in _SEVERITY_ORDER:
        if sev in full_dist or sev in sample_dist:
            header += f"| {sev} | {full_dist.get(sev, 0):,} | {sample_dist.get(sev, 0):,} |\n"

    header += "\n### 법령 카테고리 상위 10\n\n| 카테고리 | 건수 |\n|---------|------|\n"
    for cat, cnt in top_cats:
        header += f"| {cat} | {cnt:,} |\n"

    header += f"""
---

## 🤖 LLM 시스템 프롬프트

```
{_RULE_BUNDLE_PROMPT.format(rule_id=rule_id, rule_name=rule_name)}
```

---

## 📋 finding 목록 — {len(sampled):,}건

> 포맷: `finding_id` [severity] 「법령명」(법령카테고리) 조문 | 매칭="매칭텍스트" | 요약

"""
    body_lines = [_format_finding_line(f) for f in sampled]
    content = header + "\n".join(body_lines) + "\n"

    meta = {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "total_findings": total,
        "sample_size": len(sampled),
        "severity_dist_full": full_dist,
        "severity_dist_sample": sample_dist,
        "top_law_categories": dict(top_cats),
    }
    return content, meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="룰별 finding을 모아 LLM 강화 분석용 번들 생성"
    )
    parser.add_argument("--output-dir", default="outputs/rule_bundles")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=1000,
        help="룰당 최대 finding 수 (이 이상은 severity stratified 샘플링). 기본 1000.",
    )
    parser.add_argument(
        "--min-findings",
        type=int,
        default=10,
        help="이 미만의 finding을 가진 룰은 건너뛰기 (분석 신뢰도 낮음). 기본 10.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--only",
        nargs="*",
        help="특정 rule_id만 생성 (예: --only S-02 G-02)",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("results JSON 스캔 중...", file=sys.stderr)
    by_rule = _load_all_findings()
    print(
        f"발견된 룰: {len(by_rule)}개 / 총 finding: {sum(len(v) for v in by_rule.values()):,}건",
        file=sys.stderr,
    )

    rules_sorted = sorted(by_rule.items(), key=lambda kv: -len(kv[1]))

    index_entries: list[dict] = []
    written = 0
    skipped: list[str] = []
    for rule_id, findings in rules_sorted:
        if args.only and rule_id not in args.only:
            continue
        if len(findings) < args.min_findings:
            skipped.append(f"{rule_id} ({len(findings)}건)")
            continue
        content, meta = _bundle_for_rule(
            rule_id, findings, sample_size=args.sample_size, seed=args.seed
        )
        out_path = output_dir / f"{rule_id}.md"
        out_path.write_text(content, encoding="utf-8")
        size_kb = out_path.stat().st_size / 1024
        meta["bundle_file"] = out_path.name
        meta["bundle_size_kb"] = round(size_kb, 1)
        index_entries.append(meta)
        written += 1
        print(
            f"  {rule_id:<10} 전체 {meta['total_findings']:>6,}건 → "
            f"샘플 {meta['sample_size']:>5,}건 / {size_kb:>6.1f}KB → {out_path.name}",
            file=sys.stderr,
        )

    # 인덱스 작성
    index_path = output_dir / "_index.json"
    index_path.write_text(
        json.dumps(
            {
                "generated_by": "scripts/bundle_by_rule.py",
                "sample_size_limit": args.sample_size,
                "min_findings_filter": args.min_findings,
                "seed": args.seed,
                "bundles": index_entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n총 {written}개 룰 번들 생성. 인덱스: {index_path}", file=sys.stderr)
    if skipped:
        print(f"건너뛴 룰 ({len(skipped)}, --min-findings={args.min_findings} 미만): "
              f"{', '.join(skipped)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
