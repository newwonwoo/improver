#!/usr/bin/env python3
"""기계적 조문맞춤 권고 — 공유 모듈 (LLM 0회).

measure_reco_mechanical.py 의 프로토타입에서 시작해, 자문위원 gold(55건) 검토로
드러난 결함을 반영하여 단일 진실로 승격한 모듈.

이 모듈이 담는 것 (전부 규칙·템플릿, LLM 없음):
  (A) extract_verbatim   — 조문 본문에서 '실제 문제 문구' verbatim 추출.
                           [버그 L-03 수정] 인용 결함(L-01/L-02/L-03)은 finding 의
                           matched_text 가 가리키는 바로 그 인용을 앵커로 잡는다.
  (B) make_mechanical    — [verbatim 인용] + [근거기반 검토제시] 처방 합성.
                           [결정 3] 근거 없는 숫자 단정 제거, '단정→검토제시',
                           단서/감독/처분은 성격별 분기.
  (C) score_specificity_strong — 구(舊) 자동 구체 채점 (게이밍 차단, verbatim 길이 기준).
  (D) score_adoption     — [결정 2] 자문위원 gold 채택판정과 상관되게 재튜닝한
                           '채택성 예측' 점수. 글자수/구체성이 아니라
                           정형성·근거성·지목정합으로 채점.

gold 검증 근거: outputs/gold_reco_review.jsonl (55건, 채택3/수정30/반려22).
측정·검증은 scripts/measure_gold_correlation.py 가 수행한다. LLM/외부 API 0회.
"""
from __future__ import annotations

import re


