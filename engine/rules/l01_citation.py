"""L-01 인용 법령 (엔진 설계서 §3.2).

「」 안의 법령 인용 수가 한 조문에서 5건↑ → 주의 (과도한 타법 의존).
정확한 폐지/제명 확인은 MCP 연동 필요 → 다음 PR.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_judicial_law
from .base import PatternResult, make_finding

_CITE_PAT = re.compile(r"「([^」]+)」")
# TP 컨텍스트: 인허가의제·특례·금지 조문 — 과도한 인용이 실질 결함
# Source: signal_candidates.json :: L-01 :: "인ㆍ허가의제_조문_TP_확정"
_TP_CONTEXT = re.compile(
    r"(인[\s·ㆍ]?허가.{0,10}의제|특례\s*규정|금지\s*행위|이\s*법에\s*따른\s*의무"
    r"|다른\s*법률과의?\s*관계|받은\s*것으로\s*본다)"
)
# 인허가의제 조문 제목 — TP 강제 트리거
_TP_TITLE = re.compile(
    r"(다른\s*법률과의?\s*관계|인[\s·ㆍ]?허가\s*등?의?\s*의제|허가\s*등?의?\s*의제"
    r"|심사\s*[·ㆍ]?\s*승인\s*[·ㆍ]?\s*협의의?\s*의제"
    r"|사무처리\s*특례)"
)
# FP 컨텍스트: 법제상 불가피한 타법 인용 조문 유형
# Source: signal_candidates.json :: L-01 :: 정의/벌칙/감면/지급대상/정보체계 시리즈
_FP_CONTEXT = re.compile(
    r"(결격\s*사유|취업\s*제한|징계\s*부가금|감면\s*대상|지급\s*대상|중복\s*수급"
    r"|회원의?\s*자격|비과세|적용\s*제외|준용한다|준용하는|회원\s*가입"
    r"|수급권자|위원의?\s*자격|정보\s*제공\s*요청)"
)
_FP_TITLE = re.compile(
    r"(승계|회원의?\s*자격|비과세|면제|적용\s*제외|준용|회원\s*가입"
    r"|결격\s*사유|감면|특별\s*공제|공제\s*대상|징계\s*부가금"
    r"|취업\s*제한|비위\s*면직|정보체계|시스템|자료\s*제공|정보\s*제공"
    r"|적용\s*특례|지원\s*대상|지급\s*대상"
    r"|세입|세출|정관|회계|예산|결산|수수료|회비"
    r"|기초연구|연구사업|입주기관\s*지원|위탁|위임"
    r"|겸임|겸직|특례)"
)
# 본문 신호: "다음 각 호의 [기관/사람/자/대학/대상자]" — 정의용 인용 패턴
_DEFINITIONAL_LIST = re.compile(
    r"다음\s*각\s*호의?\s*(기관|사람|자|대학|단체|기업|법인|시설|매체물|대상자|업체)"
)
# 본문 신호: 적용 범위 정의 (이 법 ... 다음 각 호의 법률에 따르지)
_SCOPE_DEFINITION = re.compile(
    r"(이\s*법|이\s*규정|이\s*기준).{0,50}다음\s*각\s*호의?\s*법률에\s*따르"
)
# 본문 신호: 행위제한·금지 단서 (생태·경관보전지역에서의 행위제한 류)
_PROHIBITED_AREA = re.compile(
    r"누구든지\s*.{0,30}안에서는?\s*다음\s*각\s*호의?\s*어느\s*하나"
)
# FP: 벌칙 본문 신호 (제목이 안 잡혀도 본문으로 판별)
# Source: signal_candidates.json :: L-01 :: "벌칙·제재조문_FP_필터"
_PENALTY_BODY = re.compile(
    r"(\d+년\s*이하의?\s*징역|\d+(천|만|억)?원\s*이하의?\s*벌금"
    r"|취업할\s*수\s*없다|해임|파면|몰수|추징)"
)
# FP: 정보체계 구축·연계 조문 (자료원천 인용용)
_INFO_SYSTEM = re.compile(
    r"(정보체계|시스템).{0,50}(구축|연계|운영).{0,300}자료\s*(또는|이나|·)?\s*정보"
)


def _is_fp_article(art: Article) -> bool:
    """L-01 FP 필터 — 불가피한 타법 인용 조문.

    Source: signal_candidates.json :: L-01
    R5 examples (verdicts that justify):
      L-01-001@소득세법 (FP — 정의조문)
      L-01-001@형법 (FP — 벌칙조문)
      L-01-001@사회보장기본법 (FP — 적용대상)
      L-01-001@정보공개법 (FP — 정보체계 자료원천)
    Counter-examples (TPs):
      L-01-007@다른 법률과의 관계 (TP — 사무처리 특례)
    """
    if art.is_definition() or art.is_penalty() or art.is_purpose():
        return True
    if art.is_disqualification():
        return True
    title = art.title or ""
    # TP 트리거가 제목에 있으면 FP 필터 통과시키지 않음 (TP 강제)
    if _TP_TITLE.search(title):
        return False
    if _FP_TITLE.search(title):
        return True
    text = art.full_text
    if _FP_CONTEXT.search(text):
        return True
    # 본문에 형벌 신호 (제목이 모호해도 벌칙조문 식별)
    if _PENALTY_BODY.search(text):
        return True
    # 정보체계 자료원천 인용
    if _INFO_SYSTEM.search(text):
        return True
    # 정의용 인용 패턴 (다음 각 호의 기관/사람/자/대학…)
    if _DEFINITIONAL_LIST.search(text):
        return True
    # 적용 범위 정의 (이 법 ... 다음 각 호의 법률에 따르)
    if _SCOPE_DEFINITION.search(text):
        return True
    # 행위제한 영역에서 다른 법령 인용
    if _PROHIBITED_AREA.search(text):
        return True
    return False


class L01Citation:
    pattern_id = "L-01"
    pattern_name = "인용 법령"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        # 사법·절차법령 — L-01 미적용 (verdict: 0 TP / 4 FP)
        if is_judicial_law(law.name):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            # Structural FP gates (verdict 분석): 0 TP / 다수 FP 조합
            decomp = decompose(art)
            t, s = decomp.type, decomp.primary_subject.value
            from ..structure import Modal
            modal_str = "NONE"
            for p in decomp.paragraphs:
                if p.modal != Modal.NONE: modal_str = p.modal.value; break
            # 사전 인용 수 계산 — 게이트가 다수 인용 본질을 놓치지 않도록
            cites_pre = _CITE_PAT.findall(art.full_text)
            laws_pre = {c for c in cites_pre if c.endswith("법") or c.endswith("법률") or "관한 법" in c}
            many_cites = len(laws_pre) >= 12
            if t == ArticleType.DELEGATION and s == "EVERYONE":
                continue
            if t == ArticleType.DISPOSITION and s == "AGENCY":
                continue
            # 3-axis gates — 인용 12개 이상이면 본질적 정탐 가능성 → gate 통과
            if not many_cites:
                if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "NONE":
                    continue
                if t == ArticleType.DELEGATION and s == "UNKNOWN" and modal_str == "NONE":
                    continue
            if t == ArticleType.PROHIBITION:
                continue  # 모든 PROHIBITION 조문 — 다른 룰 영역
            if t == ArticleType.DISPOSITION and s == "OPERATOR" and modal_str == "MUST":
                continue
            if t == ArticleType.DELEGATION and s == "OPERATOR" and modal_str == "MAY":
                continue
            cites = cites_pre
            # 법령명만 카운트 — 동일 법령명은 1회로
            laws = {c for c in cites if c.endswith("법") or c.endswith("법률") or "관한 법" in c}
            # TP 부스트: 의제·특례 조문의 과다 인용은 한 단계 상향
            has_tp_context = bool(_TP_CONTEXT.search(art.full_text))
            # TP 컨텍스트 있으면 임계값 낮춤 (인허가의제는 6개부터)
            # TP 컨텍스트 없으면 7개 이상이어야 발화 (정밀도 우선)
            min_threshold = 6 if has_tp_context else 7
            if len(laws) < min_threshold:
                continue
            if len(laws) >= 10:
                severity = "심각" if has_tp_context else "경고"
            elif len(laws) >= 8:
                severity = "경고" if has_tp_context else "주의"
            else:
                severity = "주의" if has_tp_context else "개선"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"{len(laws)}개 법률",
                        summary=f"한 조문에 {len(laws)}개 법률 인용 — 독해 곤란"
                        + (" (의제·특례 조문)" if has_tp_context else ""),
                        fix_type="replace",
                    ),
                )
            )
        return findings
