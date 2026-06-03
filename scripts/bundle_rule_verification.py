#!/usr/bin/env python3
"""Stage A — 룰 검증 sub-bundle 생성 (콘텐츠 포함, ChatGPT Plus 타깃).

docs/design/engine_reinforcement_strategy.md 의 4-Stage 청사진 중 A단계.

설계 요점:
- 룰별로 finding을 stratified sample (severity 비례) → 룰당 ~300건 (기본)
- 같은 (법령, 조문) finding은 모아서 — 조문 본문 한 번만 출력 (토큰 절약)
- 50건 단위 sub-bundle (입력 ~60KB / 응답 ~10KB → Plus 한 호출 안에 들어옴)
- 시행령 매핑 본문 포함 (S-02 등 위임 룰의 핵심 신호)
- 응답 스키마: verdicts(짧음) + new_signals(풍부) + missed_patterns

워크플로:
    1. python scripts/bundle_rule_verification.py
       → outputs/rule_verification/<rule_id>_partNN.md (~150개 sub-bundle)
    2. 사용자가 sub-bundle 하나씩 ChatGPT Plus 에 복붙
       → 응답을 outputs/rule_verification_responses/<bundle_id>.json 으로 저장
    3. python scripts/import_rule_verification.py
       → outputs/verification_dataset.jsonl (Stage B 입력)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.parser import parse_law  # noqa: E402

_META_PATTERNS = {"X-CROSS", "X-PATTERN"}
_SEVERITY_ORDER = ["심각", "경고", "주의", "개선", "양호"]
_DELEG_KEYS = re.compile(r"(대통령령|시행령|총리령|부령|시행규칙|고시)")
_ARTICLE_BODY_MAX = 1500  # 조문 본문 최대 글자수 (긴 조문은 클립)
_DECREE_BODY_MAX = 1200


_SYSTEM_PROMPT = """\
당신은 한국 법제 전문가입니다. 법제처 입안길잡이, 감사원 내부통제 가이드라인,
공정위 약관규제법 사례, 권익위 규제개혁, 금감원 검사제재 기준에 정통합니다.

규정개선 분석 엔진이 룰 `{rule_id}` ({rule_name}) 로 1차 매칭한 후보 finding들을
**조문 본문 콘텐츠 보고** 검증해야 합니다. 단순 키워드가 아니라 의미·맥락으로 판정하세요.

[작업 — 한 응답으로 모두]
1. 각 finding의 **TP/FP/BORDER** 판정 + 짧은 근거 인용
2. **새 신호 (new_signals)** — 키워드로는 못 잡지만 콘텐츠에서 보이는 패턴.
   코드로 옮길 수 있는 표현(정규식, 구조 조건, 교차 신호)으로 적으세요.
3. **놓친 패턴 (missed_patterns)** — 룰이 잡지 못했지만 본문에서 발견된 결함 유형

[판정 기준]
- TP: 룰 매칭 + 법제처/감사원/공정위/권익위/금감원 기준에서 명확히 결함
- FP: 다음 중 하나
  · 용어정의 조문에서 잡힌 모호표현/위임/포괄어 (다른 법 인용일 가능성)
  · 벌칙 조문에서 잡힌 권리제한
  · 절차법의 제재공백
  · 정책의무(노력하여야/진흥/촉진/육성)에 대한 제재공백
  · 룰 키워드가 다른 의미로 사용 (지위의제, 사실추정 등)
  · 협조요청·수익적 재량 (침익적 아님)
  · 위임이지만 시행령에 이미 구체화 (S-02 한정)
- BORDER: 추가 자료 없으면 판정 보류

