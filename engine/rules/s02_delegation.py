"""S-02 위임 검증 — 단계1 (포괄위임) + 단계2 (하위법령 이행).

설계서 §3.2 S-02: MCP 인덱스 사용 가능 시 시행령 이행 여부도 함께 판정.
포괄위임: 구체적 기준 없이 "그 밖에 필요한 사항" 등 catch-all만 있는 경우.
"""
from __future__ import annotations

import re

from ..mcp import LawIndex, load_default_index
from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType
from .base import PatternResult, make_finding


_PRIMARY = re.compile(r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정(?:하|한|할|해|함)")
# 포괄위임 패턴: 구체 기준 없이 "그 밖에/기타 필요한 사항"만 위임
_CATCHALL_DELEG = re.compile(
    r"(그\s*밖에|기타)\s*.{0,30}(필요한\s*사항|에\s*관한\s*사항|에\s*관하여\s*필요한)\s*은?\s*"
    r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정"
)
# TP 필터: 조문 제목이나 내용에 위임 대상이 명확한 경우
_SPECIFIC_SUBJECT = re.compile(
    r"(기준|절차|방법|범위|요건|한도|서식|서류|자격|요율|금액|기간|규모)"
    r".{0,30}(대통령령|시행령|총리령|부령)으?로\s*정"
)
# FP 필터: 기술적 사양 위임 (불가피한 위임)
_TECH_SPEC = re.compile(
    r"(서식|양식|전산|전자|전기|기술적|규격|통신|정보시스템)"
    r".{0,30}(대통령령|시행령|부령)으?로\s*정"
)
# FP 필터: 그 밖에 앞에 구체 항목들이 나열된 경우 (조직 명칭·운영 등)
# 예: "명칭, 관할 구역, 조직 및 정원, 그 밖에 필요한 사항"
_ENUMERATED_BEFORE_CATCHALL = re.compile(
    r"(명칭|관할|구역|조직|정원|구성|위원|임명|위촉|운영|소재지|영수증|기부금)"
    r"[^.]{0,80}(그\s*밖에|기타)"
)
# FP 필터: 위원회/협의회/평의원회 등 자문기구의 운영 위임은 통상 적정
_COMMITTEE_TITLE = re.compile(r"(위원회|심의회|평의원회|이사회|협의회|운영위원회|자문위원회|소위원회)")
# FP 필터: catch-all 뒤에 "구성·운영" 등이 오는 경우 위원회 운영 위임
_CATCHALL_OPERATION = re.compile(
    r"(그\s*밖에|기타)\s*[^.]{0,60}(구성|운영|회의|의사|회칙|운영규정)"
    r"[^.]{0,40}(대통령령|시행령|총리령|부령)"
)


class S02Delegation:
    pattern_id = "S-02"
    pattern_name = "위임 검증"
    category = "구조"

    def __init__(self, index: LawIndex | None = None, *, check_decree: bool = False):
        # check_decree=False by default until enforcement decree index is populated
        self._index = index
        self._check_decree = check_decree

    def _idx(self) -> LawIndex | None:
        if self._index is not None:
            return self._index
        if self._check_decree:
            try:
                self._index = load_default_index()
                return self._index
            except Exception:
                self._check_decree = False
        return None

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        index = self._idx()

        delegating: list[Article] = []
        catchall_arts: list[Article] = []

        for art in law.articles:
            if art.is_definition() or art.is_purpose() or art.is_penalty():
                continue
            # R2 구조 신호: COMMITTEE 타입 — 위원회 운영 위임은 자체 표준 (구성·운영 위임 자연스러움)
            d = decompose(art)
            if d.type == ArticleType.COMMITTEE:
                continue
            text = art.full_text
            if not _PRIMARY.search(text):
                continue
            delegating.append(art)

            # 포괄위임 감지: catch-all 표현만 있고 구체적 주제 없음
            if not _CATCHALL_DELEG.search(text):
                continue
            # 기술적 사양 위임은 FP
            if _TECH_SPEC.search(text):
                continue
            # FP: 조직·운영 구체 항목들이 그 밖에 앞에 나열된 경우
            if _ENUMERATED_BEFORE_CATCHALL.search(text):
                continue
            # FP: 위원회·협의회 등 자문기구 조문 — catch-all delegation은 통상 운영 위임
            title = art.title or ""
            if _COMMITTEE_TITLE.search(title):
                continue
            # FP: 그 밖에 + 구성·운영 + 대통령령 — 위원회 운영 위임
            if _CATCHALL_OPERATION.search(text):
                continue
            # 구체적 기준/절차도 함께 위임되면 정상 입법 패턴 → 보고하지 않음
            has_specific = bool(_SPECIFIC_SUBJECT.search(text))
            if has_specific:
                continue
            severity = "경고"
            catchall_arts.append(art)
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text="포괄위임",
                        summary="포괄위임: 위임 범위 불명확 (그 밖에 필요한 사항)"
                        + (" + 구체 기준 병기" if has_specific else ""),
                        fix_type="replace",
                    ),
                )
            )

        # 단계2: 하위법령 이행 검증 (MCP 인덱스)
        if index is None or not delegating:
            return findings

        parent = index.find(law.name)
        if parent is None:
            return findings
        if not parent.get("has_enforcement_decree"):
            # 시행령 자체 없음 → 위임 다수면 심각
            if len(delegating) >= 5:
                idx += 1
                findings.append(
                    make_finding(
                        self,
                        idx,
                        PatternResult(
                            article=delegating[0],
                            severity="심각",
                            matched_text="시행령 부재",
                            summary=f"위임 {len(delegating)}건이 있으나 시행령 자체 미제정",
                            fix_type="sub_legislation",
                        ),
                    )
                )
            return findings

        decree = index.decree_for(law.name)
        if decree is None:
            return findings
        decree_arts = set(decree.get("article_numbers", []))
        unmatched = 0
        for art in delegating:
            base = art.number_raw
            try:
                b = int(base)
            except ValueError:
                continue
            near = any(
                a.isdigit() and abs(int(a) - b) <= 3 for a in decree_arts
            )
            if not near:
                unmatched += 1
        # 미이행이 5건 이상인 경우만 보고 (노이즈 감소)
        if unmatched >= 5:
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=delegating[0],
                        severity="경고",
                        matched_text="시행령 이행 미확인",
                        summary=f"위임 {unmatched}건 대응 시행령 조문 미확인",
                        fix_type="sub_legislation",
                    ),
                )
            )
        return findings
