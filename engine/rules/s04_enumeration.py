"""S-04 열거 과다 (항 단위 호 개수)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding

# FP 필터 패턴
_PERMIT_DEEMED = re.compile(r"(인[\s·ㆍ]?허가.{0,10}의제|다른\s*법(률|령)에\s*따른\s*인[\s·ㆍ]?허가)")
_ARTICLES_OF_ASSOC = re.compile(r"정관.{0,30}(기재|포함|사항|규정)")
_PUBLIC_INSTITUTION = re.compile(r"(사업\s*범위|사업의\s*종류|공공기관의\s*운영)")
# FP: 정관 기재사항·회원자격·수입·수수료·면제·비과세 등 표준 열거
_STD_LIST_TITLE = re.compile(
    r"(정관|회원|회비|수수료|수입|세입|세출|예산|결산|회계|급여|면제|비과세|감면"
    r"|업무|사업|시설|기준|등록\s*요건|허가\s*요건|결격\s*사유|취소\s*사유"
    r"|위반행위|준수사항)"
)
# 포괄위임 종결호 — 호 자체가 아니라 마지막 호에서만 확인
_CATCHALL_ITEM = re.compile(r"그\s*밖에.{0,30}(대통령령|총리령|부령|규칙)으로\s*정하는")


def _is_fp_article(art: Article) -> bool:
    """열거 과다 FP 필터 — 법제상 불가피한 호 다수 조문."""
    # 정의·벌칙·목적 조문은 호 열거가 정상
    if art.is_definition() or art.is_penalty() or art.is_purpose():
        return True
    text = art.full_text
    title = art.title or ""
    # 인허가의제 조문 — 법적 의제 열거 불가피
    if _PERMIT_DEEMED.search(title) or _PERMIT_DEEMED.search(text[:300]):
        return True
    # 정관 기재사항 — 민법·상법 표준 형식 (제목 단독 "정관" 포함)
    if _ARTICLES_OF_ASSOC.search(title) or _ARTICLES_OF_ASSOC.search(text[:300]):
        return True
    if title.strip() == "정관":
        return True
    # 공공기관 사업범위 열거 — 설립근거법 표준
    if _PUBLIC_INSTITUTION.search(title):
        return True
    # 표준 열거 제목 (회원자격·수입·면제 등): 호 30개 미만이면 FP
    # 단, "위반행위·취소사유·결격사유" 등 침익적 열거는 보고
    if _STD_LIST_TITLE.search(title):
        adversarial_title = any(k in title for k in ("위반", "취소", "결격", "처분", "벌"))
        if not adversarial_title:
            return True
    return False


def _has_catchall_without_substance(para) -> bool:
    """포괄위임 종결호만 있고 구체 기준 없는 항 — TP 부스트용."""
    if not para.items:
        return False
    last_text = para.items[-1].text
    return bool(_CATCHALL_ITEM.search(last_text))


class S04Enumeration:
    pattern_id = "S-04"
    pattern_name = "열거 과다"
    category = "구조"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            for para in art.paragraphs:
                n = len(para.items)
                if n < 10:
                    continue
                if n >= 30:
                    severity = "심각"
                elif n >= 20:
                    severity = "경고"
                elif n >= 15:
                    severity = "주의"
                else:
                    severity = "개선"
                # TP 부스트: 포괄위임 종결호 + 기준 부재
                has_catchall = _has_catchall_without_substance(para)
                if has_catchall and severity in ("주의", "개선"):
                    severity = "경고"
                idx += 1
                sub = "S-04-b" if has_catchall else "S-04-a"
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=art,
                            severity=severity,
                            matched_text=f"호 {n}개" + (" + 포괄위임" if has_catchall else ""),
                            summary=f"{art.number} {para.number or ''}: 호 {n}개 나열"
                            + (" (포괄위임 종결호)" if has_catchall else ""),
                            fix_type="add_paragraph",
                            sub_check_id=sub,
                        ),
                    )
                )
        return findings
