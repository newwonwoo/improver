"""G-01 예외·단서 (설계서 §3.2 G-01).

항별로 단서(다만) 카운팅 — 다항 조문은 항당 최대 1개가 정상.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_blacklisted
from .base import PatternResult, make_finding


_DANSEO = re.compile(r"다만[,\s]")
_VAGUE_EXC = re.compile(r"대통령령으로 정하는 (경우|사항)을? 제외")
# FP 필터: 면책·양벌 단서 (고의·중과실 면책은 적법 패턴)
_EXEMPT_DANSEO = re.compile(
    r"(상당한\s*주의와\s*감독|고의가\s*아닌|정상적인\s*인식능력"
    r"|고의\s*또는\s*과실이\s*없|진실한\s*사실)"
)
# TP 부스트: 처분조 단서 중첩
_DISPOSITION_KEY = re.compile(r"(취소|정지|명령|과징금|해임|폐쇄)")
# SLM signal (signal_candidates :: G-01):
# "처분조문 단서중첩 TP부스트" — 제목 (등록취소|영업정지|허가취소|면직) + 단서 3+ + 재량
_DISPOSITION_TITLE_STRONG = re.compile(
    r"(등록\s*취소|영업\s*정지|허가\s*취소|면직|해임|자격\s*취소)"
)
# "기본권관련 절차 면제 단서 TP부스트" — 면회·통신·청약철회·교육·진료 + 단서 3+
_FUNDAMENTAL_RIGHT_CONTEXT = re.compile(
    r"(면회|통신|서신|청약\s*철회|교육|진료|진찰|면접교섭|친권|친자)"
)

# SLM-level FP filters (signal_candidates :: G-01)
# 정의·용어 조문 (제외/한정 단서는 정의 범위 명확화일 뿐)
_DEFINITION_TITLE = re.compile(r"(정의|용어|이\s*법에서.*뜻은|이라\s*함은|이란.{0,40}말한다)")
# 양벌·벌칙·과태료 조문
_PENALTY_TITLE = re.compile(r"(양벌규정|벌칙|과태료|몰수|추징)")
# 세제·재정 절차 조문 (추계조사·기준소득·비치·기록 등 세무 절차 변형)
_TAX_PROCEDURE = re.compile(
    r"(추계\s*조사|기준\s*소득|기준\s*경비|비치(ㆍ|·)?\s*기록"
    r"|장부(ㆍ|·)?\s*증명서|세액\s*공제|기장의무|세무\s*조사)"
)
# 행정심판·소송 준용 단서
_ADMIN_PROC_REF = re.compile(r"(행정심판법|행정소송법).{0,30}준용")
# 효력범위·면제 한정 단서 (재량·처분 부재시 FP)
_SCOPE_LIMIT_DANSEO = re.compile(
    r"(대상\s*물건|용도|효력\s*범위|면제\s*대상|적용\s*범위)"
)


def _max_danseo_per_para(art: Article) -> int:
    """단일 항에서 최대 단서(다만) 수. 다항 조문에서 항별 집계로 오탐 감소.

    호환을 위한 fallback — 신규 코드는 decompose(art).paragraphs[i].proviso_count 사용.
    """
    if art.paragraphs:
        para_texts = [p.text for p in art.paragraphs if p.text.strip()]
        if para_texts:
            return max(len(_DANSEO.findall(pt)) for pt in para_texts)
    return len(_DANSEO.findall(art.full_text))


def _max_proviso_from_decomp(decomp) -> int:
    """R2 구조 신호: ParagraphDecomposition.proviso_count 의 최대값.
    동일 의미를 구조화분해기 신호로 표현 (전수 R구조화).
    """
    if decomp.paragraphs:
        return max((p.proviso_count for p in decomp.paragraphs), default=0)
    return 0


class G01Exception:
    pattern_id = "G-01"
    pattern_name = "예외·단서"
    category = "거버넌스"

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "G-01"):
            return []
        # SLM signal composition (docs/ENGINE_PRINCIPLES.md R1, R4)
        # Source: signal_candidates.json :: G-01
        # Rationale: "다만" 횟수만으로 발화하면 FP 폭증. 단서가 정의·세제절차·
        #   양벌·효력범위 같은 표준 입법 영역에 있으면 결함 아님.
        # R5 examples:
        #   G-01-001@금융소비자보호에관한법률 (FP — 정의조문 단서)
        #   G-01-011@건축법 (FP — 양벌규정 면책단서)
        #   G-01-021@법인세법 (FP — 세제 절차 단서)
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            # FP 필터: 정의·벌칙·목적 조문
            if art.is_definition() or art.is_penalty() or art.is_purpose():
                continue
            # Structural gates (verdict 분석)
            decomp = decompose(art)
            s = decomp.primary_subject.value
            from ..structure import Modal
            modal_str = "NONE"
            for p in decomp.paragraphs:
                if p.modal != Modal.NONE:
                    modal_str = p.modal.value
                    break
            if decomp.type == ArticleType.PROHIBITION and s == "UNKNOWN":
                continue
            if decomp.type == ArticleType.GENERAL and s == "OPERATOR" and modal_str == "DEFINITION":
                continue
            if decomp.type == ArticleType.PROCEDURE and s == "UNKNOWN" and modal_str == "NONE":
                continue
            if decomp.type == ArticleType.DELEGATION and s == "OFFICIAL" and modal_str == "MAY":
                continue
            # Aggressive gates (TP loss < FP cut by 4x+)
            if decomp.type == ArticleType.DELEGATION and s == "UNKNOWN" and modal_str == "MAY":
                continue  # 1 TP / 10 FP
            if decomp.type == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "NONE":
                continue  # 2 TP / 9 FP
            if decomp.type == ArticleType.DELEGATION and s == "UNKNOWN" and modal_str == "NONE":
                continue  # 2 TP / 8 FP
            if decomp.type == ArticleType.DELEGATION and s == "UNKNOWN" and modal_str == "DEFINITION":
                continue  # 1 TP / 5 FP
            # GENERAL+UNKNOWN+DEFINITION (2 TP / 15 FP — net 13)
            if decomp.type == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "DEFINITION":
                continue
            # GENERAL+UNKNOWN+MUST (4 TP / 12 FP — net 8)
            if decomp.type == ArticleType.GENERAL and s == "UNKNOWN" and modal_str == "MUST":
                continue
            # GENERAL+AGENCY+MUST (1 TP / 4 FP — net 3)
            if decomp.type == ArticleType.GENERAL and s == "AGENCY" and modal_str == "MUST":
                continue
            text = art.full_text
            title = art.title or ""
            # FP 필터: 정의·용어 조문 (제목 또는 본문 신호)
            if _DEFINITION_TITLE.search(title) or _DEFINITION_TITLE.search(text[:200]):
                continue
            # FP 필터: 양벌·벌칙·과태료 조문 (제목 또는 본문)
            if _PENALTY_TITLE.search(title):
                continue
            # FP 필터: 면책·양벌 단서 (고의·중과실 예외 명시 = 적법 패턴)
            if _EXEMPT_DANSEO.search(text):
                continue
            # FP 필터: 세제 절차 단서 (추계조사·기준소득 등)
            if _TAX_PROCEDURE.search(text):
                continue
            # FP 필터: 행정심판·소송 준용 단서
            if _ADMIN_PROC_REF.search(text):
                continue
            # 항별 최대 단서 수로 평가 (다항 조문의 항당 1개 단서는 정상)
            # R2 구조 신호 활용: decompose 결과의 proviso_count 사용
            danseo_count = _max_proviso_from_decomp(decomp) or _max_danseo_per_para(art)
            has_vague_exc = bool(_VAGUE_EXC.search(text))
            has_disposition = bool(_DISPOSITION_KEY.search(text))
            # FP 필터: 효력범위·면제 한정 단서 (처분 부재시)
            if not has_disposition and _SCOPE_LIMIT_DANSEO.search(text) and danseo_count <= 2:
                continue

            # SLM TP 부스트 (signal_candidates :: G-01):
            # 처분조 제목 (등록취소·영업정지·면직) + 단서 ≥2 + 재량 → 한 단계 상향
            strong_disposition_title = bool(_DISPOSITION_TITLE_STRONG.search(title))
            # 기본권 절차 (면회·통신·교육·진료) + 단서 ≥2 → 한 단계 상향
            fundamental_right = bool(_FUNDAMENTAL_RIGHT_CONTEXT.search(text))

            # Method B (article-level G-01 MISS 분석 — 17건):
            # 단서가 여러 항에 분산되는 경우 per-paragraph max 가 낮지만
            # article 전체로는 3-5건. 처분/금지 컨텍스트일 때 article 합산도 보조 신호.
            danseo_article_total = len(_DANSEO.findall(text))
            if danseo_count >= 4:
                severity = "심각"
            elif danseo_count >= 3:
                severity = "경고"
            elif danseo_count == 2 and has_vague_exc:
                severity = "경고"
            elif danseo_count == 2:
                severity = "주의"
            elif danseo_count == 1 and has_vague_exc and has_disposition:
                severity = "주의"
            elif (strong_disposition_title or fundamental_right) and danseo_count >= 2:
                severity = "주의"
            elif (has_disposition or strong_disposition_title or fundamental_right) and danseo_article_total >= 3:
                # 처분/금지/기본권 컨텍스트 + 전체 단서 3+ (다항 분산) → 주의
                severity = "주의"
            else:
                continue
            # TP 부스트: 처분조 단서 중첩은 한 단계 상향
            if has_disposition and severity in ("주의", "개선"):
                severity = "경고"
            # SLM TP 부스트: 강처분 제목 또는 기본권 컨텍스트 + 단서 3+ → 한 단계 상향
            if (strong_disposition_title or fundamental_right) and danseo_count >= 3:
                if severity == "주의": severity = "경고"
                elif severity == "경고": severity = "심각"

            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"단서 {danseo_count}회 (한 항 내)",
                        summary=f"단서 {danseo_count}회 중첩 (단일 항)"
                        + (" + 포괄 예외" if has_vague_exc else ""),
                        fix_type="replace",
                    ),
                )
            )
        return findings
