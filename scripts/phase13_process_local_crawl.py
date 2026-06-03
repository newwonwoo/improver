#!/usr/bin/env python3
"""
98건 로컬 크롤링 자료 처리 — Phase 13

라우팅:
1. moleg_interp (법령해석 90건) → 추론엔진(symbolic)
   - 회답/이유 추출 → 법령 정합성 패턴 식별
   - 우리 corpus 의 어떤 조문이 인용되는지 매핑 → verdict 후보

2. ftc_press (보도자료 14건) → 추론엔진 + verdict 라벨 후보
   - 위반행위 + 제재 패턴 추출
   - 약관 시정 / 부당특약 / 하도급 패턴 분류

출력:
- outputs/phase13_routing.json — 분류 결과
- outputs/phase13_patterns.md — 추출 패턴 (사람이 검토용)
- outputs/phase13_verdict_candidates.jsonl — verdict 후보
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
MOLEG_DIR = ROOT / "outputs/rule_mining/sources/crawled/moleg_interp"
FTC_DIR = ROOT / "outputs/rule_mining/sources/crawled/ftc_press"
LAWS_DIR = ROOT / "data/laws/raw"

# 법령 인용 정규식 — 「법령명」 제N조 패턴
LAW_CITE = re.compile(r"「([^」]{3,40})」\s*(?:제\s*\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호)?(?:[가-하]목)?)?")
ARTICLE_CITE = re.compile(r"제\s*(\d+)조(?:의(\d+))?")

# 회답/이유 섹션 추출
SECTION_RX = re.compile(r"^(?:#+\s*)?(\d+\.\s*(?:질의|회답|이유|결론))", re.MULTILINE)


def load_corpus_laws():
    """corpus 의 법령명 set — 우리가 분석 가능한 법령만 verdict 후보"""
    if not LAWS_DIR.exists():
        return set()
    return {d.name for d in LAWS_DIR.iterdir() if d.is_dir()}


def extract_moleg_sections(md_text: str) -> dict:
    """moleg .md 에서 질의/회답/이유 섹션 분리."""
    body = md_text
    # 헤더 부분 제거
    if "---" in body:
        parts = body.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]

    sections = {"질의": "", "회답": "", "이유": "", "결론": ""}
    matches = list(SECTION_RX.finditer(body))
    for i, m in enumerate(matches):
        name = None
        for k in sections:
            if k in m.group(1):
                name = k
                break
        if not name:
            continue
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()
    return sections


def extract_cited_laws(text: str) -> list[str]:
    """텍스트에서 인용된 법령명 추출."""
    cites = set()
    for m in LAW_CITE.finditer(text):
        name = m.group(1).strip()
        # 약어/일반명사 필터
        if len(name) >= 4 and not name.startswith(("그", "이", "위")):
            cites.add(name)
    return sorted(cites)


def detect_patterns(text: str) -> list[str]:
    """이유 섹션에서 추론엔진 강화에 도움될 패턴 식별."""
    patterns = []
    # 1. "다른 법률의 특별한 규정" — 적용 우선순위
    if re.search(r"다른\s*법(률|령)의?\s*특별한\s*규정", text):
        patterns.append("law_precedence")
    # 2. 법령 상호 조화/충돌
    if re.search(r"(법령\s*상호\s*간|법령간|조화|상충)", text):
        patterns.append("law_harmony")
    # 3. 위임 한계
    if re.search(r"(위임의?\s*한계|위임범위|위임명령)", text):
        patterns.append("delegation_limit")
    # 4. 처분 기준 명확성
    if re.search(r"(명확(?:성|히)|구체적|예측가능)", text):
        patterns.append("clarity_required")
    # 5. 적용 배제
    if re.search(r"(적용(?:을|이)?\s*배제|적용되지\s*않|제외(?:한다|된다))", text):
        patterns.append("application_exclusion")
    # 6. 입법 취지 해석
    if re.search(r"(입법(?:의)?\s*취지|규정(?:의)?\s*취지|취지에\s*부합)", text):
        patterns.append("legislative_intent")
    # 7. 행정규칙 위임 한계 (R-SUBDELEG-ADMIN-RULE 직결)
    if re.search(r"(고시|훈령|예규|지침|행정규칙).{0,30}(위임|정할\s*수)", text):
        patterns.append("admin_rule_delegation")
    # 8. 절차 보장
    if re.search(r"(청문|의견(?:청취|제출)|소명(?:기회)?)", text):
        patterns.append("procedural_protection")
    return patterns


def process_moleg(corpus_laws: set) -> dict:
    """moleg_interp 90건 처리."""
    md_files = sorted(MOLEG_DIR.glob("*.md"))
    out = {
        "total": len(md_files),
        "items": [],
        "pattern_counts": defaultdict(int),
        "in_corpus_laws": defaultdict(list),
    }
    for fp in md_files:
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        # title from first line
        title = text.split("\n", 1)[0].lstrip("#").strip()[:200]
        sections = extract_moleg_sections(text)
        reasoning = sections["이유"] + " " + sections["회답"]
        cited = extract_cited_laws(reasoning) or extract_cited_laws(title)
        patterns = detect_patterns(reasoning)
        in_corpus = [c for c in cited if c in corpus_laws]

        item = {
            "file": fp.name,
            "title": title,
            "cited_laws_count": len(cited),
            "cited_laws_in_corpus": in_corpus,
            "patterns": patterns,
            "reasoning_len": len(reasoning),
        }
        out["items"].append(item)
        for p in patterns:
            out["pattern_counts"][p] += 1
        for cl in in_corpus:
            out["in_corpus_laws"][cl].append(fp.name)

    out["pattern_counts"] = dict(out["pattern_counts"])
    out["in_corpus_laws"] = {k: v[:5] for k, v in out["in_corpus_laws"].items()}
    return out


def process_ftc(corpus_laws: set) -> dict:
    """ftc_press 14건 처리 — 제목 위주 (본문은 .hwp 첨부)."""
    from bs4 import BeautifulSoup
    md_files = sorted(FTC_DIR.glob("*.md"))
    out = {
        "total": len(md_files),
        "items": [],
        "category_counts": defaultdict(int),
    }
    for fp in md_files:
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception:
            continue
        title = text.split("\n", 1)[0].lstrip("#").strip()
        # 카테고리 분류 by title keyword
        category = "기타"
        if re.search(r"부당특약|하도급", title):
            category = "하도급 부당특약 (R-DISP-ARBITRARY/공정성)"
        elif re.search(r"약관|시정", title):
            category = "약관 시정 (R-BROAD-IMMUNITY/R-DISP-ARBITRARY)"
        elif re.search(r"담합|입찰", title):
            category = "담합 (적법성)"
        elif re.search(r"표시광고|광고|기만", title):
            category = "표시광고 (공정성)"
        elif re.search(r"가맹|대리점", title):
            category = "가맹·대리점 (공정성)"
        elif re.search(r"과징금|제재", title):
            category = "제재 (적법성)"
        out["items"].append({
            "file": fp.name,
            "title": title,
            "category": category,
        })
        out["category_counts"][category] += 1
    out["category_counts"] = dict(out["category_counts"])
    return out


def main():
    corpus_laws = load_corpus_laws()
    print(f"corpus laws: {len(corpus_laws)}")

    moleg_res = process_moleg(corpus_laws)
    ftc_res = process_ftc(corpus_laws)

    # Verdict 후보 — corpus 에 있는 법령을 인용한 moleg 해석례
    verdict_candidates = []
    for item in moleg_res["items"]:
        for ln in item["cited_laws_in_corpus"]:
            verdict_candidates.append({
                "source": "moleg_interp",
                "file": item["file"],
                "law_name": ln,
                "patterns": item["patterns"],
                "title": item["title"][:150],
            })

    summary = {
        "phase": 13,
        "moleg": {
            "total": moleg_res["total"],
            "pattern_counts": moleg_res["pattern_counts"],
            "in_corpus_law_count": len(moleg_res["in_corpus_laws"]),
            "in_corpus_laws_top": dict(list(moleg_res["in_corpus_laws"].items())[:10]),
        },
        "ftc_press": {
            "total": ftc_res["total"],
            "category_counts": ftc_res["category_counts"],
        },
        "verdict_candidates_count": len(verdict_candidates),
    }

    Path("outputs/phase13_routing.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with open("outputs/phase13_verdict_candidates.jsonl", "w", encoding="utf-8") as f:
        for v in verdict_candidates:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