[새 신호 작성 — 가장 중요]
이 단계의 가치는 verdict가 아니라 **새 신호 발견**에 있습니다.
- 룰 엔진이 키워드만 봐서 놓치는 신호를 콘텐츠에서 찾아 코드 표현으로 적기
- 예: "조문 제목에 '정의' 포함 AND 앞 절에 '~란.*말한다' 패턴" → FP 필터
- 예: "위임 키워드 + 시행령 ±3조에 구체 호 ≥3개" → FP 다운그레이드
- 예: "처분조 + 재량 키워드 + 사전통지 부재" → TP 부스트
- 정규식 / boolean 조건 / score 임계로 표현 가능해야 함

[출력 — 반드시 아래 JSON 형식 단독 응답. 마크다운 코드블록·인사말·설명 금지.]
{{
  "bundle_id": "{bundle_id}",
  "rule_id": "{rule_id}",
  "verdicts": [
    {{"fid": "<finding_id>@<법령명>", "v": "TP|FP|BORDER", "ev": "조문 인용 ≤30자"}}
  ],
  "new_signals": [
    {{
      "name": "<신호명 한 줄>",
      "logic": "<코드화 가능한 표현 — 정규식/조건/교차신호>",
      "effect": "TP_BOOST|FP_FILTER|NEW_RULE",
      "examples": ["<fid 3~5개>"],
      "rationale": "<근거 1~2문장>"
    }}
  ],
  "missed_patterns": [
    {{
      "name": "<패턴명>",
      "logic": "<탐지 로직>",
      "examples": ["「법령」 §X"]
    }}
  ]
}}
"""


def _stratified_sample(
    findings: list[dict], target_size: int, seed: int
) -> list[dict]:
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
    return out[:target_size]


def _global_fid(f: dict) -> str:
    return f"{f['finding_id']}@{f['_law_name']}"


def _load_decree(law_name: str, cache: dict) -> object | None:
    """data/laws/raw/<law>/시행령.md → Law 객체. 없으면 None."""
    if law_name in cache:
        return cache[law_name]
    decree_path = Path("data/laws/raw") / law_name / "시행령.md"
    if not decree_path.exists():
        cache[law_name] = None
        return None
    try:
        text = decree_path.read_text(encoding="utf-8")
        decree = parse_law(text, name=f"{law_name} 시행령")
    except Exception:
        cache[law_name] = None
        return None
    cache[law_name] = decree
    return decree


def _decree_matches(article_full_text: str, number_raw: str, decree) -> list:
    """본법 조문 번호 ±3 휴리스틱으로 시행령 매핑 후보 반환."""
    if decree is None or not _DELEG_KEYS.search(article_full_text):
        return []
    try:
        base = int(number_raw)
    except (ValueError, TypeError):
        return []
    matches = []
    for darticle in decree.articles:
        try:
            d_num = int(darticle.number_raw)
        except (ValueError, TypeError):
            continue
        if abs(d_num - base) <= 3:
            matches.append(darticle)
    return matches[:3]  # 최대 3건


def _clip(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_entry(
    law_name: str,
    law_category: str,
    article: dict,
    findings: list[dict],
    decree_cache: dict,
) -> str:
    """한 (법령, 조문) entry — 조문 본문 + 그 조문의 finding 목록 + 시행령 매핑."""
    art_num = article.get("number", "?")
    art_title = article.get("title") or ""
    full_text = _clip(article.get("full_text") or "", _ARTICLE_BODY_MAX)
    cat_tag = f" ({law_category})" if law_category else ""

    lines = [
        f"### 「{law_name}」{cat_tag} {art_num}"
        + (f" — {art_title}" if art_title else ""),
        "",
        "```",
        full_text,
        "```",
        "",
        f"**이 조문에서 잡힌 finding ({len(findings)}건)**:",
    ]
    for f in findings:
        fid = _global_fid(f)
        sev = f.get("severity", "?")
        matched = (f.get("matched_text") or "").replace("\n", " ").strip()
        if len(matched) > 80:
            matched = matched[:77] + "..."
        summary = (f.get("summary") or "").replace("\n", " ").strip()
        if len(summary) > 100:
            summary = summary[:97] + "..."
        lines.append(
            f"- `{fid}` [{sev}] 매칭=「{matched}」 | {summary}"
        )

    # 시행령 매핑 (위임 키워드 있을 때만)
    decree = _load_decree(law_name, decree_cache)
    matches = _decree_matches(
        article.get("full_text") or "", article.get("number_raw") or "", decree
    )
    if matches:
        lines += ["", f"**시행령 매핑 후보 ({len(matches)}건, ±3조)**:"]
        for da in matches:
            d_title = f" ({da.title})" if da.title else ""
            d_body = _clip(da.full_text, _DECREE_BODY_MAX)
            lines += [
                f"<details><summary>시행령 {da.number}{d_title}</summary>",
                "",
                "```",
                d_body,
                "```",
                "</details>",
            ]
    lines.append("")
    return "\n".join(lines)


def _bundle_header(
    bundle_id: str, rule_id: str, rule_name: str, part: int, total_parts: int,
    finding_count: int, entry_count: int,
) -> str:
    return f"""# 📦 Stage A 검증 번들 — `{rule_id}` part {part}/{total_parts}

