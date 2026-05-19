"""F-01 권리 제한 + 구제수단 부재 (설계서 §3.2 F-01)."""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from .base import PatternResult, make_finding


_STRONG = re.compile(
    r"(금지한다|할 수 없다|하지 못한다|박탈|자격을 상실|효력을 잃"
    r"|아니\s*된다|해서는\s*아니\s*된다|하여서는\s*아니\s*된다)"
    # 취소한다·정지한다는 F-03(처분조) 영역 — 중복 제거
)
_MID = re.compile(r"(제한한다|제한할 수 있다|배제|적용하지 아니한다|거부할 수 있다)")
_WEAK = re.compile(r"조건을 붙일 수 있다")  # "제한" 단독은 제거 (너무 광범위)
_REMEDY = re.compile(r"(이의신청|이의 신청|구제|청문|소명|행정소송|행정심판|불복)")
# TP 필터: 수범자가 일반 국민/소비자/근로자인 경우만
_CITIZEN = re.compile(r"(국민|소비자|이용자|가입자|근로자|환자|세입자|임차인|청구권자|모든\s*사람|일반인)")
# 일반 prohibitive — "누구든지" 는 보편 금지로 더 약한 신호
_UNIVERSAL_PROHIBITION = re.compile(r"누구든지")
# FP 필터: 처벌/제재 조문에서의 금지 (이미 E-05/F-05에서 처리)
_SANCTION_CONTEXT = re.compile(r"(징역|벌금|과태료|과징금|형사|처벌|제재)")
# FP 필터: 사업자 행위 제한 (국민 권리 침해 아님)
_OPERATOR = re.compile(
    r"(사업자|판매업자|제조업자|수입업자|서비스업자|운영자|공급자"
    r"|세무사|변호사|회계사|법무사|변리사|관세사|건축사|의사|약사|간호사"
    r"|공단|공사|재단|협회|조합|진흥원|위원회"
    r"|검정기관|승인기관|시험기관|인증기관|평가기관|보증기관|혈액원|의료기관"
    r"|선박의?\s*소유자|선박소유자|차주"
    r"|기관의?\s*장은|기관장은|장의?\s*장은)"
)
# 주체 식별: "X는 ... 아니 된다" 패턴 (술부 가까이)
# X가 _OPERATOR_SUBJECT 이면 사업자 의무 (시민 권리 제한 아님)
# 괄호 안 부연설명은 허용
_OPERATOR_SUBJECT = re.compile(
    r"^[^\.]{0,10}?(사업자|판매업자|제조업자|수입업자|서비스업자|운영자|공급자"
    r"|세무사|변호사|회계사|법무사|변리사|관세사|건축사|의사|약사"
    r"|공단|공사|재단|협회|조합|진흥원"
    r"|검정기관|승인기관|시험기관|인증기관|평가기관|보증기관|혈액원|의료기관"
    r"|선박의?\s*소유자|선박소유자|임대인"
    r"|기관의?\s*장|기관장)(?:\([^)]*\))?\s*[은이는]",
    re.MULTILINE,
)
# FP 필터: 사업주/고용주가 주체 → 근로자 보호 조문 (권리 제한 아님)
_EMPLOYER_SUBJECT = re.compile(
    r"(사업주|고용주|사용자|운영자|고용인|고용하고\s*있는\s*자|임대인).{0,200}(하지\s*못한다|아니\s*된다|할\s*수\s*없다|거절하지\s*못한다)"
)
# FP 필터: 자동 자격 상실 (사건 발생 시 자동 상실 — 재량적 박탈 아님)
_AUTOMATIC_STATUS_LOSS = re.compile(
    r"(피보험자격을?\s*상실한다|회원자격을?\s*상실한다"
    r"|다음\s*각\s*호의?\s*어느\s*하나에?\s*해당하는\s*날에.{0,30}상실"
    r"|이직한\s*날의?\s*다음\s*날|자격이\s*당연히)"
)
# FP 필터: 위원·임원 자격 제한 (자격조건 정의 — 권리 제한 아님)
_OFFICER_QUAL = re.compile(
    r"(위원에?\s*임명될\s*수\s*없다|위원이\s*될\s*수\s*없다"
    r"|임원이?\s*될\s*수\s*없다|임원으로\s*선임될\s*수\s*없다"
    r"|이사가?\s*될\s*수\s*없다|감사가?\s*될\s*수\s*없다"
    r"|투표\s*참관인이?\s*될\s*수\s*없다|선거\s*참관인이?\s*될\s*수\s*없다"
    r"|감독\s*위원이?\s*될\s*수\s*없다|시험\s*위원이?\s*될\s*수\s*없다)"
)
# Method B (F-01_part01) 검증으로 도출된 신호:
# Source: outputs/rule_verification_responses/F-01_part01.json :: new_signals
# 1. 협조요청·자료요청 조문 — 시민 권리 제한 아님
_DATA_COOPERATION_TITLE = re.compile(
    r"(자료의?\s*협조요청|자료\s*제공\s*요청|자료\s*제출\s*요구"
    r"|자료의?\s*제공\s*요청|정보\s*제공\s*요청)"
)
# 2. 행정처분 조문 (F-03 영역)
_ADMIN_DISPOSITION_TITLE = re.compile(
    r"(인가\s*취소|등록\s*취소|면허\s*취소|영업\s*정지|업무\s*정지|폐업\s*신고|직권\s*말소"
    r"|징계\s*심의|규제특례\s*지정의?\s*취소)"
)
# 3. 시설·법인·기관 책임자 의무 (사업자 의무 — 시민 권리 X)
_INSTITUTION_OBLIGATION_TITLE = re.compile(
    r"(시설\s*완성검사|중앙행정기관의?\s*설치|기관의?\s*보조기관|기관의?\s*조직"
    r"|정부조직)"
)
# TP 필터: 실질적 권리 박탈 키워드
_DEPRIVATION = re.compile(
    r"(자격을?\s*정지|허가를?\s*취소|등록을?\s*취소|인가를?\s*취소|면허를?\s*취소"
    r"|자격을?\s*상실|직위를?\s*해제|영업을?\s*정지)"
)