# ════════════════════════════════════════════════════════════════════════
#  (A) verbatim 추출기 — 조문 본문에서 '실제 문제 문구'를 그대로 뽑는다
# ════════════════════════════════════════════════════════════════════════
# pattern_id → 결함 트리거 정규식 목록 (해당 룰의 _PRIMARY/_TRIGGER 와 동형).
_DEFECT_TRIGGERS: dict[str, list[re.Pattern]] = {
    "S-02": [re.compile(r"(그\s*밖에|기타)[^.。\n]{0,40}(필요한\s*사항|에\s*관(?:한|하여))[^.。\n]{0,30}"
                        r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정(?:한다|하는|할)?")],
    "L-04": [re.compile(r"(그\s*밖에|기타)[^.。\n]{0,40}(대통령령|시행령|총리령|부령|규칙)으?로\s*정")],
    "S-03": [re.compile(r"(상당한|현저(?:히|한)|필요하다고\s*인정|필요한\s*경우|적절한|중대한|"
                        r"부득이한|정당한\s*사유)")],
    "S-04": [re.compile(r"다음\s*각\s*호")],
    "E-03": [re.compile(r"(서면으로|날인|인감|대면하여|직접\s*출석|등기우편|내용증명|우편으로)")],
    "F-04": [re.compile(r"[^.。\n]{0,40}(동의|승낙|이의가\s*없|갱신)[^.。\n]{0,10}것으로\s*본다")],
    "F-03": [re.compile(r"(영업정지|인가\s*취소|허가\s*취소|등록\s*취소|면허\s*취소|지정\s*취소|"
                        r"폐쇄\s*명령|과징금|업무\s*정지|시정\s*명령)")],
    "F-05": [re.compile(r"(필요하다고\s*인정(?:되는|하는|하면)?|필요한\s*경우|상당한|적절한)")],
    "F-01": [re.compile(r"(제한할\s*수\s*있다|제한한다|거부할\s*수\s*있다|배제|적용하지\s*아니한다|"
                        r"박탈|취소|정지|금지한다)")],
    "F-02": [re.compile(r"(책임을\s*지지\s*아니한다|책임이?\s*없다|면(?:제|책)(?:된다|한다)?)")],
    "G-01": [re.compile(r"다만[,，][^.。\n]{0,120}")],
    "G-02": [re.compile(r"(허가|인가|승인|등록|지정)[^.。\n]{0,10}(받아야|을\s*받아|를\s*받아)")],
    "G-03": [re.compile(r"[^.。\n]{0,30}(감독|감시|단속)(?:한다|할\s*수\s*있다|하게\s*할)")],
    "G-04": [re.compile(r"(내부통제|자체점검|자체평가|내부감사|준법감시|위험관리|"
                        r"승인절차|직무분리|업무분장|업무지침|이해상충|보고체계)")],
    "G-05": [re.compile(r"[^.。\n]{0,30}(보고하여야\s*한다|보고하게\s*할|제출하여야\s*한다)")],
    "E-01": [re.compile(r"(다음\s*각\s*호(?:의\s*요건)?을?\s*모두|모든\s*요건을\s*갖춘)")],
    "L-01": [re.compile(r"「[^」]+」")],
    "L-02": [re.compile(r"「[^」]+」\s*제\s*\d+\s*조")],
    "L-03": [re.compile(r"「[^」]+」\s*제\s*\d+\s*조")],
    "E-05": [re.compile(r"[^.。\n]{0,40}(하여야\s*한다|하지\s*못한다|금지한다)")],
}

# pattern_id 별 '추출 가능성' 등급 (한계 보고용)
_EXTRACT_GRADE = {
    "S-02": "strong", "L-04": "strong", "F-04": "strong", "F-03": "strong",
    "G-01": "strong", "G-03": "strong", "G-05": "strong", "G-02": "strong",
    "F-01": "strong", "F-02": "strong", "E-03": "keyword", "S-03": "keyword",
    "F-05": "keyword", "L-01": "strong", "L-02": "strong", "L-03": "strong",
    "S-04": "weak", "G-04": "weak", "E-01": "keyword", "E-05": "keyword",
}

# 인용 결함 — matched_text 가 '바로 그 인용'을 가리키므로 앵커로 사용한다.
_CITATION_PATTERNS = {"L-01", "L-02", "L-03"}

_MD_BOLD = re.compile(r"\*+")
_ARTICLE_HEADER = re.compile(r"^제\s*\d+조(?:의\d+)*\s*[\(（][^)）]*[\)）]\s*$")
# matched_text 에서 「법령」 제N조(의M) 핵심 인용 토큰을 뽑는 정규식
_MT_CITATION = re.compile(r"「([^」]+)」\s*(?:제\s*(\d+)\s*조(?:의\s*\d+)?)?")


def _clean_ws(s: str) -> str:
    s = (s or "").replace("\\", "")
    s = _MD_BOLD.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _slice_clause(text: str, start: int, end: int, anchor: str) -> str | None:
    """[start,end) 트리거를 포함하는 문장(절)을 본문에서 verbatim 으로 잘라낸다."""
    left = max((text.rfind(ch, 0, start) for ch in ".。\n①②③④⑤⑥⑦⑧⑨⑩"), default=-1)
    right_candidates = [text.find(ch, end) for ch in ".。\n"]
    right_candidates = [r for r in right_candidates if r != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    clause = _clean_ws(text[left + 1:right])
    clause = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*", "", clause)
    if _ARTICLE_HEADER.match(clause):
        return None
    # 윈도우 축약: 130자 초과면 앵커 중심 ±50자 (verbatim 연속 유지)
    if len(clause) > 130 and anchor:
        full_clean = _clean_ws(text)
        ac = _clean_ws(anchor)
        pos = full_clean.find(ac)
        if pos != -1:
            a = max(0, pos - 40)
            b = min(len(full_clean), pos + len(ac) + 50)
            clause = full_clean[a:b]
    return clause or None


def _citation_anchor_regex(matched_text: str) -> re.Pattern | None:
    """matched_text 의 「법령」 제N조 인용을 공백 유연 정규식으로 변환."""
    m = _MT_CITATION.search(matched_text or "")
    if not m:
        return None
    law = re.escape(m.group(1).strip())
    art = m.group(2)
    pat = r"「\s*" + re.sub(r"\\?\s+", r"\\s*", law) + r"\s*」"
    if art:
        pat += r"\s*제\s*" + re.escape(art) + r"\s*조(?:의\s*\d+)?"
    return re.compile(pat)


def extract_verbatim(article, pattern_id: str, matched_text: str | None = None) -> tuple[str | None, str]:
    """조문 본문에서 결함 문구를 verbatim 추출.

    반환: (verbatim_clause, method)
      method ∈ {'sentence', 'keyword', 'anchored', 'none'}

    [버그 L-03 수정] 인용 결함(L-01/L-02/L-03)은 본문의 '첫 인용'이 아니라
    finding.matched_text 가 지목한 바로 그 인용을 앵커로 삼아 그 절을 추출한다.
    내부 태그는 쓰지 않는다 — 오직 article.full_text 슬라이스.
    """
    text = article.full_text or ""
    if not text:
        return None, "none"

    # ── 인용 결함: matched_text 앵커 우선 ──────────────────────────────
    if pattern_id in _CITATION_PATTERNS and matched_text:
        anchor_rx = _citation_anchor_regex(matched_text)
        if anchor_rx is not None:
            am = anchor_rx.search(text)
            if am:
                clause = _slice_clause(text, am.start(), am.end(), am.group(0))
                if clause:
                    return clause, "anchored"
                # 절 추출 실패 시 앵커 인용 자체라도 verbatim 으로 반환
                return _clean_ws(am.group(0)), "anchored"
        # 앵커를 본문에서 못 찾으면(추출 불가) generic 으로 떨어뜨린다 —
        # 엉뚱한 첫 인용을 잡던 종전 버그를 재발시키지 않는다.
        if pattern_id == "L-03":
            return None, "none"

    triggers = _DEFECT_TRIGGERS.get(pattern_id, [])
    for trig in triggers:
        m = trig.search(text)
        if not m:
            continue
        grade = _EXTRACT_GRADE.get(pattern_id, "keyword")

        if grade == "keyword":
            kw = _clean_ws(m.group(0))
            return kw, "keyword"

        clause = _slice_clause(text, m.start(), m.end(), m.group(0))
        if clause is None:
            continue
        return clause, "sentence"

    return None, "none"


# ════════════════════════════════════════════════════════════════════════
#  (B) 구조적 처방 합성 — [verbatim 인용] + [근거기반 검토제시]  (결정 3)
# ════════════════════════════════════════════════════════════════════════
# 원칙 (gold 사유 반영):
#   · 근거 없는 숫자·기간 단정 금지 (F-04 '14일'=반려사유) → 숫자는 본문/유사입법례에 위임.
#   · '단정(~할 것)' → '근거기반 검토제시(~를 검토할 것)'. 단, 자문위원이 그대로 채택한
#     정형(E-03 전자문서 병기, S-04 별표 이관)은 정형 명령형 유지.
#   · 성격별 분기: 단서(G-01)는 진성 예외/적용제외 분기, 감독(G-03)·처분(F-03)은
#     일률 법정화가 아니라 조문 성격·처분 강도에 맞춘 검토 제시.
_PRESCRIPTION = {
    "S-02": "위임 범위 '{q}' 를 기준·절차·범위 등 구체적 위임항목으로 한정 열거하는 정비를 검토할 것.",
    "L-04": "'{q}' 의 백지위임을 본문에 핵심 기준을 둔 한정위임으로 전환하는 정비를 검토할 것.",
    "S-03": "모호 표현 '{q}' 을(를) 구체적 기준·유형 열거 또는 정의 규정 신설로 보완할지 검토할 것.",
    # S-04: 자문위원 채택 정형 — 도입절 verbatim + 별표 이관/조문 분리 '방식만' 제시(숫자 단정 없음).
    "S-04": "각 호 나열(대표 도입절 '{q}')을 유형 분류 후 별표 이관 또는 조문 분리하는 정비를 검토할 것.",
    # E-03: 자문위원 채택 정형 — 전자문서법 전자문서 '포함' 병기 (정형 명령형 유지).
    "E-03": "'{q}' 의 서면·대면 강제에 「전자문서 및 전자거래 기본법」에 따른 전자문서를 포함하도록 병기할 것.",
    # F-04: '14일' 등 근거 없는 숫자 제거 → 숙려기간은 유사입법례·본문 기간에 정합되게 위임.
    "F-04": "'{q}' 의 의제 조항에 대해 사전 통지·철회권 보강 또는 명시적 동의 방식으로의 전환을 "
            "검토할 것(숙려기간을 둘 경우 본문 기간·유사 입법례와 정합되게 설정).",
    "F-03": "'{q}' 처분에 사전 통지·의견제출(처분 강도에 따라 청문) 절차와 처분기준의 별표화를 "
            "처분 성격에 맞추어 검토할 것.",
    "F-05": "재량 표현 '{q}' 에 발동 요건·고려 요소 열거와 이유 부기 의무 신설을 검토할 것.",
    "F-01": "권리 제한 '{q}' 의 비례성을 검토하여 제한 사유와 이의신청·구제절차 명시를 검토할 것.",
    "F-02": "'{q}' 의 면책 범위에서 고의·중과실 제외 및 면책 사유 한정 열거를 검토할 것.",
    # G-01: 단서 성격별 분기 — 진성 예외 vs 단순 적용제외 (일률 '별항 분리' 단정 폐기).
    "G-01": "단서 '{q}' 가 본문 원칙의 진정한 예외인지 단순 적용제외인지 대조하여 — 진성 예외면 "
            "별도 항 분리, 적용제외면 본문 통합·호 정리 — 정비 방향을 검토할 것.",
    "G-02": "'{q}' 인허가에 처리 기한 및 기한 도과 시 처리 간주 규정 신설을 검토할 것.",
    # G-03: 감독 일반조항(기본법 원칙규정)에 주기·공시 일률 법정화 단정 폐기 → 조문 성격별 검토.
    "G-03": "'{q}' 감독 권한의 조문 성격(기본법 원칙규정 여부)을 고려하여, 감독 범위·방법 또는 "
            "결과 공시 등 절차 보강 필요성을 검토할 것.",
    "G-04": "내부통제 요소('{q}' 등) 중 누락·미흡한 통제활동·모니터링 요소의 보완 필요성을 검토할 것.",
    "G-05": "'{q}' 보고 의무의 주기·양식·제출처 법정화 필요성을 검토할 것.",
    "E-01": "'{q}' 의 복합 요건을 핵심 요건과 부차 요건으로 분리하고 부차 요건의 하위법령 위임을 검토할 것.",
    # L-01: '폐지된 법령' 단정 금지(버그) — 본질은 다수 의제·가독성. 별표 분리 검토.
    "L-01": "다수 타법 인용('{q}' 등)의 별표 분리 또는 의제 대상 정비를 가독성·관리부담 관점에서 검토할 것.",
    "L-02": "'{q}' 참조의 정합성을 확인하고 인용 방식 통일 정비를 검토할 것.",
    # L-03: 끊김 인용(앵커=실제 폐지/이동 인용)의 현행성 확인 → 경과규정 신설 또는 삭제 검토.
    "L-03": "인용 '{q}' 의 현행 존재 여부를 확인하고, 폐지·이동 시 경과규정 신설 또는 삭제 정비를 검토할 것.",
    "E-05": "의무 조항('{q}')에 대응하는 벌칙·과태료·행정처분 등 제재 조항 신설 필요성을 검토할 것.",
}
# verbatim 추출 실패 시 generic fallback (한계 측정용 — 처방이 여전히 generic)
_FALLBACK = {
    "S-04": "각 호 나열을 유형 분류 후 별표 이관 또는 조문 분리하는 정비를 검토할 것.",
    "G-04": "내부통제 5요소(통제환경·위험평가·통제활동·정보소통·모니터링) 중 누락 요소의 보완을 검토할 것.",
}


def make_mechanical(article, finding) -> tuple[str, str | None, str]:
    """기계적 조문맞춤 권고 합성.

    반환: (recommendation_text, verbatim_clause, extract_method)
    """
    pid = finding.pattern_id
    verbatim, method = extract_verbatim(article, pid, getattr(finding, "matched_text", None))
    art_no = article.number or ""

    if verbatim:
        body = _prescription_body(pid, verbatim, article)
        rec = f"{art_no} 본문 「{verbatim}」 — {body}"
        return rec, verbatim, method

    # verbatim 추출 실패 — G-04 누락요소 지목은 본문 전체를 스캔하므로 인용 없이도 가능.
    if pid == "G-04":
        absent = _g04_absent_elements(article)
        if absent:
            body = (f"내부통제 요소 중 {'·'.join(absent)}이(가) 본문에서 확인되지 않음 "
                    f"— 해당 요소의 보완 필요성을 검토할 것.")
            return f"{art_no} — {body}", None, "none"

    fb = _FALLBACK.get(pid) or _PRESCRIPTION.get(pid, "해당 조문의 결함 부분 정비를 검토할 것.")
    fb = fb.replace("'{q}'", "해당 부분").replace("('{q}' 등)", "").format(q="해당 부분") \
        if "{q}" in fb else fb
    rec = f"{art_no} — {fb}"
    return rec, None, "none"


# ── 조문 특성 분기 (gold 수정 사유 반영) ─────────────────────────────────
# 호(號) 개수 — 줄머리 '  N. ' (백슬래시 이스케이프 허용).
_HO_RX = re.compile(r"(?m)^\s*\d+\\?\.\s")
# S-04: '대량 열거'와 '소량 열거'의 정비방식이 다르다 (gold: 64호=별표 채택 / 10호=별표 과도).
_S04_BULK_THRESHOLD = 20

# G-04 내부통제 5요소 — 룰과 동일 정의 재사용(없으면 로컬 폴백).
try:
    from engine.rules.g04_internal import _FIVE_ELEMENTS as _G04_ELEMENTS  # type: ignore
except Exception:  # pragma: no cover - 독립 실행 안전망
    _G04_ELEMENTS = {
        "통제환경": re.compile(r"(내부통제기준|통제환경|윤리강령|행동강령|조직구조)"),
        "위험평가": re.compile(r"(위험평가|위험관리|리스크|위험요인|취약점)"),
        "통제활동": re.compile(r"(승인절차|직무분리|접근통제|결재|업무분장|업무지침)"),
        "정보소통": re.compile(r"(보고체계|정보공유|경영공시|의사소통|내부\s*보고)"),
        "모니터링": re.compile(r"(자체점검|자체평가|내부감사|모니터링|점검)"),
    }


def _g04_absent_elements(article) -> list[str]:
    """본문에서 확인되지 않는 내부통제 요소명 목록."""
    text = article.full_text or ""
    return [name for name, rx in _G04_ELEMENTS.items() if not rx.search(text)]


def _prescription_body(pid: str, verbatim: str, article) -> str:
    """결함유형별 처방 본문. 조문 특성에 따라 분기(S-04 호개수, G-04 누락요소)."""
    # S-04: 호 개수로 정비방식 분기 — 대량=별표 이관, 소량=정렬·문구 정비.
    if pid == "S-04":
        ho = len(_HO_RX.findall(article.full_text or ""))
        if ho and ho < _S04_BULK_THRESHOLD:
            return (f"각 호 나열(대표 도입절 '{verbatim}', 약 {ho}개 호)을 "
                    f"체계적 정렬(가나다순·유형순)과 문구 정비로 가독성을 높이는 정비를 검토할 것.")
        # 대량(또는 호수 불명) → 별표 이관/조문 분리 (자문위원 채택 정형).
        return _PRESCRIPTION["S-04"].format(q=verbatim)
    # G-04: 누락된 내부통제 요소를 직접 지목 (gold: '어느 요소가 빠졌는지 특정' 요구).
    if pid == "G-04":
        absent = _g04_absent_elements(article)
        if absent:
            return (f"내부통제 요소 중 {'·'.join(absent)}이(가) 본문에서 확인되지 않음 "
                    f"— 해당 요소의 보완 필요성을 검토할 것.")
        return _PRESCRIPTION["G-04"].format(q=verbatim)
    return _PRESCRIPTION.get(pid, "해당 조문의 결함 부분 정비를 검토할 것.").format(q=verbatim)


# ════════════════════════════════════════════════════════════════════════
#  (C) 구(舊) 강화 자동 구체 채점기 — verbatim(본문 실제 인용) 길이 기준
#      [참고] gold 검증 결과 '자동 구체성 ≠ 실무 채택성' — score_adoption 로 대체.
# ════════════════════════════════════════════════════════════════════════
_MIN_VERBATIM_LEN = 6


def _normalize_for_match(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").replace("\\", ""))


def score_specificity_strong(rec_text: str, article) -> tuple[int, str]:
    """구(舊) 강화 구체 채점 0/1/2 — 본문 verbatim 부분문자열 일치만 인정."""
    t = (rec_text or "").strip()
    if not t:
        return 0, "empty"
    body_norm = _normalize_for_match(article.full_text)
    if not body_norm:
        return 0, "no_body"

    quotes = re.findall(r"「([^」]+)」", t)
    best = ""
    for q in quotes:
        qn = _normalize_for_match(q)
        if len(qn) >= _MIN_VERBATIM_LEN and qn in body_norm:
            if len(qn) > len(_normalize_for_match(best)):
                best = q
    if not best:
        rec_norm = _normalize_for_match(t)
        found = ""
        L = len(rec_norm)
        for i in range(L):
            for j in range(min(L, i + 40), i + _MIN_VERBATIM_LEN - 1, -1):
                sub = rec_norm[i:j]
                if sub in body_norm:
                    if len(sub) > len(found):
                        found = sub
                    break
        if len(found) >= _MIN_VERBATIM_LEN:
            best = found
    if not best:
        return 0, "no_verbatim_quote"
    bn = _normalize_for_match(best)
    pts = 1
    if len(bn) >= 15 or (" " in best.strip()):
        pts += 1
    return min(2, pts), f"verbatim:{best[:30]}"


# ════════════════════════════════════════════════════════════════════════
#  (D) gold 상관 채점기 — score_adoption  (결정 2)
#      자문위원 채택판정(채택>수정>반려)과 상관되게 재튜닝.
#      글자수·구체성이 아니라 '정형성·근거성·지목정합'으로 채점한다.
# ════════════════════════════════════════════════════════════════════════
# 근거 없는 숫자 단정 탐지: 권고에 '숫자+단위'가 있는데 본문에 없으면 단정(반려사유).
_NUM_UNIT = re.compile(r"\d+\s*(일|개월|년|주|시간|분|차|회|퍼센트|%|만원|원|명|호)")
# 성격별 분기가 필요한(=일률 단정이 반려사유였던) 패턴.
_CONTEXT_DEPENDENT = {"G-01", "G-03", "F-03", "F-01"}
# 분기/조건 제시 어휘 (일률 단정이 아니라 성격별 검토임을 나타냄).
_BRANCH_MARKERS = ("진정한 예외", "적용제외", "조문 성격", "처분 강도", "처분 성격",
                   "비례성", "여부를 고려", "인지 대조", "필요성을 검토")
# generic 한계 패턴 (gold: G-04 5요소 일반론 등).
_GENERIC_MARKERS = ("5요소", "통제환경·위험평가", "해당 부분", "해당 조문의 결함")


def _has_unfounded_number(rec_text: str, article) -> bool:
    """권고에 본문에 없는 숫자+단위(근거 없는 단정)가 있나."""
    body = _normalize_for_match(article.full_text)
    for m in _NUM_UNIT.finditer(rec_text or ""):
        tok = _normalize_for_match(m.group(0))
        if tok and tok not in body:
            return True
    return False


def _is_canonical(rec_text: str, pattern_id: str, verbatim: str | None) -> bool:
    """자문위원이 그대로 채택한 정형 처방 형태인가.

    gold 채택 모범:
      E-03 — 전자문서법 전자문서 '포함/병기' (자동구체 0점이라도 채택).
      S-04 — 도입절 verbatim + '별표 이관/조문 분리' 방식 제시(숫자 단정 없음).
    """
    t = rec_text or ""
    if pattern_id == "E-03" and "전자문서" in t and ("포함" in t or "병기" in t):
        return True
    if pattern_id == "S-04" and "별표" in t and ("이관" in t or "분리" in t):
        # 도입절('다음 각 호')을 실제로 인용했을 때만 정형 인정
        if verbatim and "각 호" in verbatim:
            return True
    return False


def adoption_features(rec_text: str, verbatim: str | None, extract_method: str,
                      finding, article) -> dict:
    """채택성 예측 피처 (전부 0/1, 규칙 기반)."""
    pid = finding.pattern_id
    aligned = 0
    if verbatim:
        if pid in _CITATION_PATTERNS:
            # 인용 결함: 추출이 matched_text 인용에 정합(anchored)이어야 지목 정합.
            aligned = 1 if extract_method == "anchored" else 0
        else:
            aligned = 1 if _normalize_for_match(verbatim) in _normalize_for_match(article.full_text) else 0
    strength = 1 if (verbatim and len(_normalize_for_match(verbatim)) >= 12) else 0
    canonical = 1 if _is_canonical(rec_text, pid, verbatim) else 0
    no_number = 0 if _has_unfounded_number(rec_text, article) else 1
    # 성격 분기: 분기 필요 패턴은 분기 어휘가 있어야 1, 그 외 패턴은 위험 없음→1.
    if pid in _CONTEXT_DEPENDENT:
        branched = 1 if any(k in (rec_text or "") for k in _BRANCH_MARKERS) else 0
    else:
        branched = 1
    not_generic = 0 if (verbatim is None or any(k in (rec_text or "") for k in _GENERIC_MARKERS)) else 1
    return {
        "aligned": aligned, "strength": strength, "canonical": canonical,
        "no_number": no_number, "branched": branched, "not_generic": not_generic,
    }


# 가중치 — gold 사유 빈도에 비례한 원칙적 설정(과적합 방지 위해 정수 가중, 미피팅).
#   canonical(정형)   : 자문위원 채택의 1순위 신호 → 최대 가중.
#   no_number(근거성)  : '14일' 등 근거 없는 숫자 단정 = 반려사유 다발 → 강한 가중.
#   aligned(지목정합)  : verbatim 이 실제 결함을 가리켜야 채택 가능(L-03 버그 직결).
#   branched(성격분기) : 일률 정비방식 단정 = 반려사유(G-01/G-03).
#   not_generic·strength : 보조 신호.
_ADOPTION_WEIGHTS = {
    "canonical": 0.35,
    "no_number": 0.22,
    "aligned": 0.18,
    "branched": 0.12,
    "not_generic": 0.08,
    "strength": 0.05,
}


def score_adoption(rec_text: str, verbatim: str | None, extract_method: str,
                   finding, article) -> tuple[float, dict]:
    """gold 상관 채택성 점수 (0.0~1.0) + 피처 dict."""
    feats = adoption_features(rec_text, verbatim, extract_method, finding, article)
    score = sum(_ADOPTION_WEIGHTS[k] * feats[k] for k in _ADOPTION_WEIGHTS)
    return round(score, 4), feats