> **번들 ID**: `{bundle_id}`
> **포함된 finding**: {finding_count}건 ({entry_count}개 조문에 분포)
> **룰**: `{rule_id}` ({rule_name})
>
> **사용 방법** (ChatGPT Plus):
> 1. 아래 "🤖 시스템 프롬프트" 블록부터 끝까지 전체 복사
> 2. ChatGPT Plus(GPT-4o) 새 대화에 붙여넣고 전송
> 3. 응답 JSON을 `outputs/rule_verification_responses/{bundle_id}.json` 으로 저장
> 4. 모든 sub-bundle 처리 후 `scripts/import_rule_verification.py` 실행

---

## 🤖 시스템 프롬프트

```
{_SYSTEM_PROMPT.format(rule_id=rule_id, rule_name=rule_name, bundle_id=bundle_id)}
```

---

## 📋 검증 대상 finding 목록 ({finding_count}건)

> 같은 (법령, 조문)의 finding은 묶어 표시. 조문 본문은 한 번만, finding은
> 그 조문 아래 리스트로 나열. 시행령 매핑은 위임 키워드가 있는 조문에만.

"""


def _load_findings_by_rule() -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """모든 result JSON 로드 → (룰별 finding, (법령,article_id)별 article)."""
    by_rule: dict[str, list[dict]] = defaultdict(list)
    article_cache: dict[str, dict] = {}  # key = f"{law}::{article_id}"
    for fp in sorted(Path("outputs/results").glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        law = data.get("law", {})
        law_name = law.get("name") or fp.stem
        law_category = law.get("category") or law.get("law_category") or ""
        for art in law.get("articles", []):
            article_cache[f"{law_name}::{art['article_id']}"] = art
        for f in data.get("findings", []):
            pid = f.get("pattern_id")
            if not pid or pid in _META_PATTERNS:
                continue
            f["_law_name"] = law_name
            f["_law_category"] = law_category
            by_rule[pid].append(f)
    return by_rule, article_cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage A — 룰 검증 sub-bundle (콘텐츠 포함, Plus 타깃)"
    )
    parser.add_argument("--output-dir", default="outputs/rule_verification")
    parser.add_argument(
        "--per-rule",
        type=int,
        default=300,
        help="룰당 stratified sample 크기 (기본 300). 작은 룰은 전체.",
    )
    parser.add_argument(
        "--per-bundle",
        type=int,
        default=50,
        help="sub-bundle 한 개당 finding 수 (기본 50, Plus 안전).",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--only",
        nargs="*",
        help="특정 룰만 생성 (예: --only S-02 G-02)",
    )
    parser.add_argument(
        "--min-findings",
        type=int,
        default=10,
        help="이 미만의 룰은 건너뛰기 (분석 신뢰도). 기본 10.",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("results JSON 스캔 중...", file=sys.stderr)
    by_rule, article_cache = _load_findings_by_rule()
    print(
        f"발견 룰: {len(by_rule)} / 총 finding: {sum(len(v) for v in by_rule.values()):,}건",
        file=sys.stderr,
    )

    decree_cache: dict[str, object | None] = {}
    index_entries: list[dict] = []
    total_bundles = 0
    total_findings = 0

    rules_sorted = sorted(by_rule.items(), key=lambda kv: -len(kv[1]))
    for rule_id, findings in rules_sorted:
        if args.only and rule_id not in args.only:
            continue
        if len(findings) < args.min_findings:
            print(
                f"  {rule_id:<10} skip ({len(findings)}건 < min-findings={args.min_findings})",
                file=sys.stderr,
            )
            continue

        rule_name = next(
            (f.get("pattern_name") for f in findings if f.get("pattern_name")),
            rule_id,
        )
        sampled = _stratified_sample(findings, args.per_rule, args.seed)
        # 같은 (법령, 조문) 묶기 + 정렬 (severity → 법령 → 조문번호)
        sev_rank = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
        sampled.sort(
            key=lambda f: (
                sev_rank.get(f.get("severity"), 99),
                f.get("_law_name", ""),
                f.get("article_id", ""),
            )
        )

        # sub-bundle 분할: per_bundle finding 묶음 — 단, 같은 (법령,조문)은 같은 part로
        parts: list[list[dict]] = []
        current: list[dict] = []
        for f in sampled:
            current.append(f)
            if len(current) >= args.per_bundle:
                parts.append(current)
                current = []
        if current:
            parts.append(current)

        total_parts = len(parts)
        for idx, part_findings in enumerate(parts, 1):
            bundle_id = f"{rule_id}_part{idx:02d}"
            # 조문 단위로 그룹화
            by_art: dict[str, list[dict]] = defaultdict(list)
            for f in part_findings:
                key = f"{f['_law_name']}::{f['article_id']}"
                by_art[key].append(f)

            entries: list[str] = []
            for art_key, art_findings in by_art.items():
                article = article_cache.get(art_key)
                if not article:
                    continue
                law_name = art_findings[0]["_law_name"]
                law_category = art_findings[0]["_law_category"]
                entries.append(
                    _format_entry(
                        law_name=law_name,
                        law_category=law_category,
                        article=article,
                        findings=art_findings,
                        decree_cache=decree_cache,
                    )
                )

            header = _bundle_header(
                bundle_id=bundle_id,
                rule_id=rule_id,
                rule_name=rule_name,
                part=idx,
                total_parts=total_parts,
                finding_count=len(part_findings),
                entry_count=len(by_art),
            )
            content = header + "\n---\n\n".join(entries) + "\n"
            out_path = out_dir / f"{bundle_id}.md"
            out_path.write_text(content, encoding="utf-8")
            size_kb = out_path.stat().st_size / 1024
            index_entries.append({
                "bundle_id": bundle_id,
                "rule_id": rule_id,
                "part": idx,
                "total_parts": total_parts,
                "finding_count": len(part_findings),
                "entry_count": len(by_art),
                "size_kb": round(size_kb, 1),
                "file": out_path.name,
            })
            total_bundles += 1
            total_findings += len(part_findings)

        print(
            f"  {rule_id:<10} {len(findings):>6,}건 → 샘플 {len(sampled):>4}건 "
            f"→ {total_parts}개 sub-bundle",
            file=sys.stderr,
        )

    index = {
        "generated_by": "scripts/bundle_rule_verification.py",
        "per_rule_sample": args.per_rule,
        "per_bundle": args.per_bundle,
        "seed": args.seed,
        "total_bundles": total_bundles,
        "total_findings": total_findings,
        "bundles": index_entries,
    }
    (out_dir / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"\n총 {total_bundles}개 sub-bundle / {total_findings:,}건 finding 생성. "
        f"인덱스: {out_dir/'_index.json'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
