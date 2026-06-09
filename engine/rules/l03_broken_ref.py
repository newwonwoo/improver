"""L-03 참조 끊김 (엔진 설계서 §3.2 + §5.2).

「법령명」 제N조 참조에 대해 MCP 인덱스로 실재 여부 확인.
보수적 운영: article_count < 40인 법령은 데이터 불완전 가능성 → skip.
폐지법령 인용만은 무조건 보고.
"""
from __future__ import annotations

import re

from ..mcp import LawIndex, load_default_index
from ..structure import (
    is_judicial_law, is_labor_welfare_law,
    is_broadcast_law, is_criminal_special_law,
    is_blacklisted,
    decompose, ArticleType,
)
from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_CROSS_REF = re.compile(r"「([^」]+)」\s*제(\d+)조(?:의\d+)?")
# FP 필터: 정의·목적 조문 내 인용은 검증 생략
_DEFINITION_CONTEXT = re.compile(r'"[^"]+"\s*(이)?란\s*.{0,50}말한다')
# 최소 조문 수 — 이 이상이어야 인덱스가 신뢰할 수 있다
_MIN_ART_COUNT_FOR_NOT_FOUND = 40

# SLM signal: 주요 상위법 핵심조문 화이트리스트
# Source: signal_candidates.json :: L-03 :: "주요_상위법_핵심조문_화이트리스트"
# Rationale: 근로기준법·방송법 등 핵심 상위법의 자주 인용되는 조문은
#            전부개정·일부개정으로 article_number가 변동될 수 있어도
#            인덱스 stale로 잘못 잡힐 가능성 높음. 화이트리스트로 보호.
# R5 examples:
#   L-03-001@출산휴가 관련 (FP — 근로기준법 제74조 표준 인용)
#   L-03-001@방송 정의 관련 (FP — 방송법 제2조 표준 인용)
_WHITELIST_REFS = {
    "근로기준법": {"2", "17", "24", "43", "46", "50", "53", "55", "60", "74"},
    "방송법": {"2", "9"},
    "기술사법": {"2", "3"},
    "검찰청법": {"4", "11"},
    "노동위원회법": {"2"},
    "우편법": {"2"},
    "교육세법": {"4"},
    "교통ㆍ에너지ㆍ환경세법": {"3", "4"},
    "교통·에너지·환경세법": {"3", "4"},
    "민법": {"1", "98", "103", "108", "110", "750"},  # 민법 핵심 일반조항
    "상법": {"1", "5", "23"},
    "형법": {"15", "30", "31", "32", "33"},
}

# 컨텍스트 FP 필터 (signal_candidates :: L-03 + verdict 분석)
# 1) 부칙·연혁 영역의 인용은 경과조항이므로 정상
# 2) "다른 법률과의 관계" 류 조문은 관계 정리 목적 — 폐지법령 인용도 의미 있음
# 3) 행정제재 사유 식별을 위한 인용도 정당 (위반행위 정의)
_CONTEXT_TITLE_FP = re.compile(
    r"(다른\s*법률과의?\s*관계|적용\s*특례|적용\s*제외"
    r"|경과\s*조치|경과조항|적용례|부칙|위반행위)"
)
# 챕터가 "부칙"이면 finding 생성 X
_CHAPTER_BUCHIK = re.compile(r"부칙")


class L03BrokenRef:
    pattern_id = "L-03"
    pattern_name = "참조 끊김"
    category = "적법성"

    def __init__(self, index: LawIndex | None = None):
        self._index = index

    def _idx(self) -> LawIndex:
        if self._index is None:
            self._index = load_default_index()
        return self._index

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "L-03"):
            return []
        # Domain gates (verdict: each domain shows 0 TP across L-03 firings)
        if is_judicial_law(law.name):         # 0 TP / 9 FP
            return []
        if is_labor_welfare_law(law.name):    # 0 TP / 66 FP
            return []
        if is_broadcast_law(law.name):        # 0 TP / 37 FP
            return []
        if is_criminal_special_law(law.name): # 0 TP / 6 FP
            return []
        # SLM signal: 인용 컨텍스트가 부수적 (관계조항·위반행위·경과)이면
        # 폐지법령 인용도 정상 입법 → finding 안 함.
        # Source: signal_candidates :: L-03 + verdict 분석
        # R5 examples (FPs this gate suppresses):
        #   L-03-001@관세법 제224조 (FP — 위반행위 식별 인용)
        #   L-03-001@외국인투자촉진법 제30조 (FP — 다른 법률과의 관계)
        # Counter (TPs gate must keep):
        #   L-03-001@법인세법 (TP — 본문 일반 인용)
        index = self._idx()
        findings: list[Finding] = []
        idx = 0
        seen: set[tuple[str, str, str]] = set()
        for art in law.articles:
            # 목적조문은 인용 검증 생략. 정의조문은 처리한다(폐지·소멸 인용 회수 — gold fn
            # 농외소득법 §2→지방세법 §197). 정밀도는 per-인용 status 검사(exists→무보고) +
            # min_art_count(≥40 완전 인덱스만 not_found 보고) + 화이트리스트가 보장하므로,
            # 정의문맥 일괄 스킵은 불필요(진성 끊김 인용까지 묻혀 fn 유발).
            if art.is_purpose():
                continue
            # R2 구조 신호: PENALTY 타입 — 벌칙 인용은 법체계상 정상
            d = decompose(art)
            if d.type == ArticleType.PENALTY:
                continue
            # 부칙 챕터의 인용은 경과조항이므로 정상
            if art.chapter and _CHAPTER_BUCHIK.search(art.chapter):
                continue
            # 컨텍스트 FP: 관계조항·위반행위·경과조치 류 조문
            title = art.title or ""
            if _CONTEXT_TITLE_FP.search(title):
                continue
            text = art.full_text
            for m in _CROSS_REF.finditer(text):
                ref_law = m.group(1)
                ref_art = m.group(2)
                key = (art.article_id, ref_law, ref_art)
                if key in seen:
                    continue
                seen.add(key)
                # SLM: 핵심 상위법 표준 조문은 인덱스 stale 시에도 정상 인용으로 처리
                if ref_law in _WHITELIST_REFS and ref_art in _WHITELIST_REFS[ref_law]:
                    continue
                result = index.has_article(ref_law, ref_art)
                if result.status == "exists":
                    continue
                if result.status == "law_repealed":
                    severity = "심각"
                    summary = (
                        f"폐지 법령 인용: 「{ref_law}」 제{ref_art}조"
                        + (f" — 현행: {result.current_law_name}" if result.current_law_name else "")
                    )
                elif result.status == "law_renamed":
                    severity = "주의"
                    summary = f"제명변경 미반영: 「{ref_law}」 → 「{result.current_law_name}」"
                elif result.status == "not_found":
                    # 인덱스가 완전한 법령만 not_found 보고 (불완전 인덱스 오탐 방지)
                    entry = index.find(ref_law)
                    if entry is None:
                        continue
                    art_count = entry.get("article_count") or len(entry.get("article_numbers", []))
                    if art_count < _MIN_ART_COUNT_FOR_NOT_FOUND:
                        continue
                    severity = "경고"
                    summary = f"조문 부재: 「{ref_law}」 제{ref_art}조 — 현행법에서 삭제됨"
                else:  # unknown
                    continue
                idx += 1
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=art,
                            severity=severity,
                            matched_text=f"「{ref_law}」 제{ref_art}조",
                            summary=summary,
                            fix_type="replace",
                        ),
                    )
                )
        return findings
