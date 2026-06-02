#!/usr/bin/env python3
"""
Phase 13 v2 — 데이터 파이프라인 재구축

QA 피드백 반영 (batch_01 검증 결과):
1. 법령↔해석례 매핑 오류 (3건) — 쟁점법령 vs 배경인용 구분 안 됨
2. 인용 배경법령을 쟁점법령으로 오인 (2건) — 첫 「..」 무차별 채택
3. 중복 (2쌍) — (file, law) 페어 중복 미제거
4. 엔진 고정출력 — articles[:30] 컷으로 핵심 조문 누락
5. R-DELEG-BLANKET 구조적 FP — 시행령 한정열거 무시

수정 사항:
- 제목 끝 "(「쟁점법령」 제N조 등 관련)" 패턴으로 primary law/article 추출
- 배경 인용 법령은 background 로 분리
- (file, primary_law, primary_article) 페어로 중복 제거
- 진단 시 primary article 만 실행 (없으면 fallback 명시)
- R-DELEG-BLANKET 발화 시 시행령 한정열거 자동 확인
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
MOLEG_DIR = ROOT / "outputs/rule_mining/sources/crawled/moleg_interp"
LAWS_DIR = ROOT / "data/laws/raw"

# 핵심 패턴: 제목 끝의 "(「쟁점법령」 제N조 등 관련)"
# 다중 등장 시 마지막 (=가장 구체적) 사용
ISSUE_RX = re.compile(r"「([^」]{3,50})」\s*((?:별표\s*\d+|제\s*\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호)?(?:[가-하]목)?)(?:\s*등)?)\s*관련")

# 시행령 한정열거 패턴 — 백지위임 FP 필터
CONCRETE_ENUM_RX = re.compile(
    r"(?:다음\s*각\s*호|다음\s*각호)|"  # "다음 각 호"
    r"(?:1\.\s+|2\.\s+).{0,200}(?:3\.\s+|4\.\s+)|"  # 1. 2. 3. 4. 열거
    r"(?:가\.\s+|나\.\s+|다\.\s+).{0,300}(?:라\.|마\.)"  # 가. 나. 다. 라. 열거
)


def load_corpus_laws():
    return {d.name for d in LAWS_DIR.iterdir() if d.is_dir()} if LAWS_DIR.exists() else set()


def parse_moleg_title(title: str) -> dict:
    """제목에서 쟁점법령·조문 추출.

    패턴: "기관명 - 쟁점 (「쟁점법령」 제N조 등 관련)"
    """
    matches = list(ISSUE_RX.finditer(title))
    if not matches:
        return {"primary_law": None, "primary_article": None}
    # 마지막 매치(=관련 표시) 우선
    last = matches[-1]
    return {
        "primary_law": last.group(1).strip(),
        "primary_article": last.group(2).strip(),
    }


def extract_all_cited(text: str) -> list:
    """본문 전체 인용 법령 (background 포함)"""
    cites = set()
    for m in re.finditer(r"「([^」]{3,50})」", text):
        name = m.group(1).strip()
        if len(name) >= 4 and not name.startswith(("그", "이", "위")):
            cites.add(name)
    return sorted(cites)


def normalize_article_number(art_ref: str) -> str:
    """제78조제2항제1호다목 → 제78조 (조 단위 정규화)"""
    m = re.match(r"(제\s*\d+조(?:의\d+)?)", art_ref)
    return m.group(1).replace(" ", "") if m else art_ref


def check_sublaw_concrete(law_name: str, article_num: str) -> dict:
    """R-DELEG-BLANKET FP 필터: 시행령에 한정 열거 있는가?"""
    result = {"has_sublaw": False, "is_concretized": False, "evidence": ""}
    decree = LAWS_DIR / law_name / "시행령.md"
    if not decree.exists():
        return result
    result["has_sublaw"] = True
    try:
        text = decree.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return result
    # 시행령에서 해당 조문 관련 부분 검색
    # 예: "법 제N조에 따라" 또는 "법 제N조의 위임에 따라"
    art_pat = article_num.replace("제", "").replace("조", "")
    m = re.search(rf"법\s*제\s*{art_pat}\s*조", text)
    if not m:
        return result
    # 매치 위치 주변 1000자에서 한정 열거 확인
    start = m.start()
    chunk = text[start : start + 2000]
    if CONCRETE_ENUM_RX.search(chunk):
        result["is_concretized"] = True
        result["evidence"] = chunk[:300]
    return result


def process_moleg(corpus_laws: set) -> dict:
    md_files = sorted(MOLEG_DIR.glob("*.md"))
    out = {"items": [], "skipped_no_pattern": 0, "skipped_no_corpus": 0}

    for fp in md_files:
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        title = text.split("\n", 1)[0].lstrip("#").strip()
        parsed = parse_moleg_title(title)
        primary_law = parsed["primary_law"]
        primary_art = parsed["primary_article"]

        if not primary_law:
            out["skipped_no_pattern"] += 1
            continue

        # primary law 가 corpus 에 없으면 verdict 후보 부적격
        if primary_law not in corpus_laws:
            # 시행령/시행규칙 빼고 본법명 추출 시도
            base = re.sub(r"\s*시행(령|규칙)\s*$", "", primary_law).strip()
            if base in corpus_laws:
                primary_law = base
            else:
                out["skipped_no_corpus"] += 1
                continue

        all_cites = extract_all_cited(text[:5000])
        background = [c for c in all_cites if c != primary_law and c not in primary_law]

        item = {
            "file": fp.name,
            "title": title[:300],
            "primary_law": primary_law,
            "primary_article": primary_art,
            "primary_article_norm": normalize_article_number(primary_art) if primary_art else None,
            "background_laws": background[:5],
        }
        out["items"].append(item)

    return out


def main():
    corpus_laws = load_corpus_laws()
    print(f"corpus laws: {len(corpus_laws)}")
    res = process_moleg(corpus_laws)
    print(f"items: {len(res['items'])}")
    print(f"skipped (no pattern in title): {res['skipped_no_pattern']}")
    print(f"skipped (primary law not in corpus): {res['skipped_no_corpus']}")

    # 중복 제거: (file, primary_law, primary_article_norm)
    seen = set()
    unique = []
    for it in res["items"]:
        key = (it["file"], it["primary_law"], it["primary_article_norm"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    print(f"unique after dedup: {len(unique)}")

    out_path = ROOT / "outputs/phase13_verdict_candidates_v2.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for it in unique:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"\nSaved: {out_path.relative_to(ROOT)}")

    # 통계
    laws_with_art = sum(1 for it in unique if it["primary_article_norm"])
    print(f"primary article 추출됨: {laws_with_art} / {len(unique)}")


if __name__ == "__main__":
    main()
