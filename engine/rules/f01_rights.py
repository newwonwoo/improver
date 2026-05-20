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
# Method B (D등급 법령 분석 — 할부·방문판매·온라인투자연계·전자상거래·전자금융·금융실명):
# 사업자 의무 조문 (소비자 보호 절차) 을 시민 권리 제한으로 오인하는 패턴
# Source: outputs/slm_step1_corpus.json 6개 D 등급 법령 top-finding 분석
# R5 examples (FPs):
#   할부거래법 제6조 (서면주의) — 사업자 정보제공 의무
#   금융실명거래법 제3조 (금융실명거래) — 금융회사 실명확인 의무
#   방문판매법 제9조 (청약철회 효과) — 사업자 환급 의무
#   온라인투자연계금융업법 제5조 (등록) — 등록요건 정의
#   전자상거래법 제5조 (전자문서 활용) — 사업자 전자문서 의무
_CONSUMER_PROTECTION_TITLE = re.compile(
    r"(서면주의|할부계약의?\s*서면|청약철회.{0,5}효과|환급|소비자.{0,10}보호"
    r"|전자문서의?\s*활용|약관.{0,5}명시|정보의?\s*제공|광고의?\s*기준)"
)
# 등록·허가 요건 정의 (요건 자체는 권리 제한 X)
_REGISTRATION_REQUIREMENT_TITLE = re.compile(
    r"^(등록|허가|인가|면허|지정|신고)(\s*요건)?(\s*등)?$"
    r"|(등록의?|허가의?|인가의?)\s*요건"
)
# 금융기관·사업자의 본질적 영업 의무 (실명거래·검사 응대 등)
_OPERATOR_BUSINESS_DUTY = re.compile(
    r"^(금융실명|실명거래|감독.{0,5}검사|보고.{0,5}검사|업무.{0,5}보고"
    r"|업무위탁|업무기준|업무방법|업무처리|업무절차"
    r"|모집\s*또는\s*매출|공개매수|모집(의?\s*신고)?)"
)
# Method B (의료법 분석): 의료직 직역 의무 조문
# R5 examples:
#   의료법 제15조 (진료거부 금지) - 의료인 진료의무
#   의료법 제17조의2 (처방전) - 의사 처방권 + 의약분업
#   의료법 제22조 (진료기록부) - 의료인 기록의무
#   의료법 제33조 (개설 등) - 의료기관 개설 제한
#   의료법 제64조 (개설 허가 취소) - F-03 영역
_MEDICAL_PROFESSION_TITLE = re.compile(
    r"(진료\s*거부|진료기록|처방전|면허|개설(\s*허가)?|의료인|의료광고"
    r"|무면허\s*의료|의료기관\s*개설|진료의?\s*\S{0,8}\s*제한)"
)
# Method B (할부거래법·방문판매법 분석): 민사 권리·의무 분배 조문
# R5 examples:
#   할부거래법 제8조 (청약의 철회) - 소비자 권리 보장
#   할부거래법 제11조 (할부계약 해제) - 사업자 권리 분배
#   할부거래법 제13조 (기한의 이익 상실) - 민법 일반조항
#   할부거래법 제16조 (소비자의 항변권) - 소비자 권리 보장
#   방문판매법 제9조 (청약철회 효과) - 사업자 환급 의무
_CIVIL_CONTRACT_TITLE = re.compile(
    r"(청약(의?)\s*철회|청약철회.{0,5}효과|청약철회.{0,5}통보"
    r"|할부계약(의?)\s*해제|계약(의?)\s*해제|계약(의?)\s*해지"
    r"|항변권|기한의?\s*이익|손해배상|위약금"
    r"|반환의?\s*의무|환급의?\s*의무|원상회복)"
)
# Method B (자본시장법 분석): 금융사업자 공시·신고·기록 의무
# R5 examples (FP):
#   자본시장법 제42조 (업무위탁) - 사업자 위탁 의무
#   자본시장법 제63조의2 (고객응대직원 보호조치) - 근로자 보호
#   자본시장법 제91조 (장부ㆍ서류 열람·공시) - 투자자 권리 보장
#   자본시장법 제119조 (모집·매출 신고) - 사업자 신고 의무
#   자본시장법 제137조 (공개매수설명서) - 사업자 공시 의무
_DISCLOSURE_RECORD_TITLE = re.compile(
    r"(장부.{0,5}서류|기록.{0,5}보존|기록.{0,5}유지|공시(의?)\s*\S{0,8}|설명서"
    r"|신고서|신고\s*의무|기재사항|공개매수|투자설명서|모집ㆍ?매출"
    r"|고객응대직원|보호\s*조치|직원\s*보호)"
)
# Method B (산업안전법 분석): 사업주 안전·보건 의무 조문 (근로자·시민 보호 목적)
# R5 examples (FP):
#   산업안전법 제25조 (안전보건관리규정 작성) - 사업주 안전관리 의무
#   산업안전법 제44조 (공정안전보고서) - 사업주 사고예방 의무
#   산업안전법 제124조 (석면농도기준 준수) - 석면해체업자 의무
#   산업안전법 제42조 (유해위험방지계획서) - 사업주 계획서 제출
#   산업안전법 제50조 (안전보건개선계획서) - 사업주 개선계획
_SAFETY_OBLIGATION_TITLE = re.compile(
    r"(안전보건관리규정|안전보건교육|공정안전보고서|유해위험방지계획서"
    r"|안전보건개선계획|석면농도기준|보호구|방호조치|화학물질안전"
    r"|위험성평가|작업환경측정|건강진단|특수건강진단)"
)
# Method B (자동차관리법 분석): 사업자 사후관리·금지행위 조문
# R5 examples (FP):
#   자동차관리법 제32조의2 (자기인증 사후관리) - 자동차제작자 의무
#   자동차관리법 제57조 (자동차관리사업자 금지 행위) - 사업자 부정행위 금지
_OPERATOR_FORBIDDEN_ACT_TITLE = re.compile(
    r"(.{0,15}\s*사업자\s*(등)?\s*(의)?\s*금지\s*행위"
    r"|사후관리|사후\s*관리|판매자의?\s*의무|제작자의?\s*책임"
    r"|제조업자의?\s*의무|영업자의?\s*의무|사업자의?\s*의무)"
)
# Method B (식품위생법 분석): 행정 표준 설정·시민 요청권 조문
# R5 examples (FP):
#   식품위생법 제7조 (식품 기준 및 규격) - 식약처장 표준 고시
#   식품위생법 제9조 (기구 및 용기 기준) - 식약처장 표준 고시
#   식품위생법 제16조 (소비자 등의 위생검사 요청) - 시민 요청권
_STANDARD_SETTING_TITLE = re.compile(
    r"(기준\s*및\s*규격|기준의?\s*고시|규격의?\s*고시|표준의?\s*고시"
    r"|위생검사\s*요청|위생검사등?\s*요청|검사\s*요청|점검\s*요청"
    r"|시민\s*제안|국민\s*제안)"
)
# 직역 자격법의 자격제한·자격취소 조문 (변호사·세무사·회계사·약사·의료인 등)
_PROFESSIONAL_QUAL_RESTRICTION = re.compile(
    r"^(자격\s*취소|자격\s*정지|등록\s*취소|면허\s*취소|면허\s*정지|등록의?\s*거부"
    r"|자격의?\s*\S{0,5}\s*제한|업무\s*정지)"
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
            # Method B (SLM 20법령 분석): 소비자 보호 절차 조문 = FP
            if _CONSUMER_PROTECTION_TITLE.search(title):
                continue
            # 등록·허가 요건 정의 조문 = FP
            if _REGISTRATION_REQUIREMENT_TITLE.search(title.strip()):
                continue
            # 금융기관·사업자 본질 영업 의무 (실명거래·감독응대) = FP
            if _OPERATOR_BUSINESS_DUTY.search(title.strip()):
                continue
            # 의료직 직역 의무 (진료거부 금지·처방전·진료기록 등) = FP
            if _MEDICAL_PROFESSION_TITLE.search(title):
                continue
            # 직역 자격제한·자격취소 = FP (F-03 영역)
            if _PROFESSIONAL_QUAL_RESTRICTION.search(title.strip()):
                continue
            # 민사 권리·의무 분배 조문 (청약철회·항변권·계약해제 등) = FP
            if _CIVIL_CONTRACT_TITLE.search(title):
                continue
            # 금융사업자 공시·신고·기록 의무 (자본시장법류) = FP
            if _DISCLOSURE_RECORD_TITLE.search(title):
                continue
            # 산업안전 사업주 안전·보건 의무 = FP (근로자 보호 목적)
            if _SAFETY_OBLIGATION_TITLE.search(title):
                continue
            # 사업자 사후관리·금지행위·제작자 책임 = FP (사업자 행위 제한)
            if _OPERATOR_FORBIDDEN_ACT_TITLE.search(title):
                continue
            # 행정 표준 설정·시민 요청권 = FP (식품위생법류)
            if _STANDARD_SETTING_TITLE.search(title):
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
