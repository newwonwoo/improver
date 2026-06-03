"""L-04 포괄위임금지 — 대통령령 등에 대한 포괄적 위임 (BAI-01·MOL-01 기반).

헌법 제75조 · 대법원 2016두64975: 위임의 목적·내용·범위를 구체적으로 한정해야 한다.
"필요한 사항" + 구체적 기준 없이 하위법령으로 넘기는 조항은 포괄위임 결함.

TP 신호:
  - "필요한 사항은 [령/규칙/고시]으로 정한다" 형식 + 앞 조항에 기준 無
  - "관계 기관의 장이 정하는 바에 따른다" (비법령 위임)
  - "내부 지침" / "업무 규정" 으로 위임

FP 필터:
  - 앞 항에 구체적 기준·범위·요건이 명시됨 ("제1항에 따른 기준·절차")
  - 기술적 위임 (서식, 수수료, 제출방법, 신청절차)
  - 법원규칙·국회규칙 위임 (헌법상 별도 수권)
  - 목적·정의·벌칙 조문
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_blacklisted
from .base import PatternResult, make_finding

# 포괄위임 핵심 패턴 — "필요한 사항은 [령/규칙/고시]으로 정한다"
_BLANKET = re.compile(
    r"필요한\s*사항(?:은|이|을)?\s*(?:대통령령|총리령|부령|[가-힣]+부령"
    r"|행정규칙|고시|훈령|예규|지침|내부\s*규정|업무\s*규정|내부\s*지침|업무\s*지침)으로\s*정한다"
)
# 비법규 위임 — 법령이 아닌 기관 내부 기준으로 위임
_NON_LEGAL = re.compile(
    r"(관계\s*기관의?\s*장|해당\s*기관의?\s*장|소관\s*기관의?\s*장)\s*이?\s*정하는\s*바에?\s*따른다"
)
# 기술적/절차적 위임 — FP 필터 (서식, 수수료, 방법 등 단순 절차)
_TECHNICAL = re.compile(
    r"(서식|수수료|제출\s*방법|신청\s*절차|처리\s*절차|제출\s*기한|수령\s*방법"
    r"|수령\s*절차|통지\s*방법|교부\s*방법|열람\s*방법|공고\s*방법)"
)
# 구체적 기준 명시 — FP 필터 (앞 항에서 이미 기준이 나열된 경우)
_CONCRETE_CRITERIA = re.compile(
    r"(제\d+항|제\d+호|각\s*호|다음\s*각\s*호|전항|해당\s*각\s*호)에?\s*따른?\s*"
    r"(기준|요건|범위|절차|방법|조건|세부\s*사항|사항)"
)
# 법원규칙·국회규칙 — 헌법상 별도 수권으로 FP
_COURT_RULES = re.compile(r"(대법원\s*규칙|국회\s*규칙|헌법재판소\s*규칙|중앙선거관리위원회\s*규칙)으로\s*정한다")
# 침익적 컨텍스트 — TP 부스트 (국민 권리 제한/의무 부과)
_ADVERSE = re.compile(
    r"(권리를?\s*제한|의무를?\s*부과|행위를?\s*금지|처분|취소|정지|제재|과태료|벌칙|이하의?\s*과태료)"
)


def _is_fp_article(art: Article) -> bool:
    if art.is_definition() or art.is_purpose() or art.is_penalty():
        return True
    return False


class L04BlanketDelegation:
    pattern_id = "L-04"
    pattern_name = "포괄위임금지"
    category = "적법성"

    def scan(self, law: Law) -> list[Finding]:
        if is_blacklisted(law.name, "L-04"):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            d = decompose(art)
            text = art.full_text

            has_blanket = bool(_BLANKET.search(text))
            has_non_legal = bool(_NON_LEGAL.search(text))
            if not has_blanket and not has_non_legal:
                continue

            # 법원규칙·국회규칙 — FP
            if _COURT_RULES.search(text):
                continue
            # 기술적 위임만 있는 경우 — FP
            if has_blanket and _TECHNICAL.search(text) and not _ADVERSE.search(text):
                # 본문에 침익적 맥락 없으면 절차 위임으로 판단
                if d.type not in (ArticleType.DISPOSITION, ArticleType.PROHIBITION, ArticleType.PENALTY):
                    continue
            # 구체적 기준이 이미 앞 항에 명시된 경우 — 일부 FP 감쇄
            has_concrete = bool(_CONCRETE_CRITERIA.search(text))

            has_adverse = bool(_ADVERSE.search(text))

            if has_non_legal:
                severity = "경고"
            elif has_adverse and not has_concrete:
                severity = "경고"
            elif has_adverse and has_concrete:
                severity = "주의"
            elif not has_concrete:
                severity = "주의"
            else:
                severity = "개선"

            matched = (_NON_LEGAL.search(text) or _BLANKET.search(text)).group(0)
            idx += 1
            findings.append(make_finding(
                self, idx,
                PatternResult(
                    article=art,
                    severity=severity,
                    matched_text=matched,
                    summary="포괄위임: 구체적 기준·범위 없이 하위법령으로 위임"
                    + (" (침익적 사항 포함)" if has_adverse else ""),
                    fix_type="add_paragraph",
                    sub_check_id="L-04-a" if has_non_legal else "L-04-b",
                ),
            ))
        return findings