class F01Rights:
    pattern_id = "F-01"
    pattern_name = "권리 제한"
    category = "공정성"

    def scan(self, law: Law) -> list[Finding]:
        findings: list[Finding] = []
        idx = 0
        articles = law.articles
        for i, art in enumerate(articles):
            if art.is_penalty() or art.is_purpose() or art.is_definition():
                continue
            text = art.full_text
            # 단순 형사처벌 컨텍스트는 제외 (F-05 영역)
            if _SANCTION_CONTEXT.search(text):
                continue
            # 사업주/고용주가 근로자를 보호하는 조문 (근로자 권리 제한 아님)
            if _EMPLOYER_SUBJECT.search(text):
                continue
            # 자동 자격 상실 (사건 발생 시 자동) — 재량적 박탈 아님
            if _AUTOMATIC_STATUS_LOSS.search(text):
                continue
            # 위원·임원 자격 제한 (자격 정의 조문)
            if _OFFICER_QUAL.search(text):
                continue
            # 주로 사업자 행위 제한 (국민 권리 침해 아님)
            if _OPERATOR.search(text) and not _CITIZEN.search(text):
                continue
            # Method B (F-01_part01 verdicts): 협조요청·행정처분·정부조직 = FP
            # Source: outputs/rule_verification_responses/F-01_part01.json
            # R5 examples (verdicts):
            #   F-01-001@건강검진기본법 (FP — 자료의 협조요청)
            #   F-01-005@독립유공자예우에관한법률 (FP — 자료 제공 요청)
            #   F-01-004@공공감사에관한법률 (FP — 자료 제출 요구)
            #   F-01-012@감정평가법 (FP — 인가취소 = F-03 영역)
            #   F-01-006@정보통신진흥특별법 (FP — 규제특례 지정 취소)
            #   F-01-001@정부조직법 (FP — 정부조직 설치)
            title = art.title or ""
            if _DATA_COOPERATION_TITLE.search(title):
                continue
            if _ADMIN_DISPOSITION_TITLE.search(title):
                continue
            if _INSTITUTION_OBLIGATION_TITLE.search(title):
                continue
            # 조문 제목이 사업자·기관 준수사항/광고/금지 조문이면 FP
            if any(k in title for k in (
                "준수사항", "준수 사항", "행위제한", "광고", "영업제한",
                "사업자의", "기관의 의무", "기관의 장",
            )):
                continue
            # 항별로 제한 주체 검토 — 제한 패턴이 있는 항의 주체가 모두 사업자/기관이면 FP
            if art.paragraphs:
                restricted_paras = [
                    p for p in art.paragraphs
                    if _STRONG.search(p.text) or _DEPRIVATION.search(p.text) or _MID.search(p.text) or _WEAK.search(p.text)
                ]
                if restricted_paras:
                    op_subj_count = sum(1 for p in restricted_paras if _OPERATOR_SUBJECT.search(p.text))
                    if op_subj_count == len(restricted_paras):
                        continue

            if _STRONG.search(text) or _DEPRIVATION.search(text):
                strength = "강"
            elif _MID.search(text):
                strength = "중"
            elif _WEAK.search(text):
                strength = "약"
            else:
                continue

            # 구제수단: 동일 조문 또는 ±2조 범위 (설계서 §3.2)
            window = articles[max(0, i - 2): min(len(articles), i + 3)]
            has_remedy = any(_REMEDY.search(a.full_text) for a in window)
            is_citizen = bool(_CITIZEN.search(text))
            # "누구든지" 는 보편 금지 — 시민으로 인정하되 한 단계 낮은 심각도
            is_universal = bool(_UNIVERSAL_PROHIBITION.search(text))
            # 법령 단위 형벌 조문이 존재하면 누구든지-형 금지는 E-05/벌칙에서 처리 → 약한 신호
            law_has_penalty = any(a.is_penalty() for a in articles)

            if is_universal and not is_citizen:
                # "누구든지"만 있는 경우: 동일 법령에 벌칙이 있으면 보편 금지가 적절 처리됨 → 약한 신호
                if law_has_penalty:
                    is_citizen = True
                    # universal + 강 + remedy 없음 → 경고 (심각 아님)
                    if strength == "강" and not has_remedy:
                        severity = "경고"
                        sub_check = "F-01-e"
                        idx += 1
                        findings.append(
                            make_finding(
                                self,
                                idx,
                                PatternResult(
                                    article=art,
                                    severity=severity,
                                    matched_text="권리 제한(보편)",
                                    summary="보편적 금지(누구든지) — 별도 구제수단 부재",
                                    fix_type="add_paragraph",
                                    sub_check_id=sub_check,
                                ),
                            )
                        )
                        continue
                else:
                    # 형벌 없는 보편 금지는 진정한 F-01 TP
                    is_citizen = True

            if strength == "강" and is_citizen and not has_remedy:
                severity = "심각"
            elif strength == "강" and is_citizen:
                severity = "경고"
            elif strength == "강":
                continue  # 비-시민 대상 강한 제한 → F-03/F-05 영역
            elif strength == "중" and not has_remedy and is_citizen:
                severity = "주의"
            elif strength == "약" and is_citizen:
                severity = "개선"
            else:
                continue

            sub_check = "F-01-e" if not has_remedy else "F-01-a"
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"권리 제한({strength})",
                        summary=(
                            f"{strength}한 권리 제한"
                            + (", 수범자 대상" if is_citizen else "")
                            + (", 구제수단 부재" if not has_remedy else "")
                        ),
                        fix_type="add_paragraph" if not has_remedy else "replace",
                        sub_check_id=sub_check,
                    ),
                )
            )
        return findings
