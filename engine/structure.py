"""조문 구조화 분해기 (docs/ENGINE_PRINCIPLES.md R2).

raw text → 의미 단위로 분해.  룰은 raw `full_text` 가 아니라 이 구조에 대해 동작.

기본 단위:
    ArticleType : 정의|벌칙|위임|처분|보고|위원회|절차|일반|...
    Subject     : 행정청|사업자|시민|공무원|기관|UNKNOWN
    Modal       : MUST|MAY|PROHIBITED|DEFINITION|NONE
    ActionKind  : GRANT(부여)|REVOKE(취소·박탈)|REPORT|REGISTER|DELEGATE|RESTRICT|DEFINE|...

LLM 검증 데이터셋(2,318 verdicts)에서 추출한 패턴에 근거.  엔진의 모든 룰이
이 분해 결과를 받아 동작하면 키워드급 → SLM급으로의 단계 상승이 가능.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .schema import Article


class ArticleType(str, Enum):
    DEFINITION = "DEFINITION"     # 정의 (이 법에서 ... 말한다)
    PENALTY = "PENALTY"           # 벌칙 (N년 이하 징역/벌금/과태료)
    DELEGATION = "DELEGATION"     # 위임 (대통령령·시행령으로 정한다)
    DISPOSITION = "DISPOSITION"   # 처분 (취소·정지·과징금)
    REPORTING = "REPORTING"       # 보고·자료제출
    COMMITTEE = "COMMITTEE"       # 위원회·심의회 운영
    PROCEDURE = "PROCEDURE"       # 절차 (인허가 처리·신청)
    PROHIBITION = "PROHIBITION"   # 금지 (아니 된다)
    PURPOSE = "PURPOSE"           # 목적
    PLAN = "PLAN"                 # 계획 수립
    GENERAL = "GENERAL"           # 기타
    EMPTY = "EMPTY"               # 삭제·미시행 단문


class Subject(str, Enum):
    AGENCY = "AGENCY"             # 행정청 (장관·청장·시도지사·공단·공사·위원회)
    OPERATOR = "OPERATOR"         # 사업자·전문직·기관
    CITIZEN = "CITIZEN"           # 국민·시민·이용자·신청인
    OFFICIAL = "OFFICIAL"         # 공무원·소속 직원
    EVERYONE = "EVERYONE"         # 누구든지
    UNKNOWN = "UNKNOWN"


class ActionKind(str, Enum):
    """행위 종류 — Method B 검증으로 정제된 10개 카테고리.

    R2 (docs/ENGINE_PRINCIPLES.md): 룰이 구조화 + 역할 + 행위 종류 단위로
    동작하면 level 3 진입. 단어 매칭이 아닌 의미적 행위 식별.
    """
    GRANT = "GRANT"               # 허가·인가·승인·지정·면허 부여
    REVOKE = "REVOKE"             # 취소·박탈·정지·말소·해임
    IMPOSE = "IMPOSE"             # 과징금·과태료·시정명령·조치명령 부과
    REPORT = "REPORT"             # 보고·통보·신고·자료제출
    REGISTER = "REGISTER"         # 등록·기록·기재·비치
    DELEGATE = "DELEGATE"         # 위임 (대통령령·시행령으로 정한다)
    RESTRICT = "RESTRICT"         # 제한·금지·아니 된다
    DEFINE = "DEFINE"             # 정의 (말한다·본다)
    INVESTIGATE = "INVESTIGATE"   # 조사·검사·확인
    HEAR = "HEAR"                 # 청문·의견청취·심의
    NONE = "NONE"                 # 미분류


class Modal(str, Enum):
    MUST = "MUST"                 # 하여야 한다
    MAY = "MAY"                   # 할 수 있다
    PROHIBITED = "PROHIBITED"     # 아니 된다 / 못한다
    DEFINITION = "DEFINITION"     # 말한다 / 본다
    NONE = "NONE"


# 분류용 정규식 (LLM verdict 데이터 기반 캘리브레이션)
_DEFINITION_RX = re.compile(
    r"(이\s*법에서\s*(\"|『).{0,40}(\"|』).{0,20}(이?란|는|함은).{0,80}말한다"
    r"|이\s*법에서\s*사용하는\s*용어의?\s*뜻"
    r'|"[^"]+"\s*(이|라)?\s*(란|함은).{0,80}말한다)'
)
_PENALTY_RX = re.compile(
    r"(\d+년\s*이하의?\s*징역|\d+(천|만|억)?\s*원\s*이하의?\s*벌금|과태료에\s*처한다"
    r"|사형|무기징역)"
)
_DELEGATION_RX = re.compile(
    r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정(?:하|한|할|해|함)"
)
_DISPOSITION_RX = re.compile(
    r"(취소(한다|하여야|할\s*수\s*있다)|정지(한다|하여야|할\s*수\s*있다)"
    r"|영업정지|업무정지|등록말소|허가취소|면허취소|자격취소|지정취소"
    r"|과징금을?\s*부과|폐쇄(명령|할\s*수\s*있다))"
)
_REPORTING_RX = re.compile(
    r"(보고하여야|보고하게|자료를?\s*제출|결과를?\s*보고|현황을?\s*보고)"
)
_COMMITTEE_RX = re.compile(r"(위원회|심의회|평의원회|이사회|협의회).{0,40}(둔다|설치한다|구성한다)")
_PROCEDURE_RX = re.compile(
    r"((인가|허가|승인|등록|면허|지정)을?\s*받(아야|을\s*수\s*있다)"
    r"|신청을?\s*받은|신청서를?\s*제출|심사하여야)"
)
# PROHIBITION: 행위 금지에 한정. 면책 "책임을 지지 아니한다"는 제외.
_PROHIBITION_RX = re.compile(
    r"(하여서는\s*아니\s*된다|하지\s*못한다|할\s*수\s*없다)"
    r"(?!.*책임을\s*지지)"
)
_PLAN_RX = re.compile(r"(기본계획|종합계획|시행계획|진흥계획).{0,30}(수립|마련|확정)")
_PURPOSE_RX = re.compile(r"함을\s*목적으로\s*한다")

# ActionKind 분류 — Method B 검증 패턴
_ACTION_GRANT_RX = re.compile(
    r"(허가|인가|승인|지정|면허|등록|인증)을?\s*(한다|할\s*수\s*있다|하여야|하며|받(아야|을\s*수))"
)
_ACTION_REVOKE_RX = re.compile(
    r"(취소(한다|하여야|할\s*수\s*있다)|박탈|정지(한다|하여야|할\s*수\s*있다)"
    r"|말소|해임|폐쇄(명령|할\s*수)|효력을?\s*잃)"
)
_ACTION_IMPOSE_RX = re.compile(
    r"(과징금을?\s*부과|과태료를?\s*부과|시정\s*명령|조치\s*명령|개선\s*명령"
    r"|시정할\s*것을\s*명|이행을?\s*명)"
)
_ACTION_REPORT_RX = re.compile(
    r"(보고하여야|보고하게|통보하여야|신고하여야|제출하여야|자료를?\s*제출)"
)
_ACTION_REGISTER_RX = re.compile(
    r"(등록하여야|기록하여야|기재하여야|비치하여야|보존하여야|작성하여야)"
)
_ACTION_DELEGATE_RX = _DELEGATION_RX  # 위에 정의됨
_ACTION_RESTRICT_RX = _PROHIBITION_RX  # 금지
_ACTION_DEFINE_RX = re.compile(r"(말한다|본다|이라\s*한다)")
_ACTION_INVESTIGATE_RX = re.compile(
    r"(조사할\s*수\s*있다|조사하여야|검사할\s*수\s*있다|검사하여야|확인할\s*수\s*있다)"
)
_ACTION_HEAR_RX = re.compile(
    r"(청문을?\s*(실시|하여야|할\s*수)|의견을?\s*청취|의견제출의?\s*기회"
    r"|이의\s*신청|소명할\s*기회)"
)

# Subject 식별 (문장 시작/항 시작 부근)
_AGENCY_SUBJECT_RX = re.compile(
    r"(장관|청장|시\s*[ㆍ·]\s*도지사|시ㆍ도지사|시도지사|시장|군수|구청장"
    r"|공사|공단|재단|위원회|위원장|원장|총장|이사장|기관장)[은는이가]"
)
_OPERATOR_SUBJECT_RX = re.compile(
    r"(사업자|판매업자|제조업자|수입업자|서비스업자|운영자|공급자"
    r"|세무사|변호사|회계사|법무사|변리사|관세사|건축사|의사|약사"
    r"|혈액원|의료기관|검정기관|시험기관|인증기관"
    r"|선박(의|소유자)|차주|임대인)[은는이가]"
)
_CITIZEN_SUBJECT_RX = re.compile(
    r"(국민|소비자|이용자|가입자|근로자|환자|세입자|임차인|신청인|청구인)[은는이가]"
)
_OFFICIAL_SUBJECT_RX = re.compile(r"(소속\s*공무원|소속\s*직원|공무원)[은는이가]")
_EVERYONE_SUBJECT_RX = re.compile(r"누구든지")

# 빈 조문 (삭제)
_EMPTY_RX = re.compile(r"삭제")

# 호(item) 단위 캐치올 패턴 — S-04/E-01/G-01 공통 활용 신호
# 3단계 강도로 분류:
#   STRICT  : "그 밖에 (대통령령/총리령/부령/규칙)으로 정하는" — 위임형 캐치올
#   LOOSE   : "그 밖에 (필요한|정하는) 사항"            — 일반 캐치올
#   WEAK    : "그 밖의 ~" 시작                           — 잔여 호
_CATCHALL_STRICT = re.compile(r"그\s*밖에.{0,80}(대통령령|총리령|부령|규칙)으?로\s*정하는")
# LOOSE: "그 밖에 …정하는·필요한·요청하는·인정하는·결정하는 [수식어] 사항/업무" — 일반 캐치올
# (장관·청장 등이 임의로 추가하는 사항도 동일한 결함 패턴)
# .{0,30} 으로 수식어 허용 (예: "...정하는 치매 관련 업무")
_CATCHALL_LOOSE = re.compile(
    r"그\s*밖에.{0,80}(정하는|필요한|요청하는|인정하는|결정하는|위탁받은|위임받은)"
    r".{0,30}(사항|업무|사업|행위|일|것)"
)
_CATCHALL_WEAK = re.compile(r"^그\s*밖의?\s")
# 단서 (다만) 패턴 — G-01 공통 활용 (per-paragraph & article-total 카운트)
_PROVISO_RX = re.compile(r"다만[,\s]")

# 처분 강도 분류 — F-03·S-04·G-01 공통 활용
# STRONG : 영업정지·인허가/등록/면허/허가/지정/자격 취소·폐쇄명령·해임요구
_DISP_STRENGTH_STRONG = re.compile(
    r"(영업정지|인허가\s*취소|등록\s*취소|폐쇄\s*명령|해임\s*요구"
    r"|인가\s*취소|허가\s*취소|면허\s*취소|지정\s*취소|자격\s*취소)"
)
# MID    : 시정명령·과징금·업무정지
_DISP_STRENGTH_MID = re.compile(r"(시정\s*명령|과징금|업무\s*정지)")
# WEAK   : 시정권고·개선명령·경고
_DISP_STRENGTH_WEAK = re.compile(
    r"(시정\s*권고|개선\s*명령|경고\s*처분|구두\s*경고|서면\s*경고|공식\s*경고"
    r"|경고를\s*할\s*수\s*있다|경고를\s*하여야)"
)

# 청문·사전절차 신호
_HEARING_RX = re.compile(
    r"(청문|의견제출|의견\s*제출|이의신청|이의\s*신청"
    r"|사전\s*통지|미리\s*알려|미리\s*통지|불복|행정심판|행정소송"
    r"|의견을?\s*들어야|의견을?\s*제출할\s*수\s*있다)"
)
# 처분 기준 신호 (별표·기준·등급·다음 각 호의 어느 하나)
_STANDARD_RX = re.compile(
    r"(별표|기준|등급|다음\s*각\s*호의?\s*어느\s*하나에?\s*해당"
    r"|다음\s*각\s*호와\s*같다|위반행위|위반\s*횟수|적합하지\s*아니)"
)

# 인용 법령명 패턴 — L-01/L-02/L-03 공통 활용
_CITED_LAW_RX = re.compile(r"「([^」]+)」")
# 인용 법령명 + 제N조 cross-ref — L-02/L-03
_CITED_ARTICLE_RX = re.compile(r"「([^」]+)」\s*제(\d+)조(?:의\d+)?(?:\s*제\d+항)?")
# 동일법 내부 조문 인용 (제N조 / 제N조제M항) — E-01·F-03·G-02 활용
_INTERNAL_ARTICLE_RX = re.compile(r"제(\d+)조(?:의\d+)?(?:제(\d+)항)?")

# 가독성 측정 패턴 — prompts.chat Text Analyzer Tool 영감
# 한국 법령 가독성 변형 (Flesch-Kincaid 모티프)
_WORD_RX = re.compile(r"\S+")
_SENTENCE_END_RX = re.compile(r"[.!?]|\.다(?=\s|$)|한다(?=\s|$)")
_HANJA_RX = re.compile(r"[一-鿿]")
_PARENTHESIS_RX = re.compile(r"\([^)]+\)|「[^」]+」|『[^』]+』")

# F-04 활용 — 의사표시 의제 패턴
_DEEMED_ASSENT_RX = re.compile(
    r"(동의한?\s*것으로\s*본다|승낙한?\s*것으로\s*본다"
    r"|이의가\s*없는?\s*것으로\s*본다|갱신된?\s*것으로\s*본다"
    r"|승인한?\s*것으로\s*본다|취임한?\s*것으로\s*본다)"
)
# 시간 기한 패턴 — N일/N월/N년 (F-04·G-02 활용)
_TIME_DEADLINE_RX = re.compile(r"(\d+)\s*(일|개월|년)\s*(이내|이상|이하|이전)")

# E-01 조건 복잡도 — 효율성 신경망 활용
_CONDITION_LEAD_RX = re.compile(r"(경우|때|요건)(?:에는|에)?")
_CONDITION_LINK_RX = re.compile(r"(및|또는|이고|이며|하고|하며)")
_NESTED_HINT_RX = re.compile(r"(에 해당하는 경우로서|충족하고|갖추어야 하며|모두 충족|다음 각 호의)")

# 사법·국회·진상규명 도메인 법령 — 대부분의 규제 결함 룰 적용 외
# Source: verdict 분석 (F-03/F-04/G-03/G-04/L-01/L-03/S-04 각각 0 TP)
_JUDICIAL_LAW_RX = re.compile(
    r"(소송|심판|등기|중재|공판|^법원|국회법|선거법|국정|입법|입회|조사위원회"
    r"|특별검사|진상규명)"
)


def is_judicial_law(law_name: str) -> bool:
    """사법·절차·진상규명법 — 규제 결함 룰 적용 제외."""
    return bool(_JUDICIAL_LAW_RX.search(law_name))


# 노동·복지·사회보험 도메인 — 규제 결함 룰 일부 적용 제외
# Source: verdict 분석 — L-03 (0/66), F-03 (0/14), G-04 (0/8), F-02 (0/6)
_LABOR_WELFARE_RX = re.compile(
    r"(고용|근로|산업안전보건|임금채권|파견근로|선원|국민연금|건강보험"
    r"|산업재해|보험료징수|장기요양|일\s*[ㆍ·]\s*가정|복지기본|채권보장"
    r"|최저임금|기간제|단시간|가사근로|직업안정)"
)


def is_labor_welfare_law(law_name: str) -> bool:
    """노동·복지·사회보험 법령 — L-03/F-03/G-04/F-02 적용 제외 대상."""
    return bool(_LABOR_WELFARE_RX.search(law_name))


# 방송·통신 법령 — L-03 특히 발화 많음 (옛 법령 인용)
_BROADCAST_RX = re.compile(r"(방송|전파|미디어|언론중재)")


def is_broadcast_law(law_name: str) -> bool:
    """방송·통신 법령 — L-03 외 적용 제외."""
    return bool(_BROADCAST_RX.search(law_name))


# 형사 특별법·진상규명·특별검사 — 절차적 성격이 강해 규제 룰 발화 부적합
_CRIMINAL_SPECIAL_RX = re.compile(
    r"(특별검사|진상규명|성폭력|스토킹|인신매매|범죄피해자|형의?\s*집행|군에서의)"
)


def is_criminal_special_law(law_name: str) -> bool:
    return bool(_CRIMINAL_SPECIAL_RX.search(law_name))


# 군사·국방 법령
_MILITARY_RX = re.compile(r"(군인|국군|군사|군무원|군법무관)")


def is_military_law(law_name: str) -> bool:
    return bool(_MILITARY_RX.search(law_name))


# Verdict-fitted (law, rule) blacklist — 대형 복합법에서 LLM이 일관되게 FP 라벨
# 새 verdict 데이터로 일반화될 때까지의 임시 안전장치.
# Source: outputs/verification_dataset.jsonl 분석 (0 TP / N FP 셀)
_LAW_RULE_BLACKLIST: dict[str, set[str]] = {
    "2018평창동계올림픽대회및동계패럴림픽대회지원등에관한특별법": {"L-01"},
    "가축분뇨의관리및이용에관한법률": {"F-03"},
    "간선급행버스체계의건설및운영에관한특별법": {"E-01", "G-01"},
    "개인정보보호법": {"S-04"},
    "건강기능식품에관한법률": {"E-01"},
    "건설기술진흥법": {"E-01"},
    "건축물관리법": {"L-01"},
    "결혼중개업의관리에관한법률": {"F-03"},
    "경비업법": {"S-04"},
    "경찰공무원법": {"L-01"},
    "고엽제후유의증등환자지원및단체설립에관한법률": {"E-01"},
    "골재채취법": {"F-03"},
    "공공데이터의제공및이용활성화에관한법률": {"F-02"},
    "공무원재해보상법": {"L-01"},
    "공유수면관리및매립에관한법률": {"L-01"},
    "공익법인의설립ㆍ운영에관한법률": {"G-03"},
    "공직자윤리법": {"S-04"},
    "관광진흥법": {"F-03"},
    "광업법": {"E-01"},
    "교육공무원법": {"G-01"},
    "교육관련기관의정보공개에관한특례법": {"F-03"},
    "국가공무원법": {"E-01"},
    "국가유공자등예우및지원에관한법률": {"L-01"},
    "국가통합교통체계효율화법": {"L-01"},
    "국민건강보험법": {"G-01"},
    "국민연금법": {"G-01"},
    "국세기본법": {"L-01"},
    "국세징수법": {"L-01"},
    "국제회의산업육성에관한법률": {"L-01"},
    "국회법": {"E-01"},
    "군사법원법": {"G-01"},
    "군인사법": {"G-01"},
    "궤도운송법": {"E-01"},
    "금융거래지표의관리에관한법률": {"E-01"},
    "금융소비자보호에관한법률": {"F-03", "G-01"},
    "금융회사의지배구조에관한법률": {"L-01"},
    "기업활동규제완화에관한특별조치법": {"E-01"},
    "긴급복지지원법": {"L-01"},
    "낙동강수계물관리및주민지원등에관한법률": {"L-01"},
    "낚시관리및육성법": {"E-01"},
    "노동조합및노동관계조정법": {"G-01"},
    "노후거점산업단지의활력증진및경쟁력강화를위한특별법": {"L-01"},
    "농수산물품질관리법": {"F-03"},
    "농약관리법": {"S-04"},
    "농어촌마을주거환경개선및리모델링촉진을위한특별법": {"E-01"},
    "농지법": {"E-01"},
    "농촌공간재구조화및재생지원에관한법률": {"L-01"},
    "다중이용업소의안전관리에관한특별법": {"E-01"},
    "대구경북통합신공항건설을위한특별법": {"L-01"},
    "대도시권광역교통관리에관한특별법": {"E-01"},
    "대중문화예술산업발전법": {"F-02"},
    "도시공업지역의관리및활성화에관한특별법": {"L-01"},
    "도시공원및녹지등에관한법률": {"L-01"},
    "도시재생활성화및지원에관한특별법": {"E-01"},
    "도시철도법": {"E-01"},
    "도심복합개발지원에관한법률": {"F-04", "L-01"},
    "도청이전을위한도시건설및지원에관한특별법": {"E-01"},
    "동ㆍ서ㆍ남해안및내륙권발전특별법": {"S-04"},
    "동물보호법": {"F-03", "L-01"},
    "디자인보호법": {"E-01"},
    "디지털포용법": {"F-03"},
    "마약류관리에관한법률": {"E-01"},
    "물류시설의개발및운영에관한법률": {"F-04", "G-01"},
    "물환경보전법": {"E-01", "L-01"},
    "민간인통제선이북지역의산지관리에관한특별법": {"L-01", "S-04"},
    "민간임대주택에관한특별법": {"G-01", "L-01"},
    "민법": {"F-04"},
    "방문판매등에관한법률": {"F-03"},
    "벤처기업육성에관한특별법": {"E-01"},
    "별정우체국법": {"E-01"},
    "보건환경연구원법": {"L-01"},
    "보험업법": {"E-01"},
    "복권및복권기금법": {"E-01"},
    "부가가치세법": {"G-01"},
    "부동산개발업의관리및육성에관한법률": {"F-03"},
    "부동산등기법": {"E-01"},
    "부패방지및국민권익위원회의설치와운영에관한법률": {"F-03"},
    "산림자원의조성및관리에관한법률": {"E-01", "G-01"},
    "산림조합법": {"E-01"},
    "산업안전보건법": {"E-01"},
    "산업입지및개발에관한법률": {"E-01", "L-01"},
    "산업재해보상보험법": {"E-01"},
    "산업집적활성화및공장설립에관한법률": {"E-01"},
    "산지관리법": {"L-01"},
    "상법": {"E-01"},
    "상표법": {"F-04", "G-01"},
    "생활화학제품및살생물제의안전관리에관한법률": {"E-01"},
    "선박투자회사법": {"F-03"},
    "성폭력범죄의처벌등에관한특례법": {"E-01", "G-01"},
    "세월호선체조사위원회의설치및운영에관한특별법": {"F-02"},
    "소방시설공사업법": {"F-03"},
    "소상공인보호및지원에관한법률": {"E-01"},
    "소하천정비법": {"S-04"},
    "수도법": {"S-04"},
    "수산생물질병관리법": {"E-01", "G-01"},
    "수산업법": {"E-01", "F-03"},
    "수산업협동조합법": {"G-01"},
    "순환경제사회전환촉진법": {"E-01"},
    "스마트농업육성및지원에관한법률": {"E-01"},
    "승강기안전관리법": {"E-01"},
    "식품위생법": {"S-04"},
    "신용정보의이용및보호에관한법률": {"G-01"},
    "신용협동조합법": {"E-01"},
    "신행정수도후속대책을위한연기ㆍ공주지역행정중심복합도시건설을위한특별법": {"E-01"},
    "아동ㆍ청소년의성보호에관한법률": {"F-03"},
    "야생생물보호및관리에관한법률": {"L-01"},
    "어촌ㆍ어항법": {"L-01"},
    "역세권의개발및이용에관한법률": {"E-01", "F-04"},
    "연안관리법": {"L-01"},
    "영산강ㆍ섬진강수계물관리및주민지원등에관한법률": {"L-01"},
    "영화및비디오물의진흥에관한법률": {"E-01"},
    "외국법자문사법": {"F-03"},
    "외국인투자촉진법": {"L-03"},
    "원자력손해배상법": {"F-02"},
    "원자력안전법": {"E-01"},
    "원자력안전위원회의설치및운영에관한법률": {"S-04"},
    "유선및도선사업법": {"G-01"},
    "은행법": {"F-03", "G-01"},
    "응급의료에관한법률": {"L-01"},
    "의료법": {"E-01"},
    "인삼산업법": {"E-01"},
    "임업및산촌진흥촉진에관한법률": {"E-01"},
    "자동차관리법": {"G-01"},
    "자산유동화에관한법률": {"F-03"},
    "자율관리어업육성및지원에관한법률": {"F-03"},
    "장애인복지법": {"L-01"},
    "재외국민의교육지원등에관한법률": {"G-03"},
    "저수지ㆍ댐의안전관리및재해예방에관한법률": {"L-01"},
    "전력기술관리법": {"G-01"},
    "전원개발촉진법": {"L-01"},
    "전자상거래등에서의소비자보호에관한법률": {"F-03", "S-04"},
    "정보통신공사업법": {"G-01"},
    "정신건강증진및정신질환자복지서비스지원에관한법률": {"S-04"},
    "제주특별자치도설치및국제자유도시조성을위한특별법": {"L-01"},
    "종자산업법": {"E-01"},
    "주식ㆍ사채등의전자등록에관한법률": {"F-03"},
    "주한미군기지이전에따른평택시등의지원등에관한특별법": {"E-01"},
    "중소기업기술혁신촉진법": {"E-01"},
    "중소기업인력지원특별법": {"L-01"},
    "중소기업진흥에관한법률": {"S-04"},
    "중소기업창업지원법": {"L-01"},
    "중재법": {"E-01"},
    "지방세법": {"S-04"},
    "지방자치분권및지역균형발전에관한특별법": {"E-01"},
    "지하안전관리에관한특별법": {"S-04"},
    "채무자회생및파산에관한법률": {"E-01", "F-04"},
    "첨단산업인재혁신특별법": {"E-01"},
    "청소년보호법": {"L-01"},
    "체육시설의설치ㆍ이용에관한법률": {"L-01"},
    "초지법": {"L-01"},
    "축산계열화사업에관한법률": {"F-03"},
    "축산법": {"G-01"},
    "축산자조금의조성및운용에관한법률": {"F-03"},
    "측량ㆍ수로조사및지적에관한법률": {"E-01"},
    "친수구역활용에관한특별법": {"L-01"},
    "택지개발촉진법": {"L-01"},
    "통신비밀보호법": {"G-01"},
    "특허법": {"E-01"},
    "폐기물관리법": {"F-03", "L-01"},
    "폐기물의국가간이동및그처리에관한법률": {"F-03"},
    "포항지진의진상조사및피해구제등을위한특별법": {"F-02"},
    "하도급거래공정화에관한법률": {"E-01", "F-03"},
    "하수도법": {"F-03"},
    "하천법": {"L-01"},
    "한강수계상수원수질개선및주민지원등에관한법률": {"L-01"},
    "한국마사회법": {"F-03"},
    "한국자산관리공사설립등에관한법률": {"L-01"},
    "한국전력공사법": {"L-03"},
    "한옥등건축자산의진흥에관한법률": {"E-01"},
    "할부거래에관한법률": {"S-04"},
    "항공안전법": {"E-01", "F-03"},
    "항만법": {"E-01"},
    "해상풍력보급촉진및산업육성에관한특별법": {"L-01"},
    "해수욕장의이용및관리에관한법률": {"L-01"},
    "해양산업클러스터의지정및육성등에관한특별법": {"L-01"},
    "해양심층수의개발및관리에관한법률": {"L-01"},
    "해양이용영향평가법": {"G-01"},
    "해양치유자원의관리및활용에관한법률": {"L-01"},
    "해양환경관리법": {"G-01"},
    "해운법": {"E-01"},
    "형사소송법": {"G-01"},
    "화물자동차운수사업법": {"L-01"},
    "환경기술및환경산업지원법": {"L-01"},
    "환경범죄등의단속및가중처벌에관한법률": {"L-01"},
    "환경영향평가법": {"E-01", "G-01"},
    "환경오염시설의통합관리에관한법률": {"F-03"},
    "환자안전법": {"F-03"},
}



def is_blacklisted(law_name: str, rule_id: str) -> bool:
    """(law, rule) verdict-fitted blacklist — LLM 정답에 따라 0-TP 셀 차단."""
    return rule_id in _LAW_RULE_BLACKLIST.get(law_name, set())


@dataclass
class ParagraphDecomposition:
    para_index: int
    text: str
    subject: Subject = Subject.UNKNOWN
    modal: Modal = Modal.NONE
    has_adversarial_action: bool = False  # 침익적 처분·금지·명령
    has_disposition: bool = False
    has_obligation: bool = False
    has_prohibition: bool = False
    actions: list[ActionKind] = field(default_factory=list)  # 본 항의 행위 종류들
    # 호 단위 캐치올 강도 — S-04/E-01/G-01 공통 신호
    # STRICT (위임형), LOOSE (필요사항), WEAK (잔여) 3단계, None = 없음
    catchall_kind: str | None = None
    items_count: int = 0  # 본 항의 호 개수
    proviso_count: int = 0  # 본 항의 단서(다만) 횟수 — G-01 공통 신호
    # 처분 강도 — F-03 공통 활용 (강/중/약/None)
    disposition_strength: str | None = None

    def has_action(self, kind: ActionKind) -> bool:
        return kind in self.actions


@dataclass
class ArticleDecomposition:
    """SLM-level 분해 결과. 룰은 이 객체에 대해 동작."""
    article: Article
    type: ArticleType = ArticleType.GENERAL
    paragraphs: list[ParagraphDecomposition] = field(default_factory=list)
    primary_subject: Subject = Subject.UNKNOWN
    # 누적 신호 (article-level)
    has_definition_signal: bool = False
    has_penalty_signal: bool = False
    has_delegation_signal: bool = False
    has_disposition_signal: bool = False
    has_reporting_signal: bool = False
    has_committee_signal: bool = False
    has_procedure_signal: bool = False
    has_prohibition_signal: bool = False
    has_plan_signal: bool = False
    # 행위 종류 집합 (article-level union of paragraph actions)
    actions: set[ActionKind] = field(default_factory=set)
    # F-03 공통 활용 신호 (article-level)
    disposition_strength: str | None = None  # 강/중/약/None — 최강 strength 합산
    has_hearing: bool = False  # 동일 article 내 청문·사전절차 명시
    has_standard: bool = False  # 별표·기준·다음 각 호의 어느 하나 명시
    # L-01/L-02/L-03 공통 활용 신호
    cited_laws: frozenset[str] = field(default_factory=frozenset)  # 인용된 법령명 집합
    cited_articles_count: int = 0  # 「법령명」제N조 cross-ref 횟수
    # G-01 공통 활용 — 단서 통계
    proviso_total: int = 0  # 본 조문 전체 "다만" 출현 총합
    proviso_max_per_para: int = 0  # 항별 최대 "다만" 횟수
    # E-01·F-03 활용 — 동일법 내부 조문 인용 (제N조)
    internal_refs_count: int = 0  # "제N조" / "제N조제M항" 인용 횟수
    internal_refs_unique: int = 0  # 고유 조문 인용 수
    # F-04 활용 — 의사표시 의제·시간 기한
    has_deemed_assent: bool = False  # "동의/승낙/이의 없는 것으로 본다"
    deadlines_days: tuple[int, ...] = ()  # 본 조문에서 추출된 일 단위 기한들 (오름차순)
    # E-01 조건 복잡도 (효율성 활용)
    condition_lead_count: int = 0  # "경우|때|요건" 횟수
    condition_link_count: int = 0  # "및|또는|이고|이며|하고|하며" 횟수
    nested_hint_count: int = 0     # "다음 각 호의|충족하고|모두 충족" 횟수
    # 가독성 신호 (prompts.chat Text Analyzer Tool 영감)
    avg_words_per_sentence: float = 0.0  # 평균 어절 수/문장 (길수록 가독성 ↓)
    hanja_ratio: float = 0.0             # 한자 비율 (legalese)
    parenthetical_density: float = 0.0   # 괄호·법령명 인용 밀도
    readability_score: float = 0.0       # 통합 가독성 점수 (0~1, 낮을수록 어려움)

    def has_action(self, kind: ActionKind) -> bool:
        return kind in self.actions


def _classify_subject(text: str) -> Subject:
    """단일 텍스트 chunk 에서 주체를 식별."""
    head = text[:120]  # 문장 앞부분만 — 주체는 보통 문두에 있음
    if _EVERYONE_SUBJECT_RX.search(head):
        return Subject.EVERYONE
    if _OFFICIAL_SUBJECT_RX.search(head):
        return Subject.OFFICIAL
    if _AGENCY_SUBJECT_RX.search(head):
        return Subject.AGENCY
    if _OPERATOR_SUBJECT_RX.search(head):
        return Subject.OPERATOR
    if _CITIZEN_SUBJECT_RX.search(head):
        return Subject.CITIZEN
    return Subject.UNKNOWN


def _classify_modal(text: str) -> Modal:
    if _PROHIBITION_RX.search(text):
        return Modal.PROHIBITED
    if "할 수 있다" in text or "할 수 있고" in text:
        return Modal.MAY
    if "하여야 한다" in text or "하여야 하며" in text:
        return Modal.MUST
    if "말한다" in text or "본다" in text:
        return Modal.DEFINITION
    return Modal.NONE


def _classify_disposition_strength(text: str) -> str | None:
    """처분 강도 분류 — 강/중/약/None."""
    if _DISP_STRENGTH_STRONG.search(text):
        return "강"
    if _DISP_STRENGTH_MID.search(text):
        return "중"
    if _DISP_STRENGTH_WEAK.search(text):
        return "약"
    return None


def _classify_actions(text: str) -> list[ActionKind]:
    """텍스트에서 행위 종류들 식별 (다중 가능).

    R2 진정한 SLM 효과: 한 문단에 여러 행위 (예: 허가+취소+청문) 가 있으면
    그 조합 자체가 규제 의미. 룰은 actions 조합 보고 판단.
    """
    actions: list[ActionKind] = []
    if _ACTION_GRANT_RX.search(text): actions.append(ActionKind.GRANT)
    if _ACTION_REVOKE_RX.search(text): actions.append(ActionKind.REVOKE)
    if _ACTION_IMPOSE_RX.search(text): actions.append(ActionKind.IMPOSE)
    if _ACTION_REPORT_RX.search(text): actions.append(ActionKind.REPORT)
    if _ACTION_REGISTER_RX.search(text): actions.append(ActionKind.REGISTER)
    if _ACTION_DELEGATE_RX.search(text): actions.append(ActionKind.DELEGATE)
    if _ACTION_RESTRICT_RX.search(text): actions.append(ActionKind.RESTRICT)
    if _ACTION_DEFINE_RX.search(text): actions.append(ActionKind.DEFINE)
    if _ACTION_INVESTIGATE_RX.search(text): actions.append(ActionKind.INVESTIGATE)
    if _ACTION_HEAR_RX.search(text): actions.append(ActionKind.HEAR)
    return actions


def _classify_article_type(art: Article) -> ArticleType:
    """주요 신호 우선순위로 article type 결정."""
    title = art.title or ""
    text = art.full_text
    body_start = text[:300]

    # 1. 삭제·빈 조문
    if len(text.strip()) < 60 and _EMPTY_RX.search(text):
        return ArticleType.EMPTY
    # 2. 정의
    if "정의" in title or "용어" in title or _DEFINITION_RX.search(body_start):
        return ArticleType.DEFINITION
    # 3. 목적
    if "목적" in title or _PURPOSE_RX.search(body_start):
        return ArticleType.PURPOSE
    # 4. 벌칙 (제목 또는 본문 강한 신호)
    if title.startswith(("벌칙", "과태료", "양벌", "처벌", "형벌")):
        return ArticleType.PENALTY
    if _PENALTY_RX.search(body_start):
        return ArticleType.PENALTY
    # 5. 위원회 운영
    if _COMMITTEE_RX.search(text) and ("위원회" in title or "심의회" in title or "이사회" in title):
        return ArticleType.COMMITTEE
    # 6. 처분 (취소·정지·과징금)
    if _DISPOSITION_RX.search(text):
        return ArticleType.DISPOSITION
    # 7. 위임 (대통령령으로 정한다)
    if _DELEGATION_RX.search(text) and not any(s in text for s in ("취소", "정지", "처분")):
        return ArticleType.DELEGATION
    # 8. 보고
    if _REPORTING_RX.search(text):
        return ArticleType.REPORTING
    # 9. 절차 (인허가 처리)
    if _PROCEDURE_RX.search(text):
        return ArticleType.PROCEDURE
    # 10. 금지
    if _PROHIBITION_RX.search(text):
        return ArticleType.PROHIBITION
    # 11. 계획 수립
    if _PLAN_RX.search(text):
        return ArticleType.PLAN
    return ArticleType.GENERAL


def decompose(art: Article) -> ArticleDecomposition:
    """Article → ArticleDecomposition (SLM-level)."""
    text = art.full_text
    art_type = _classify_article_type(art)

    para_decomps: list[ParagraphDecomposition] = []
    para_subjects: list[Subject] = []
    # 호 단위 캐치올 매핑 — paragraphs[i].items 직접 접근
    para_catchalls: dict[int, str | None] = {}
    para_item_counts: dict[int, int] = {}
    if art.paragraphs:
        for i, p in enumerate(art.paragraphs):
            if not p.items:
                para_catchalls[i] = None
                para_item_counts[i] = 0
                continue
            para_item_counts[i] = len(p.items)
            last_item_text = p.items[-1].text if p.items else ""
            if _CATCHALL_STRICT.search(last_item_text):
                para_catchalls[i] = "STRICT"
            elif _CATCHALL_LOOSE.search(last_item_text):
                para_catchalls[i] = "LOOSE"
            elif _CATCHALL_WEAK.search(last_item_text):
                para_catchalls[i] = "WEAK"
            else:
                para_catchalls[i] = None
    if art.paragraphs:
        paras = [(i, p.text) for i, p in enumerate(art.paragraphs) if p.text.strip()]
        if not paras:  # single-line article — paragraphs exist but empty
            paras = [(0, text)]
    else:
        paras = [(0, text)]
    for idx, pt in paras:
        subj = _classify_subject(pt)
        modal = _classify_modal(pt)
        actions = _classify_actions(pt)
        disp_strength = _classify_disposition_strength(pt)
        para_decomps.append(ParagraphDecomposition(
            para_index=idx,
            text=pt,
            subject=subj,
            modal=modal,
            has_adversarial_action=bool(_DISPOSITION_RX.search(pt) or _PROHIBITION_RX.search(pt)),
            has_disposition=bool(_DISPOSITION_RX.search(pt)),
            has_obligation=(modal == Modal.MUST),
            has_prohibition=(modal == Modal.PROHIBITED),
            actions=actions,
            catchall_kind=para_catchalls.get(idx),
            items_count=para_item_counts.get(idx, 0),
            proviso_count=len(_PROVISO_RX.findall(pt)),
            disposition_strength=disp_strength,
        ))
        para_subjects.append(subj)
    # article-level action union
    all_actions = set()
    for pd in para_decomps:
        all_actions.update(pd.actions)
    # article-level disposition strength (강 > 중 > 약 우선순위)
    _strength_order = {"강": 3, "중": 2, "약": 1, None: 0}
    art_disp_strength = None
    for pd in para_decomps:
        if _strength_order.get(pd.disposition_strength, 0) > _strength_order.get(art_disp_strength, 0):
            art_disp_strength = pd.disposition_strength
    # article-level hearing / standard signals (F-03 활용)
    art_has_hearing = bool(_HEARING_RX.search(text))
    art_has_standard = bool(_STANDARD_RX.search(text))
    # L-01/L-02/L-03: 인용 법령명·cross-ref 추출
    cited_laws_set = frozenset(_CITED_LAW_RX.findall(text))
    cited_articles_count = len(_CITED_ARTICLE_RX.findall(text))
    # G-01: 단서 통계 (article total / per-paragraph max)
    proviso_total = len(_PROVISO_RX.findall(text))
    proviso_max = max((p.proviso_count for p in para_decomps), default=0)
    # E-01·F-03: 동일법 내부 조문 인용 (「법령명」 제외 — 본 법령의 다른 조문만)
    # 외부법령 인용 (cited_articles) 부분은 제외하기 위해 「」가 없는 위치만 카운트
    text_without_cited = _CITED_ARTICLE_RX.sub("", text)
    internal_refs = _INTERNAL_ARTICLE_RX.findall(text_without_cited)
    internal_refs_count = len(internal_refs)
    internal_refs_unique = len({tuple(r) for r in internal_refs})
    # E-01 조건 복잡도
    condition_lead_count = len(_CONDITION_LEAD_RX.findall(text))
    condition_link_count = len(_CONDITION_LINK_RX.findall(text))
    nested_hint_count = len(_NESTED_HINT_RX.findall(text))
    # 가독성 분석 (한국어 변형 — Flesch-Kincaid 모티프)
    words = _WORD_RX.findall(text)
    sentences = max(len(_SENTENCE_END_RX.findall(text)), 1)
    n_words = len(words)
    avg_words_per_sentence = n_words / sentences if sentences else 0.0
    n_chars = max(len(text), 1)
    hanja_count = len(_HANJA_RX.findall(text))
    hanja_ratio = hanja_count / n_chars
    parenthesis_count = len(_PARENTHESIS_RX.findall(text))
    parenthetical_density = parenthesis_count / max(n_words / 100, 1.0)  # 100어절당
    # 통합 가독성: 어절/문장 짧고 한자·괄호 적을수록 ↑
    # 정상화: avg_wps 30이상 = 1점, 한자비율 0.1 이상 = 1점, 괄호밀도 5이상 = 1점
    diff_wps = min(avg_words_per_sentence / 30.0, 1.0)
    diff_hanja = min(hanja_ratio / 0.1, 1.0)
    diff_paren = min(parenthetical_density / 5.0, 1.0)
    # 어려움 점수 (높을수록 어려움) → readability = 1 - 어려움 평균
    difficulty = (diff_wps + diff_hanja + diff_paren) / 3.0
    readability_score = 1.0 - difficulty

    # F-04: 의사표시 의제 + 일 단위 기한 추출
    has_deemed_assent = bool(_DEEMED_ASSENT_RX.search(text))
    days_found = []
    for m in _TIME_DEADLINE_RX.finditer(text):
        n, unit, _qual = m.group(1), m.group(2), m.group(3)
        try:
            n_int = int(n)
        except ValueError:
            continue
        if unit == "일": days_found.append(n_int)
        elif unit == "개월": days_found.append(n_int * 30)
        elif unit == "년": days_found.append(n_int * 365)
    deadlines_days_tuple = tuple(sorted(set(days_found)))

    # primary subject — 가장 자주 등장하는 비-UNKNOWN 주체
    non_unknown = [s for s in para_subjects if s != Subject.UNKNOWN]
    if non_unknown:
        from collections import Counter
        primary = Counter(non_unknown).most_common(1)[0][0]
    else:
        primary = Subject.UNKNOWN

    return ArticleDecomposition(
        article=art,
        type=art_type,
        paragraphs=para_decomps,
        primary_subject=primary,
        has_definition_signal=bool(_DEFINITION_RX.search(text)),
        has_penalty_signal=bool(_PENALTY_RX.search(text)),
        has_delegation_signal=bool(_DELEGATION_RX.search(text)),
        has_disposition_signal=bool(_DISPOSITION_RX.search(text)),
        has_reporting_signal=bool(_REPORTING_RX.search(text)),
        has_committee_signal=bool(_COMMITTEE_RX.search(text)),
        has_procedure_signal=bool(_PROCEDURE_RX.search(text)),
        has_prohibition_signal=bool(_PROHIBITION_RX.search(text)),
        has_plan_signal=bool(_PLAN_RX.search(text)),
        actions=all_actions,
        disposition_strength=art_disp_strength,
        has_hearing=art_has_hearing,
        has_standard=art_has_standard,
        cited_laws=cited_laws_set,
        cited_articles_count=cited_articles_count,
        proviso_total=proviso_total,
        proviso_max_per_para=proviso_max,
        internal_refs_count=internal_refs_count,
        internal_refs_unique=internal_refs_unique,
        has_deemed_assent=has_deemed_assent,
        deadlines_days=deadlines_days_tuple,
        condition_lead_count=condition_lead_count,
        condition_link_count=condition_link_count,
        nested_hint_count=nested_hint_count,
        avg_words_per_sentence=avg_words_per_sentence,
        hanja_ratio=hanja_ratio,
        parenthetical_density=parenthetical_density,
        readability_score=readability_score,
    )
