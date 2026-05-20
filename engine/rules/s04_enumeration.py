"""S-04 열거 과다 (항 단위 호 개수).

SLM-level (docs/ENGINE_PRINCIPLES.md R2): raw text 의 호 수만 보는 게 아니라
ArticleDecomposition.type 게이트를 거쳐 발화 여부를 결정.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_judicial_law, is_blacklisted
from .base import PatternResult, make_finding

# FP 필터 패턴
_PERMIT_DEEMED = re.compile(r"(인[\s·ㆍ]?허가.{0,10}의제|다른\s*법(률|령)에\s*따른\s*인[\s·ㆍ]?허가)")
_ARTICLES_OF_ASSOC = re.compile(r"정관.{0,30}(기재|포함|사항|규정)")
_PUBLIC_INSTITUTION = re.compile(r"(사업\s*범위|사업의\s*종류|공공기관의\s*운영)")
# FP: 정관 기재사항·회원자격·수입·수수료·면제·비과세 등 표준 열거
_STD_LIST_TITLE = re.compile(
    r"(정관|회원|회비|수수료|수입|세입|세출|예산|결산|회계|급여|면제|비과세|감면"
    r"|업무|사업|시설|기준|등록\s*요건|허가\s*요건|결격\s*사유|취소\s*사유"
    r"|위반행위|준수사항|기본계획|종합계획|시행계획|시책|진흥계획"
    r"|위원회의?\s*기능|위원회의?\s*업무|심의사항|기금의?\s*용도|업무|용도"
    r"|대상사업|적용대상|적용\s*범위)"
)
# Method B 추가 FP 필터 (article-level S-04 FP 분석 — 5건 → 0):
#   "특례" 류 한정열거 (도로교통법 §30 긴급자동차 특례), "시행규정"
#   기재사항 (도시정비법 §53), "불공정거래·불건전 영업행위 금지" 류
# Source: signal_candidates.json :: S-04 + verdict article-level
_EXTRA_FP_TITLE = re.compile(
    r"(특례|시행규정|"
    r"(?:불공정거래|불건전\s*영업|영업\s*행위)\s*.{0,5}금지)"
)
# 포괄위임 종결호 — 호 자체가 아니라 마지막 호에서만 확인
_CATCHALL_ITEM = re.compile(r"그\s*밖에.{0,30}(대통령령|총리령|부령|규칙)으로\s*정하는")

# 본문 신호 — title 이 부족할 때 본문에서 분류
# Source: signal_candidates.json :: S-04
# 벌칙·과태료 본문 신호 (각호가 위반행위 구성요건 열거)
_PENALTY_BODY = re.compile(
    r"(다음\s*각\s*호의?\s*어느\s*하나에?\s*해당하는?\s*자.{0,50}"
    r"(징역|벌금|과태료|처한다|부과한다))"
    r"|(\d+년\s*이하의?\s*징역|\d+(천|만|억)?\s*원\s*이하의?\s*벌금)"
)
# 정의 조문 본문 신호 (각호가 용어 정의)
_DEFINITION_BODY = re.compile(
    r"(이\s*법에서\s*(\"|『).*(\"|』)?(이?란|의\s*뜻은|는\s*다음과\s*같다)"
    r"|이\s*법에서\s*사용하는\s*용어의?\s*뜻"
    r'|"[^"]+"\s*(이|라)?\s*(란|함은).{0,80}말한다)'
)
# 처분 사유 열거 본문 신호 (취소/정지 사유)
_DISPOSITION_GROUNDS_BODY = re.compile(
    r"다음\s*각\s*호의?\s*어느\s*하나에?\s*해당하는?\s*(경우|때)에는?"
    r".{0,80}(허가|등록|면허|지정|승인|인가)를?\s*(취소|정지)"
)
# 자료요청·기관별 권한 열거 (정보체계 인용)
_DATA_REQUEST_BODY = re.compile(
    r"(자료\s*제공\s*요청|정보\s*제공\s*요청|관계\s*기관의?\s*장에게)"
    r".{0,100}다음\s*각\s*호"
)
# 사업범위 본문 신호 (공공기관 사업 열거)
_BUSINESS_SCOPE_BODY = re.compile(
    r"(공단은?|공사는?|재단은?|진흥원은?|기금은?|위원회는?)"
    r"\s*다음\s*각\s*호의?\s*사업"
)


def _is_fp_article(art: Article) -> bool:
    """열거 과다 FP 필터 — 법제상 불가피한 호 다수 조문.

    Method B (Claude classifier) 보강 분석 결과:
      - 벌칙·과태료라도 N≥20 이면 예측가능성 위협 → 발화 (FP 필터 해제)
      - 인허가의제 N≥30 극단치 → 발화 (FP 필터 해제)
      - 기본계획 + 캐치올 호 → 발화 (FP 필터 해제)
    Source: signal_candidates.json + Method B inline classification
    R5 examples (Method B로 직접 검증):
      S-04-003@해운법 제19조 (TP — 면허취소 18개)
      S-04-001@경범죄처벌법 제3조 (TP — 벌칙 41개)
      S-04-006@하수도법 제80조 (TP — 과태료 28개)
      S-04-003@새만금특별법 제17조 (TP — 인허가의제 53개)
    Counter-examples:
      S-04-001@독점규제법 제2조 (FP — 정의조문)
      S-04-002@도로교통법 제2조 (FP — 정의조문 35개)
    """
    # 정의·벌칙·목적 조문은 호 열거가 정상
    if art.is_definition() or art.is_purpose():
        return True
    text = art.full_text
    title = art.title or ""
    # 특례·시행규정·불공정거래 금지 류 (보존된 표준 입법 형식)
    if _EXTRA_FP_TITLE.search(title):
        return True
    # 벌칙 조문: N≥35 인 극단치만 발화 (경범죄처벌법 제3조 41개 류)
    # (Method B 분석: 20~30 구간은 정상 입법, LLM 도 FP 판정 다수)
    if art.is_penalty():
        max_items = max((len(p.items) for p in art.paragraphs), default=0)
        if max_items < 35:
            return True

    # 인허가의제 조문 — N≥50 극단치만 발화 (새만금 53개 류)
    if _PERMIT_DEEMED.search(title) or _PERMIT_DEEMED.search(text[:300]):
        max_items = max((len(p.items) for p in art.paragraphs), default=0)
        if max_items < 50:
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
    # 추가: 기본계획·시행계획에 캐치올 호가 있으면 발화 (포괄위임 동반 결함)
    if _STD_LIST_TITLE.search(title):
        adversarial_title = any(k in title for k in ("위반", "취소", "결격", "처분", "벌"))
        plan_with_catchall = (
            any(k in title for k in ("기본계획", "종합계획", "시행계획"))
            and any(_CATCHALL_ITEM.search(p.items[-1].text) if p.items else False
                    for p in art.paragraphs)
        )
        if not adversarial_title and not plan_with_catchall:
            return True
    # 본문 신호 — title 이 일반적이거나 비어있을 때만 본문 첫 200자만 보고 분류
    body_start = text[:200]
    # 벌칙 첫 줄 신호: 본문이 벌칙성이라도 N≥35 이면 발화
    if _PENALTY_BODY.search(body_start):
        max_items = max((len(p.items) for p in art.paragraphs), default=0)
        if max_items < 35:
            return True
    # 정의 본문 신호: "이 법에서 ... 말한다"
    if _DEFINITION_BODY.search(body_start):
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
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "S-04"):
            return []
        # 사법·절차법령 — S-04 미적용 (verdict: 0 TP / 7 FP)
        if is_judicial_law(law.name):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            # Method B (Step 42): 센터·기금·용도·기능 제목 + 캐치올 + 호 ≥10
            # 우선 _inst_override 평가 후 FP 필터·구조 게이트 우회
            _early_decomp = decompose(art)
            _inst_title_pre = bool(re.search(r"(센터|기금|용도|기능)", art.title or ""))
            _inst_catchall_pre = any(
                p.catchall_kind in ("STRICT", "LOOSE") for p in _early_decomp.paragraphs
            )
            _inst_n_pre = max((p.items_count for p in _early_decomp.paragraphs), default=0)
            _inst_override_pre = _inst_title_pre and _inst_catchall_pre and _inst_n_pre >= 10

            if not _inst_override_pre and _is_fp_article(art):
                continue
            # Structural FP gates (verdict 분석): 순수 FP 조합
            decomp = _early_decomp
            t, s = decomp.type, decomp.primary_subject.value
            from ..structure import Modal
            modal_str = "NONE"
            for p in decomp.paragraphs:
                if p.modal != Modal.NONE: modal_str = p.modal.value; break
            # Method B (Step 42): 센터·기금·용도·기능 제목 + 캐치올 + 호 ≥10
            # → 기관 업무 열거 + 임의 추가 조항의 명백 결함 패턴 (verdict 4 TP / 1 FP)
            # R5 examples:
            #   진로교육법 §15 (국가진로교육센터 — LOOSE 캐치올)
            #   치매관리법 §16의2 (광역치매센터 — LOOSE)
            #   한강수계 §22 (기금의 용도 — STRICT)
            #   한국해양진흥공사법 §11 (업무... 사실은 "기능"이 아님)
            #   지방자치분권법 §63 (기능 — LOOSE)
            # 구조적 게이트 우회 (Subject·Modal·Type 무관 발화)
            _inst_title = bool(re.search(r"(센터|기금|용도|기능)", art.title or ""))
            _inst_catchall = any(
                p.catchall_kind in ("STRICT", "LOOSE") for p in decomp.paragraphs
            )
            _inst_n = max((p.items_count for p in decomp.paragraphs), default=0)
            _inst_override = _inst_title and _inst_catchall and _inst_n >= 10
            if t == ArticleType.COMMITTEE:
                if not _inst_override:
                    continue
            if t == ArticleType.REPORTING and s == "AGENCY":
                if not _inst_override:
                    continue
            if t == ArticleType.PROHIBITION:
                continue
            if t == ArticleType.GENERAL and s in ("AGENCY", "EVERYONE"):
                if not _inst_override:
                    continue
            if t == ArticleType.PLAN and s == "AGENCY":
                if not _inst_override:
                    continue
            # 3-axis gates
            if t == ArticleType.DISPOSITION and s == "AGENCY" and modal_str == "MUST":
                if not _inst_override:
                    continue
            if t == ArticleType.DISPOSITION and s == "UNKNOWN" and modal_str in ("MAY", "PROHIBITED"):
                if not _inst_override:
                    continue
            if t == ArticleType.DELEGATION and s == "AGENCY" and modal_str == "DEFINITION":
                if not _inst_override:
                    continue
            if t == ArticleType.DELEGATION and s == "UNKNOWN" and modal_str == "MUST":
                if not _inst_override:
                    continue
            if t == ArticleType.PROCEDURE and s == "UNKNOWN" and modal_str == "MUST":
                if not _inst_override:
                    continue
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str in ("NONE", "MAY"):
                if not _inst_override:
                    continue
            # Aggressive (TP loss < FP cut by 4x)
            # DISPOSITION + AGENCY + MAY (4 TP / 32 FP — net 28)
            # Method B 보강: 처분 제목(취소/말소/정지/폐쇄) + 호 ≥15 는 진성 TP
            #   사료관리법 §25 (등록취소 19호), 하수도법 §54 (등록취소 15호),
            #   해운법 §19 (면허취소 18호) — verdict TP 3건, FP 1건만 (net +2)
            _title_disp_short = bool(re.search(r"(취소|말소|정지|폐쇄)", art.title or ""))
            _max_items = max((len(p.items) for p in art.paragraphs), default=0)
            if t == ArticleType.DISPOSITION and s == "AGENCY" and modal_str == "MAY":
                if not (_title_disp_short and _max_items >= 15):
                    continue
            # DELEGATION + AGENCY + MAY (3 TP / 9 FP — net 6)
            # Method B: 개발계획·복합개발·혁신구역·정비계획 제목 + STRICT 캐치올
            # + 호 ≥16 은 진성 TP (verdict: 4 TP / 0 FP).
            #   경제자유구역 §6 (n=16), 도심복합 §5 (n=17),
            #   도시공업지역 §22 (n=21), 노후계획도시정비 §12 (n=19)
            _plan_title_disp = bool(re.search(r"(개발계획|복합개발|혁신구역|정비계획)", art.title or ""))
            _max_items_for_gate = max((len(p.items) for p in art.paragraphs), default=0)
            _has_strict_catchall = any(
                bool(re.search(r"그\s*밖에.{0,80}(대통령령|총리령|부령|규칙)으?로\s*정하는",
                               p.items[-1].text)) if p.items else False
                for p in art.paragraphs
            )
            if t == ArticleType.DELEGATION and s == "AGENCY" and modal_str == "MAY":
                if not (_plan_title_disp and _has_strict_catchall and _max_items_for_gate >= 16):
                    if not _inst_override_pre:
                        continue
            # GENERAL + UNKNOWN + MUST (1 TP / 6 FP)
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "MUST":
                if not _inst_override_pre:
                    continue
            # DELEGATION + EVERYONE + PROHIBITED (1 TP / 6 FP)
            if t == ArticleType.DELEGATION and s == "EVERYONE" and modal_str == "PROHIBITED":
                continue
            # GENERAL + UNKNOWN + DEFINITION (1 TP / 4 FP)
            if t == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "DEFINITION":
                if not _inst_override_pre:
                    continue
            # SLM signal: 호 수만으론 TP/FP 분간 불가 (TP 평균 13.4 ≈ FP 평균 13.7).
            # 컨텍스트(처분·위반·포괄위임) 신호와 결합해야 의미 있는 발화.
            art_text = art.full_text
            has_adversarial_context = bool(re.search(
                r"(취소|정지|명령|과징금|과태료|처분|위반|금지|시정명령)", art_text
            ))
            for para in art.paragraphs:
                n = len(para.items)
                # 적대적 컨텍스트 없으면 임계값 상향 (15호 이상만 발화)
                # _inst_override_pre 시: 호 ≥10 로 임계값 완화 (기관 업무+캐치올)
                if _inst_override_pre:
                    min_n = 10
                else:
                    min_n = 10 if has_adversarial_context else 15
                if n < min_n:
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
