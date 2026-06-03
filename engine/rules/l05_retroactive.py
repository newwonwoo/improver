"""L-05 소급입법금지 / 경과조치 부재 (MOL-04 기반).

헌법 제13조②: 소급입법에 의한 재산권 박탈 금지.
신법 시행 후 이미 완성된 법률관계에 불리하게 소급 적용하거나,
경과조치 없이 기존 행위자·권리자에게 새 의무를 부과하는 조항.

TP 신호:
  - "이 법 시행 전에 행한", "이 법 시행 당시" + 침익적 조항 + 경과조치 없음
  - "종전의 규정에도 불구하고" + 불이익 소급 적용
  - 부칙·경과조치 없이 벌칙/제재가 소급 적용될 수 있는 구조

FP 필터:
  - "종전의 규정에 따른다" (경과조치 명시)
  - "이 법 시행 전에 허가받은 경우에는 ... 효력이 있다" (기득권 보호)
  - 수익적 소급 (이미 완성된 권리에 유리한 적용)
  - 정의·목적·벌칙 조문 자체
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_blacklisted
from .base import PatternResult, make_finding

# 소급 적용 신호
_RETROACTIVE = re.compile(
    r"(이\s*법?\s*시행\s*전에?\s*(?:행한|체결한|이루어진|발생한|설치한|제조한|수입한)"
    r"|이\s*법?\s*시행\s*당시)"
)
# 경과조치 명시 — FP 필터 (명시적으로 기득권 보호하는 경우)
_TRANSITIONAL_OK = re.compile(
    r"(종전의?\s*규정에\s*따른다"
    r"|종전\s*규정에\s*의한?\s*(?:허가|인가|등록|신고|처분|기득권)"
    r"|효력이\s*있다|유효하다|존속한다"
    r"|이미\s*(?:처리된|완료된|납부된|취득한|진행\s*중인))"
)
# 수익적 소급 — FP 필터
_BENEFICIAL = re.compile(
    r"(지원|보조금|혜택|급여|보상|환급|반환|지급|경감|면제|감면)\s*"
    r"(?:할\s*수\s*있다|한다|받을\s*수\s*있다|받는다)"
)
# 침익적 컨텍스트 — TP 부스트
_ADVERSE = re.compile(
    r"(처벌|제재|취소|정지|금지|벌금|과태료|과징금|징역|영업\s*(?:취소|정지)"
    r"|자격\s*(?:취소|정지|박탈)|손해배상|부담|납부|의무\s*부과)"
)
# 부칙 경과조치 관련 문구 — FP (이 법의 목적이 경과조치 자체인 경우)
_IS_TRANSITIONAL_ARTICLE = re.compile(
    r"(경과\s*조치|기존\s*사업자|종전에\s*따른|이미\s*(?:허가|등록|신고|인가|지정)"
    r"|이\s*법\s*시행\s*전\s*종전)"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose():
        return True
    # 경과조치 조문 자체 (부칙 조문 일 가능성)
    title = art.title or ""
    if re.search(r"(경과|부칙|적용례|소급|유효)", title):
        return True
    return False


class L05Retroactive:
    pattern_id = "L-05"
    pattern_name = "소급입법금지·경과조치부재"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        if is_blacklisted(law.name, "L-05"):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            text = art.full_text
            if not _RETROACTIVE.search(text):
                continue

            d = decompose(art)
            # 경과조치 명시 → FP
            if _TRANSITIONAL_OK.search(text):
                continue
            # 이 조문 자체가 경과조치인 경우
            if _IS_TRANSITIONAL_ARTICLE.search(text):
                continue

            has_adverse = bool(_ADVERSE.search(text))
            is_beneficial = bool(_BENEFICIAL.search(text))

            # 수익적 소급은 FP
            if is_beneficial and not has_adverse:
                continue

            m = _RETROACTIVE.search(text)
            if has_adverse:
                severity = "경고"
            elif d.type == ArticleType.PENALTY:
                severity = "경고"
            else:
                severity = "주의"

            idx += 1
            findings.append(make_finding(
                self, idx,
                PatternResult(
                    article=art,
                    severity=severity,
                    matched_text=m.group(0),
                    summary="소급적용 가능성: 시행 전 행위에 새 규정 적용, 경과조치 명시 없음"
                    + (" (침익적)" if has_adverse else ""),
                    fix_type="add_paragraph",
                    sub_check_id="L-05-a",
                ),
            ))
        return findings
