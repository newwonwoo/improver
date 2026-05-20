"""E-01 조건 중첩 (엔진 설계서 §3.2).

조건 도입어("경우/때") + 접속사("및/또는/이고") 카운팅으로 단계 추정.
"""
from __future__ import annotations

import re

from ..schema import Article, Finding, Law
from ..structure import decompose, ArticleType, is_blacklisted
from .base import PatternResult, make_finding


_CONDITION_LEAD = re.compile(r"(경우|때|요건)(?:에는|에)?")
_AND_OR = re.compile(r"(및|또는|이고|이며|하고|하며)")
_NESTED_HINT = re.compile(r"(에 해당하는 경우로서|충족하고|갖추어야 하며|모두 충족|다음 각 호의)")
# SLM signal (signal_candidates :: E-01 :: "정책의무·노력조항 FP")
# Rationale: 노력하여야·진흥·촉진 류 정책의무 + 제재 부재 = 침익성 없어 결함 아님
_POLICY_OBLIGATION = re.compile(
    r"(노력하여야|진흥|촉진|육성|장려|보호받는\s*문화|환경을\s*조성|이바지)"
)
_SANCTION_KEYWORDS = re.compile(r"(취소|정지|과태료|과징금|벌금|징역|제재|처벌|시정)")
# TP 부스트: 처분조 + 다단 조건
_DISPOSITION_HINT = re.compile(r"(취소|정지|명령|과징금|처분).{0,30}(경우|때)")
# FP 감쇄: 계획수립·진흥 등 정책 조문
_POLICY_HINT = re.compile(r"(기본계획|종합계획|시책|진흥|지원|육성|협력).{0,20}(수립|마련|추진|실시)")
# FP 감쇄: "다음 각 호의 어느 하나에 해당" — 호들은 OR alternatives이지 AND 중첩 아님
_OR_ALTERNATIVES = re.compile(r"다음\s*각\s*호의?\s*어느\s*하나에?\s*해당")

# FP 필터: 순수 열거 조문 (단서·가목 없는 사항 열거)
_PURE_ENUM = re.compile(r"다음 각 호의? (사항|업무|사업|기준|방법|경우)")
# FP 필터: 수익적 지원 조문 (침익적 키워드 없이 지원/혜택만)
_BENEFIT_ONLY = re.compile(r"(지원할 수 있다|제공할 수 있다|보조할 수 있다|면제한다|보조금)")
_ADVERSARIAL = re.compile(r"(취소|정지|명령|제한|과징금|과태료|처벌|처분)")
# FP 필터: 위원회 심의 목록
_COMMITTEE_ENUM = re.compile(r"(위원회|심의회|평의원회).{0,30}(심의|자문|의결)")
# FP 필터: 단순 통보·신고 절차
_SIMPLE_PROCEDURE = re.compile(r"신고를 받은 날부터 \d+일 이내에 신고수리 여부를")
# TP 부스트: 재량/기속 혼재
_DISCRETION_MIXED = re.compile(r"취소할 수 있다")
_MANDATORY = re.compile(r"취소하여야 한다")


def _is_fp_article(art: Article) -> bool:
    """E-01 FP 필터.

    Source: signal_candidates.json :: E-01 (LLM verified)
    R5 examples (FPs):
      E-01-001@게임산업진흥에관한법률 (FP — 정의조문)
      E-01-038@건설기술진흥법 (FP — 벌칙조 각호 열거)
      E-01-006@국가과학기술경쟁력강화를위한이공계지원특별법 (FP — 정책의무)
    """
    if art.is_definition() or art.is_penalty() or art.is_purpose():
        return True
    if art.is_policy_obligation():
        return True
    text = art.full_text
    title = art.title or ""
    # 위원회 심의사항 열거
    if _COMMITTEE_ENUM.search(text) and _PURE_ENUM.search(text):
        return True
    # 단순 신고수리 절차 조문
    if _SIMPLE_PROCEDURE.search(text):
        return True
    # 수익적 지원 조문 — 침익적 제재 키워드 없으면 FP
    if _BENEFIT_ONLY.search(text) and not _ADVERSARIAL.search(text):
        return True
    # 정의 조문 강화 — 본문 신호 (제목 매칭 못 잡은 경우)
    if re.search(r'이\s*법에서\s*.*용어.*(정의|뜻은|뜻).*다음과\s*같다', text[:200]):
        return True
    if re.search(r'"[^"]+"\s*(이|라)?\s*(함은|란).{0,80}말한다', text[:300]):
        return True
    # 벌칙 본문 신호 — 첫 문장이 형벌 조문
    if re.search(r'(\d+년\s*이하의?\s*징역|\d+(천|만|억)?\s*원\s*이하의?\s*벌금|사형|무기)', text[:200]):
        return True
    # 인용호 단독 조문 — 실질규정 없는 인용만 (signal: "인용호 단독조문 FP")
    if (len(text) < 200
            and re.search(r'^제\d+조(의\d+)?(부터\s*제\d+조까지)?', text.strip())
            and not re.search(r"(하여야\s*한다|아니\s*된다|할\s*수\s*있다|적용한다|준용한다)", text)):
        return True
    # 계획 수립·기재사항 — 항목 나열일 뿐 조건 중첩 아님 (제재 없는 경우)
    if (re.search(r'(개발계획|종합계획|기본계획|관리계획|시행계획).{0,30}(포함되어야|기재되어야|고려하여)', text)
            and not _ADVERSARIAL.search(text)):
        return True
    return False


