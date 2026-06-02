#!/usr/bin/env python3
"""
Phase 13 v2 — Verdict batch 재생성 (QA 피드백 반영)

수정 사항:
1. primary_article 만 진단 (articles[:30] 컷 제거 → 전 조문 스캔 후 정확 매칭)
2. 시행령 한정열거 자동 확인 → R-DELEG-BLANKET FP 후보 사전 표시
3. background_laws 명시 (배경 인용 vs 쟁점 구분)
4. moleg 회답·이유 본문 + 시행령 발췌 동봉
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.parser import parse_law
from engine.slm.features import extract_features
from engine.reasoning import reason_over

CAND_FILE = ROOT / "outputs/phase13_verdict_candidates_v2.jsonl"
MOLEG_DIR = ROOT / "outputs/rule_mining/sources/crawled/moleg_interp"
LAWS_DIR = ROOT / "data/laws/raw"
OUT_DIR = ROOT / "outputs/phase13_verdict_batches_v2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 8

CONCRETE_ENUM_RX = re.compile(
    r"(?:다음\s*각\s*호|다음\s*각호)|"
    r"(?:\b1\.|\b가\.).{0,500}(?:\b3\.|\b다\.)"
)


def load_law_cached(name: str, cache: dict):
    if name in cache:
        return cache[name]
    md = LAWS_DIR / name / "법률.md"
    if not md.exists():
        cache[name] = None
        return None
    try:
        law = parse_law(md.read_text(encoding="utf-8"), name=name)
        cache[name] = law
        return law
    except Exception:
        cache[name] = None
        return None


def extract_moleg_sections(text: str) -> str:
    """질의·회답·이유 섹션만 추출."""
    if "---" in text:
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    # 핵심 마커 이후 본문 찾기
    keep = []
    in_body = False
    for line in text.split("\n"):
        if not in_body and any(k in line for k in ["질의요지", "1. 질의", "2. 회답"]):
            in_body = True
        if in_body:
            keep.append(line)
        if len(keep) > 80:
            break
    return "\n".join(keep)[:2500]


def find_article(law, article_num: str):
    """제161조 같은 조문 찾기."""
    if not article_num:
        return None
    norm = article_num.replace(" ", "")
    for art in law.articles:
        if art.number.replace(" ", "") == norm:
            return art
    return None


def check_sublaw_enum(law_name: str, art_num: str) -> dict:
    """시행령에서 해당 조문 한정열거 확인 — R-DELEG-BLANKET FP 필터."""
    out = {"checked": False, "has_concrete_enum": False, "evidence": ""}
    if not art_num:
        return out
    decree = LAWS_DIR / law_name / "시행령.md"
    if not decree.exists():
        return out
    try:
        text = decree.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return out
    out["checked"] = True
    art_digits = re.search(r"\d+", art_num).group() if re.search(r"\d+", art_num) else ""
    if not art_digits:
        return out
    # 시행령에서 "법 제N조" 인용 위치
    m = re.search(rf"법\s*제\s*{art_digits}\s*조", text)
    if not m:
        return out
    chunk = text[m.start() : m.start() + 1500]
    if CONCRETE_ENUM_RX.search(chunk):
        out["has_concrete_enum"] = True
        out["evidence"] = chunk[:400].replace("\n", " ")
    return out


def render_batch(items: list, batch_idx: int) -> str:
    out = [
        f"# Phase 13 Verdict Batch v2 #{batch_idx:02d} ({len(items)}건)",
        "",
        "## QA 피드백 반영 사항",
        "이전 batch (v1) 의 5가지 문제 수정:",
        "1. 제목 끝 `(「쟁점법령」 제N조 등 관련)` 패턴으로 정확한 쟁점법령·조문 추출",
        "2. 배경 인용 법령 (background_laws) 명시",
        "3. (file, primary_law, article) 중복 제거",
        "4. **전 조문 스캔 후 정확 조문 매칭** (articles[:30] 버그 제거)",
        "5. R-DELEG-BLANKET 발화 시 **시행령 한정열거 자동 확인** (FP 후보 사전 표시)",
        "",
        "## 요청",
        "각 항목별로:",
        "- `verdict`: TP/FP/BORDER",
        "- `rule_id`: 평가 대상 규칙",
        "- `relevant_to_moleg`: 해석례와 조문 쟁점 일치 여부",
        "- `issue`: 데이터/매핑 이슈 코드 (DELEG_FILLED_BY_SUBLAW, MATCH_MISS, etc.)",
        "- `reason`: 근거 설명",
        "",
        "## 응답 JSON 스키마",
        "```json",
        "{",
        '  "verdicts": [',
        '    {"id":1, "verdict":"TP|FP|BORDER", "rule_id":"R-...", "relevant_to_moleg":true|false, "issue":"...", "reason":"..."},',
        "    ...",
        "  ]",
        "}",
        "```",
        "",
        "---",
        "",
    ]
    law_cache = {}
    for i, cand in enumerate(items, 1):
        law = load_law_cached(cand["primary_law"], law_cache)
        if not law:
            out.append(f"### #{i} — 「{cand['primary_law']}」 (corpus parse 실패, skip)")
            out.append("")
            continue

        art = find_article(law, cand["primary_article_norm"])
        moleg_body = extract_moleg_sections(
            (MOLEG_DIR / cand["file"]).read_text(encoding="utf-8", errors="ignore")
        )

        out.append(f"### #{i} — 「{cand['primary_law']}」 {cand['primary_article_norm']}")
        out.append(f"**moleg 해석례 제목**: {cand['title'][:200]}")
        out.append(f"**배경 인용 법령**: {', '.join(cand['background_laws']) or '없음'}")
        out.append("")
        out.append(f"**moleg 본문 발췌**:")
        out.append("```")
        out.append(moleg_body[:1500])
        out.append("```")
        out.append("")

        if not art:
            out.append(f"**⚠ 조문 매칭 실패**: {cand['primary_article_norm']} 가 corpus 에서 검색 안 됨")
            out.append("")
            out.append("---\n")
            continue

        # 정확 조문 평가
        fv = extract_features(art)
        res = reason_over(fv)

        out.append(f"**조문 본문** ({art.number} {art.title or ''}):")
        out.append("```")
        out.append(art.full_text[:2000])
        out.append("```")
        out.append("")

        out.append(f"**우리 진단엔진 발화**:")
        if not res.steps:
            out.append("  (발화 없음 — 진단 깨끗)")
        else:
            for step in res.steps:
                out.append(f"  - **{step.rule_id}** (신뢰도 {step.confidence:.2f})")
                out.append(f"    추론: {step.inference[:200]}")
                # R-DELEG-BLANKET 자동 FP 필터
                if step.rule_id == "R-DELEG-BLANKET":
                    sub = check_sublaw_enum(cand["primary_law"], cand["primary_article_norm"])
                    if sub["checked"]:
                        if sub["has_concrete_enum"]:
                            out.append(f"    🚩 **FP 후보**: 시행령에 한정 열거 확인됨 (위임 구체화)")
                            out.append(f"    시행령 발췌: `{sub['evidence'][:200]}...`")
                        else:
                            out.append(f"    ✓ 시행령 확인: 한정 열거 미발견 (TP 가능성)")
        out.append("")
        out.append("---\n")
    return "\n".join(out)


def main():
    items = []
    with open(CAND_FILE) as f:
        for line in f:
            items.append(json.loads(line))
    print(f"candidates: {len(items)}")

    n_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
    for b in range(n_batches):
        batch_items = items[b * BATCH_SIZE : (b + 1) * BATCH_SIZE]
        md = render_batch(batch_items, b + 1)
        out_path = OUT_DIR / f"batch_v2_{b+1:02d}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"  {out_path.relative_to(ROOT)} — {len(batch_items)}건 ({len(md):,}자)")


if __name__ == "__main__":
    main()