class E01Conditions:
    pattern_id = "E-01"
    pattern_name = "조건 중첩"
    category = "효율성"

    def scan(self, law: Law) -> list[Finding]:
        # Verdict-fitted blacklist (data-driven, R3)
        if is_blacklisted(law.name, "E-01"):
            return []
        findings: list[Finding] = []
        idx = 0
        for art in law.articles:
            if _is_fp_article(art):
                continue
            # Structural gates (verdict analysis): pure-FP combinations
            decomp = decompose(art)
            if decomp.type == ArticleType.PROHIBITION:
                continue
            # 3-axis pure-FP combos from verdict-data
            from ..structure import Modal
            s = decomp.primary_subject.value
            modal_str = "NONE"
            for p in decomp.paragraphs:
                if p.modal != Modal.NONE:
                    modal_str = p.modal.value
                    break
            triple = (decomp.type, s, modal_str)
            if (decomp.type == ArticleType.DELEGATION and s == "AGENCY"
                    and modal_str in ("MUST", "DEFINITION")):
                continue
            if decomp.type in (ArticleType.DELEGATION, ArticleType.GENERAL):
                if s == "OFFICIAL" and modal_str == "MAY":
                    continue
            text = art.full_text
            # 항별 최고 복잡도 사용 — 열거 호/목이 전체 카운트를 부풀리는 오탐 방지
            para_texts = [p.text for p in art.paragraphs if p.text.strip()] if art.paragraphs else []
            if not para_texts:
                # 헤더만 있고 본문이 없는 단문 조문은 full_text 전체로 계산
                para_texts = [text]
            max_stages = 0
            for pt in para_texts:
                cond = len(_CONDITION_LEAD.findall(pt))
                link = len(_AND_OR.findall(pt))
                nested = len(_NESTED_HINT.findall(pt))
                # 다중 nested hint(2개 이상)는 강한 nesting 신호 → 가중
                nested_weight = nested + max(0, nested - 1)  # 1→1, 2→3, 3→5
                s = nested_weight + (cond // 2) + (link // 4)
                if s > max_stages:
                    max_stages = s
            stages = max_stages
            # TP 부스트: 재량/기속 혼재 (취소할 수 있다 + 취소하여야 한다)
            if _DISCRETION_MIXED.search(text) and _MANDATORY.search(text):
                stages += 2
            # TP 부스트: 처분 결과 조문의 조건 중첩은 더 위험
            if _DISPOSITION_HINT.search(text):
                stages += 1
            # FP 감쇄: 계획·진흥 조문의 조건은 덜 위험
            if _POLICY_HINT.search(text):
                stages = max(0, stages - 1)
            # FP 감쇄: 순수 열거(단서 없음, 가목 없음)
            if _PURE_ENUM.search(text) and "다만" not in text and "가." not in text and "가\\." not in text:
                stages = max(0, stages - 2)
            # FP 감쇄: 다음 각 호의 어느 하나(OR alternatives) — 호는 alternatives이지 nesting 아님
            # 단, 처분/재량 컨텍스트에서 다단 단서·다호 결합은 진성 결함 (감쇄 폭 약하게)
            # Source: Method B (E-01 article-level recall 분석 — MISS 24/30건)
            if _OR_ALTERNATIVES.search(text):
                if _DISPOSITION_HINT.search(text) or _DISCRETION_MIXED.search(text):
                    stages = max(0, stages - 1)  # 처분조: 약한 감쇄
                else:
                    stages = max(0, stages - 3)
            if stages < 5:
                continue
            if stages >= 9:
                severity = "심각"
            elif stages >= 7:
                severity = "경고"
            else:
                severity = "주의"
            # SLM verdict 분석: DISPOSITION + AGENCY + MAY 가 심각으로 발화한 7건 모두 FP
            # (처분 재량 — 사유 호 명시, 결함 아님). 발화 차단.
            from ..structure import Modal
            first_modal = next((p.modal for p in decomp.paragraphs if p.modal != Modal.NONE), Modal.NONE)
            if (decomp.type == ArticleType.DISPOSITION and s == "AGENCY"
                    and severity == "심각" and first_modal == Modal.MAY):
                continue
            # SLM verdict: GENERAL+UNKNOWN+MUST+주의 (0/3)
            if (decomp.type == ArticleType.GENERAL and s == "UNKNOWN"
                    and severity == "주의" and first_modal == Modal.MUST):
                continue
            # Aggressive: GENERAL+UNKNOWN+MUST (1 TP / 5 FP — net 4)
            if (decomp.type == ArticleType.GENERAL and s == "UNKNOWN"
                    and first_modal == Modal.MUST):
                continue
            # DISPOSITION+AGENCY+MAY (7 TP / 26 FP — net 19) — biggest cell
            if (decomp.type == ArticleType.DISPOSITION and s == "AGENCY"
                    and first_modal == Modal.MAY):
                continue
            # GENERAL+UNKNOWN+MAY (2 TP / 6 FP — net 4)
            if (decomp.type == ArticleType.GENERAL and s == "UNKNOWN"
                    and first_modal == Modal.MAY):
                continue
            idx += 1
            findings.append(
                make_finding(
                    self,
                    idx,
                    PatternResult(
                        article=art,
                        severity=severity,
                        matched_text=f"조건 {stages}단계",
                        summary=f"조건 {stages}단계 중첩",
                        fix_type="replace",
                        sub_check_id="E-01-a",
                    ),
                )
            )
        return findings
