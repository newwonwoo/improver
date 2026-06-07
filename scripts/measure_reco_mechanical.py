#!/usr/bin/env python3
"""V6 후속 — '기계적 조문맞춤 권고' 프로토타입 측정 하네스 (LLM 절대 미사용).

[배경 / 직전 시도의 실패]
- Layer1 generic 템플릿: 구체율 21%, 조문 고유성 ≈0 (measure_reco_quality.py).
- 직전 '조문번호 주입'(measure_reco_article_aware.py): 자동채점기를 게이밍.
  prefix 의 인용이 내부 패턴태그('아날로그(강)', '강한 처분')라 무의미했음.
  → 채점기가 '제N조' 존재만으로 구체점수를 줘서 과대평가.

[이번 지시 — 전부 기계적, LLM 없음]
1. measure_reco_quality.py 와 동일 표본·동일 파이프라인 재사용.
2. 기계적 조문맞춤 권고 생성기 (이 스크립트 내부 함수, engine/config 무수정):
   - 파서 구조(Article.full_text / paragraphs)에서 그 finding 의 **실제 문제 문구를
     verbatim 추출**. 내부 태그(matched_text='아날로그(강)') 가 아니라 조문 본문의
     실제 절(예: 포괄위임이면 "...그 밖에 필요한 사항은 대통령령으로 정한다").
   - 결함유형(pattern_id)별 구조적 처방 합성:
       [verbatim 인용]  +  [결함에 맞는 개정 동작(한정열거/분리/기준명시 등)]
     전부 규칙·템플릿 슬롯 채우기. LLM 없음.
3. 채점기 강화: 기존 구체 채점의 취약점(=조문번호·내부태그 존재만으로 만점) 수정.
   → **권고에 포함된 인용이 그 조문 본문에서 verbatim 으로 실제 추출된 구절일 때만**
     구체 점수. 단순 '제N조'·내부태그는 불인정.
4. [baseline Layer1] vs [기계적 조문맞춤] 을 강화 채점기로 비교.

[출력]
    outputs/reco_mechanical_measure.json
    stdout — 3축 비교 + 예시 3건 + 한계

측정 전용. 프로덕션 무수정. 커밋 금지. LLM/외부 API 호출 0회.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine import fpc, recommender, scorer  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402

# baseline 하네스의 표본/파이프라인/유틸/채점기 재사용 (동일 잣대 보장)
import scripts.measure_reco_quality as base  # noqa: E402

REPORT_PATH = REPO / "outputs" / "reco_mechanical_measure.json"


# ════════════════════════════════════════════════════════════════════════
#  (A) verbatim 추출기 — 조문 본문에서 '실제 문제 문구'를 그대로 뽑는다
# ════════════════════════════════════════════════════════════════════════
# 핵심: 각 pattern_id 의 '결함 트리거'를 조문 full_text 에서 다시 찾아,
#       그 트리거를 포함하는 **문장(절)** 을 verbatim 으로 잘라낸다.
#       내부 태그(matched_text)가 아니라 조문 본문 그 자체에서 나온 문자열.

# pattern_id → 결함 트리거 정규식 목록 (해당 룰의 _PRIMARY/_TRIGGER 와 동형).
# 첫 매칭을 '대표 결함 위치'로 삼는다.
_DEFECT_TRIGGERS: dict[str, list[re.Pattern]] = {
    # 포괄위임 — "그 밖에 … 필요한 사항은 대통령령으로 정한다"
    "S-02": [re.compile(r"(그\s*밖에|기타)[^.。\n]{0,40}(필요한\s*사항|에\s*관(?:한|하여))[^.。\n]{0,30}"
                        r"(대통령령|시행령|총리령|부령|시행규칙|고시)으?로\s*정(?:한다|하는|할)?")],
    "L-04": [re.compile(r"(그\s*밖에|기타)[^.。\n]{0,40}(대통령령|시행령|총리령|부령|규칙)으?로\s*정")],
    # 모호 표현 — 본문 내 모호어 자체가 verbatim 근거 (S-03 는 별도 키워드 추출 경로)
    "S-03": [re.compile(r"(상당한|현저(?:히|한)|필요하다고\s*인정|필요한\s*경우|적절한|중대한|"
                        r"부득이한|정당한\s*사유)")],
    # 과다 열거 — 호가 많은 항 (verbatim: 그 항의 도입부)
    "S-04": [re.compile(r"다음\s*각\s*호")],
    # 아날로그 강제 — 서면/날인/대면 등
    "E-03": [re.compile(r"(서면으로|날인|인감|대면하여|직접\s*출석|등기우편|내용증명|우편으로)")],
    # 의사표시 의제 — "…한 것으로 본다"
    "F-04": [re.compile(r"[^.。\n]{0,40}(동의|승낙|이의가\s*없|갱신)[^.。\n]{0,10}것으로\s*본다")],
    # 처분 — 영업정지/취소/과징금 등
    "F-03": [re.compile(r"(영업정지|인가\s*취소|허가\s*취소|등록\s*취소|면허\s*취소|지정\s*취소|"
                        r"폐쇄\s*명령|과징금|업무\s*정지|시정\s*명령)")],
    # 재량 — "필요하다고 인정", "필요한 경우" 등
    "F-05": [re.compile(r"(필요하다고\s*인정(?:되는|하는|하면)?|필요한\s*경우|상당한|적절한)")],
    # 권리제한 — 제한/배제/거부
    "F-01": [re.compile(r"(제한할\s*수\s*있다|제한한다|거부할\s*수\s*있다|배제|적용하지\s*아니한다|"
                        r"박탈|취소|정지|금지한다)")],
    # 면책 — 책임을 지지 않는다
    "F-02": [re.compile(r"(책임을\s*지지\s*아니한다|책임이?\s*없다|면(?:제|책)(?:된다|한다)?)")],
    # 단서 남용 — "다만, …"
    "G-01": [re.compile(r"다만[,，][^.。\n]{0,120}")],
    # 인허가 — 허가/인가 받아야
    "G-02": [re.compile(r"(허가|인가|승인|등록|지정)[^.。\n]{0,10}(받아야|을\s*받아|를\s*받아)")],
    # 감독 — "…감독한다 / 감독할 수 있다"
    "G-03": [re.compile(r"[^.。\n]{0,30}(감독|감시|단속)(?:한다|할\s*수\s*있다|하게\s*할)")],
    # 내부통제 — 통제/점검/감사 관련 (verbatim 근거 약함 → 후술 한계)
    "G-04": [re.compile(r"(내부통제|자체점검|자체평가|내부감사|준법감시|위험관리)")],
    # 보고 — "…보고하여야 한다"
    "G-05": [re.compile(r"[^.。\n]{0,30}(보고하여야\s*한다|보고하게\s*할|제출하여야\s*한다)")],
    # 복합조건 — "다음 각 호의 요건을 모두 갖춘"
    "E-01": [re.compile(r"(다음\s*각\s*호(?:의\s*요건)?을?\s*모두|모든\s*요건을\s*갖춘)")],
    # 타법 다수 인용 — 「법령」 토큰
    "L-01": [re.compile(r"「[^」]+」")],
    "L-02": [re.compile(r"「[^」]+」\s*제\s*\d+\s*조")],
    "L-03": [re.compile(r"「[^」]+」\s*제\s*\d+\s*조")],
    # 제재 부재 — 의무문 (verbatim: 의무 조항)
    "E-05": [re.compile(r"[^.。\n]{0,40}(하여야\s*한다|하지\s*못한다|금지한다)")],
}

# pattern_id 별 '추출 가능성' 등급 (한계 보고용)
#   strong  = 본문에 결함 문구가 통째로 존재 → 깔끔한 verbatim 절 추출 가능
#   keyword = 본문에 모호어/키워드만 존재 → 단어 verbatim 은 되나 '문장 처방' 약함
#   weak    = 결함이 '부재'(보고의무 없음 등)/'구조량'(호 30개)이라 verbatim 곤란
_EXTRACT_GRADE = {
    "S-02": "strong", "L-04": "strong", "F-04": "strong", "F-03": "strong",
    "G-01": "strong", "G-03": "strong", "G-05": "strong", "G-02": "strong",
    "F-01": "strong", "F-02": "strong", "E-03": "keyword", "S-03": "keyword",
    "F-05": "keyword", "L-01": "strong", "L-02": "strong", "L-03": "strong",
    "S-04": "weak", "G-04": "weak", "E-01": "keyword", "E-05": "keyword",
}

_SENT_SPLIT = re.compile(r"(?<=[.。])\s+|\n+")


_MD_BOLD = re.compile(r"\*+")
_ARTICLE_HEADER = re.compile(r"^제\s*\d+조(?:의\d+)*\s*[\(（][^)）]*[\)）]\s*$")


def _clean_ws(s: str) -> str:
    s = (s or "").replace("\\", "")
    s = _MD_BOLD.sub("", s)          # 마크다운 ** 굵게 표기 제거
    return re.sub(r"\s+", " ", s).strip()


def extract_verbatim(article, pattern_id: str) -> tuple[str | None, str]:
    """조문 본문에서 결함 문구를 verbatim 추출.

    반환: (verbatim_clause, method)
      verbatim_clause : 조문 full_text 의 부분 문자열 (정규화 공백만 손질). 없으면 None.
      method          : 'sentence'(트리거 포함 문장 절) / 'keyword'(키워드 단독) / 'none'.

    내부 태그는 절대 쓰지 않는다 — 오직 article.full_text 슬라이스.
    """
    text = article.full_text or ""
    if not text:
        return None, "none"

    triggers = _DEFECT_TRIGGERS.get(pattern_id, [])
    for trig in triggers:
        m = trig.search(text)
        if not m:
            continue
        grade = _EXTRACT_GRADE.get(pattern_id, "keyword")

        # keyword 등급: 매칭 토큰 자체를 verbatim 인용 (문장 처방은 약함)
        if grade == "keyword":
            kw = _clean_ws(m.group(0))
            # S-03/F-05 모호어는 그 단어가 본문에 실재 → verbatim 인정
            if kw and kw in _clean_ws(text):
                return kw, "keyword"
            return kw, "keyword"

        # strong 등급: 트리거를 포함하는 '문장(절)' 을 통째로 추출
        # 문장 경계로 자르되, 너무 길면 트리거 주변 윈도우로 축약.
        start = m.start()
        # 직전 문장 경계
        left = max((text.rfind(ch, 0, start) for ch in ".。\n①②③④⑤⑥⑦⑧⑨⑩"), default=-1)
        # 다음 문장 경계
        right_candidates = [text.find(ch, m.end()) for ch in ".。\n"]
        right_candidates = [r for r in right_candidates if r != -1]
        right = min(right_candidates) + 1 if right_candidates else len(text)
        clause = text[left + 1:right]
        clause = _clean_ws(clause)
        # 원문자 항번호 제거 (앞머리 ① 등)
        clause = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\s*", "", clause)
        # 조문 헤더 라인('제N조 (제목)')만 잡힌 경우는 결함 문구가 아님 → 추출 실패 처리
        if _ARTICLE_HEADER.match(clause):
            continue
        # 윈도우 축약: 100자 초과면 트리거 중심 ±50자 (단 verbatim 연속 유지)
        if len(clause) > 130:
            full_clean = _clean_ws(text)
            tg = _clean_ws(m.group(0))
            pos = full_clean.find(tg)
            if pos != -1:
                a = max(0, pos - 40)
                b = min(len(full_clean), pos + len(tg) + 50)
                clause = full_clean[a:b]
        if clause:
            return clause, "sentence"

    # 트리거 미발견 (weak 등급에서 흔함)
    return None, "none"


# ════════════════════════════════════════════════════════════════════════
#  (B) 구조적 처방 합성 — [verbatim 인용] + [결함별 개정 동작]
# ════════════════════════════════════════════════════════════════════════
# 결함유형별 개정 동작 슬롯 (순수 템플릿, LLM 없음).
_PRESCRIPTION = {
    "S-02": "위임 범위를 '{q}' 와 같은 포괄표현에서 구체적 위임항목(기준·절차·범위)으로 한정 열거할 것.",
    "L-04": "'{q}' 의 백지위임을 본문에 핵심 기준을 둔 한정위임으로 전환할 것.",
    "S-03": "모호 표현 '{q}' 을(를) 구체적 수치·기준·유형 열거로 대체할 것.",
    "S-04": "각 호 나열을 유형 분류 후 별표 이관 또는 조문 분리할 것 (대표 도입절: '{q}').",
    "E-03": "'{q}' 의 아날로그 강제 절차에 '전자문서법에 따른 전자문서를 포함한다'를 병기할 것.",
    "F-04": "'{q}' 의 의제 조항에 사전 통지·14일 이상 숙려기간·철회권을 명시하거나 명시적 동의 방식으로 전환할 것.",
    "F-03": "'{q}' 처분에 사전 통지·의견제출(청문) 절차와 처분기준표(별표)를 명시할 것.",
    "F-05": "재량 표현 '{q}' 에 발동 요건·고려 요소를 열거하고 이유 부기 의무를 신설할 것.",
    "F-01": "권리 제한 '{q}' 에 제한 사유·기간 상한과 이의신청·구제절차를 명시할 것.",
    "F-02": "'{q}' 의 면책 범위에서 고의·중과실을 제외하고 면책 사유를 한정 열거할 것.",
    "G-01": "단서 '{q}' 를 별도 항으로 분리하고 예외 적용 요건을 구체화할 것.",
    "G-02": "'{q}' 인허가에 처리 기한과 간주 규정을 신설할 것.",
    "G-03": "'{q}' 감독 권한에 감독 범위·주기·방법 기준과 결과 공시 의무를 법정화할 것.",
    "G-04": "내부통제 요소('{q}' 등) 중 누락된 통제활동·모니터링 요소를 보완할 것.",
    "G-05": "'{q}' 보고 의무에 주기·양식·제출처를 구체적으로 법정화할 것.",
    "E-01": "'{q}' 의 복합 요건을 핵심 요건과 부차 요건으로 분리하고 부차 요건은 시행령에 위임할 것.",
    "L-01": "다수 타법 인용('{q}' 등)을 직접 규정으로 전환하거나 별표로 분리할 것.",
    "L-02": "'{q}' 참조의 정합성을 확인하고 인용 방식을 통일할 것.",
    "L-03": "'{q}' 인용 대상 조문의 현행 존재 여부를 확인하고 갱신할 것.",
    "E-05": "의무 조항('{q}')에 대응하는 벌칙·과태료·행정처분 제재 조항을 신설할 것.",
}
# verbatim 추출 실패 시 generic fallback (한계 측정용 — 처방이 여전히 generic)
_FALLBACK = {
    "S-04": "각 호 나열을 유형 분류 후 별표 이관 또는 조문 분리할 것.",
    "G-04": "내부통제 5요소(통제환경·위험평가·통제활동·정보소통·모니터링) 중 누락 요소를 보완할 것.",
}


def make_mechanical(article, finding) -> tuple[str, str | None, str]:
    """기계적 조문맞춤 권고 합성.

    반환: (recommendation_text, verbatim_clause, extract_method)
    """
    pid = finding.pattern_id
    verbatim, method = extract_verbatim(article, pid)
    art_no = article.number or ""

    if verbatim:
        body = _PRESCRIPTION.get(pid, "해당 조문의 결함 부분을 개정할 것.")
        body = body.format(q=verbatim)
        rec = f"{art_no} 본문 「{verbatim}」 — {body}"
        return rec, verbatim, method

    # verbatim 실패 → generic fallback (조문번호만, 인용 없음)
    fb = _FALLBACK.get(pid) or _PRESCRIPTION.get(pid, "해당 조문의 결함 부분을 개정할 것.")
    fb = fb.replace("'{q}'", "해당 부분").replace("('{q}' 등)", "").format(q="해당 부분") \
        if "{q}" in fb else fb
    rec = f"{art_no} — {fb}"
    return rec, None, "none"


# ════════════════════════════════════════════════════════════════════════
#  (C) 강화 채점기 — verbatim(본문 실제 인용)이 있을 때만 구체 점수
# ════════════════════════════════════════════════════════════════════════
def _normalize_for_match(s: str) -> str:
    """공백·백슬래시 제거 후 비교용 정규화 (verbatim 포함 판정)."""
    return re.sub(r"\s+", "", (s or "").replace("\\", ""))


# 최소 verbatim 길이 (이보다 짧은 키워드 인용은 '구체'로 안 봄 — 게이밍 방지)
_MIN_VERBATIM_LEN = 6


def score_specificity_strong(rec_text: str, article) -> tuple[int, str]:
    """강화 구체 채점 0/1/2.

    핵심 변경: '제N조' 존재나 내부태그 인용은 점수를 주지 않는다.
    오직 **권고에 담긴 인용 구절이 조문 본문(full_text)의 verbatim 부분문자열**일 때만
    구체 점수를 준다.

      +1 : 조문 본문 verbatim 절(>= _MIN_VERBATIM_LEN 자)이 권고에 포함됨.
      +1 : 그 verbatim 절이 충분히 길거나(>=15자) 다어절(공백 포함)이라 '문장 처방' 수준.

    반환: (점수0~2, 판정사유)
    """
    t = (rec_text or "").strip()
    if not t:
        return 0, "empty"
    body_norm = _normalize_for_match(article.full_text)
    if not body_norm:
        return 0, "no_body"

    # 권고에서 「...」 인용부 추출 (생성기가 넣은 verbatim 후보)
    quotes = re.findall(r"「([^」]+)」", t)
    # 「」가 없더라도 본문 verbatim 부분문자열이 들어있는지 탐색 (게이밍 무관 검증)
    best = ""
    for q in quotes:
        qn = _normalize_for_match(q)
        if len(qn) >= _MIN_VERBATIM_LEN and qn in body_norm:
            if len(qn) > len(_normalize_for_match(best)):
                best = q

    # 「」 인용이 본문에 없으면, 권고 전체에서 본문과 일치하는 최장 연속 구간을 탐색
    if not best:
        rec_norm = _normalize_for_match(t)
        # 슬라이딩으로 본문에 존재하는 최장 부분문자열 근사 (윈도우 기반, 비용 제한)
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
        # verbatim 근거 없음 — 조문번호/태그만 있어도 0점 (강화 핵심)
        return 0, "no_verbatim_quote"

    bn = _normalize_for_match(best)
    pts = 1
    # '문장 처방' 수준: 길거나(>=15자) 어절 2개 이상
    if len(bn) >= 15 or (" " in best.strip()):
        pts += 1
    return min(2, pts), f"verbatim:{best[:30]}"


def score_actionability(rec_text: str) -> int:
    return base.score_actionability(rec_text)


# ════════════════════════════════════════════════════════════════════════
#  (D) 메인 — baseline vs mechanical, 강화 채점기로 비교
# ════════════════════════════════════════════════════════════════════════
def main() -> int:
    fid_map = json.loads(base.FID_MAP_PATH.read_text(encoding="utf-8"))

    # 1) TP 행 수집 (baseline 동일)
    tp_rows = []
    with base.VERDICTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("verdict") != "TP":
                continue
            fid = d.get("fid")
            if not fid or "@" not in fid:
                continue
            _, law_name = fid.split("@", 1)
            tp_rows.append({
                "fid": fid, "rule_id": d["rule_id"], "law_name": law_name,
                "evidence": d.get("evidence", ""), "article": fid_map.get(fid),
            })

    total_tp = len(tp_rows)

    # 2) 표본 (baseline 동일: rule_id 별 고르게, 동일 seed)
    import random
    rng = random.Random(base.RANDOM_SEED)
    by_rule = defaultdict(list)
    for r in tp_rows:
        by_rule[r["rule_id"]].append(r)
    sample = []
    for rule_id in sorted(by_rule):
        rows = by_rule[rule_id][:]
        rng.shuffle(rows)
        sample.extend(rows[:base.SAMPLE_PER_RULE])
    sample.sort(key=lambda r: (r["rule_id"], r["law_name"]))

    # 3) 법령별 엔진 1회 (baseline 동일 파이프라인)
    by_law = defaultdict(list)
    for r in sample:
        by_law[r["law_name"]].append(r)

    records = []
    skipped = {"missing_law": 0, "fn_not_fired": 0, "unmapped": 0}

    for law_name, rows in by_law.items():
        md = base.LAWS_DIR / law_name / "법률.md"
        if not md.exists():
            for r in rows:
                skipped["missing_law"] += 1
                records.append({**r, "status": "missing_law"})
            continue
        text = base._strip_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        law = parse_law(text, name=law_name, law_category=base._categorize(law_name))
        findings = run_all(law)
        findings = fpc.correct(law, findings)
        result = scorer.compute(law, findings)
        result = recommender.apply(result)  # Layer1 부착

        art_by_norm = {base._normalize_article(a.number): a for a in law.articles}
        idx = {}
        for fobj in result.findings:
            idx[(fobj.pattern_id, base._normalize_article(fobj.article_number))] = fobj

        for r in rows:
            art = r["article"]
            if not art:
                skipped["unmapped"] += 1
                records.append({**r, "status": "unmapped"})
                continue
            fobj = idx.get((r["rule_id"], base._normalize_article(art)))
            if fobj is None:
                skipped["fn_not_fired"] += 1
                records.append({**r, "status": "fn_not_fired"})
                continue
            article = art_by_norm.get(base._normalize_article(art))
            if article is None:
                skipped["fn_not_fired"] += 1
                records.append({**r, "status": "fn_not_fired"})
                continue

            rec = fobj.recommendation or {}
            baseline_text = rec.get("template") or ""

            # --- baseline 을 강화 채점기로 채점 ---
            b_acc = base.score_accuracy(fobj, baseline_text)
            b_spec, b_reason = score_specificity_strong(baseline_text, article)
            b_actn = score_actionability(baseline_text)

            # --- 기계적 조문맞춤 권고 생성 + 강화 채점 ---
            mech_text, verbatim, method = make_mechanical(article, fobj)
            m_acc = base.score_accuracy(fobj, mech_text)
            m_spec, m_reason = score_specificity_strong(mech_text, article)
            m_actn = score_actionability(mech_text)

            records.append({
                **r,
                "status": "scored",
                "severity": fobj.severity,
                "pattern_id": fobj.pattern_id,
                "internal_matched_text": fobj.matched_text,
                "verbatim_extracted": verbatim,
                "extract_method": method,
                "extract_grade": _EXTRACT_GRADE.get(fobj.pattern_id, "keyword"),
                "baseline_recommendation": baseline_text,
                "mechanical_recommendation": mech_text,
                "baseline": {"accuracy": b_acc, "specificity": b_spec,
                             "actionability": b_actn, "spec_reason": b_reason},
                "mechanical": {"accuracy": m_acc, "specificity": m_spec,
                               "actionability": m_actn, "spec_reason": m_reason},
            })

    scored = [x for x in records if x["status"] == "scored"]
    n = len(scored)

    def axis_summary(variant: str):
        if not n:
            return None
        spec_dist = {i: 0 for i in range(3)}
        actn_dist = {i: 0 for i in range(3)}
        acc_dist = {i: 0 for i in range(2)}
        for x in scored:
            v = x[variant]
            spec_dist[v["specificity"]] += 1
            actn_dist[v["actionability"]] += 1
            acc_dist[v["accuracy"]] += 1
        return {
            "accuracy": {"dist": acc_dist,
                         "mean": round(sum(x[variant]["accuracy"] for x in scored) / n, 3)},
            "specificity": {
                "dist": spec_dist,
                "mean": round(sum(x[variant]["specificity"] for x in scored) / n, 3),
                "pct_specific_ge1": round(
                    sum(1 for x in scored if x[variant]["specificity"] >= 1) / n, 3),
            },
            "actionability": {
                "dist": actn_dist,
                "mean": round(sum(x[variant]["actionability"] for x in scored) / n, 3)},
        }

    baseline_ax = axis_summary("baseline")
    mech_ax = axis_summary("mechanical")

    deltas = None
    if n:
        deltas = {
            "specificity_mean": round(mech_ax["specificity"]["mean"]
                                      - baseline_ax["specificity"]["mean"], 3),
            "specificity_pct_ge1": round(mech_ax["specificity"]["pct_specific_ge1"]
                                         - baseline_ax["specificity"]["pct_specific_ge1"], 3),
            "actionability_mean": round(mech_ax["actionability"]["mean"]
                                        - baseline_ax["actionability"]["mean"], 3),
        }

    # verbatim 추출 성공률 (등급별)
    extract_stats = defaultdict(lambda: {"n": 0, "extracted": 0})
    for x in scored:
        g = x["extract_grade"]
        extract_stats[g]["n"] += 1
        if x["verbatim_extracted"]:
            extract_stats[g]["extracted"] += 1
    extract_summary = {g: {"n": s["n"], "extracted": s["extracted"],
                           "rate": round(s["extracted"] / s["n"], 2) if s["n"] else None}
                       for g, s in extract_stats.items()}

    def per_rule_spec():
        by = defaultdict(list)
        for x in scored:
            by[x["rule_id"]].append(x)
        out = {}
        for rid, xs in sorted(by.items()):
            k = len(xs)
            out[rid] = {
                "n": k,
                "baseline_spec": round(sum(x["baseline"]["specificity"] for x in xs) / k, 2),
                "mech_spec": round(sum(x["mechanical"]["specificity"] for x in xs) / k, 2),
                "verbatim_rate": round(sum(1 for x in xs if x["verbatim_extracted"]) / k, 2),
            }
        return out

    summary = {
        "total_tp_rows": total_tp,
        "sample_size": len(sample),
        "scored": n,
        "skipped": skipped,
        "baseline_axes": baseline_ax,
        "mechanical_axes": mech_ax,
        "deltas": deltas,
        "verbatim_extraction_by_grade": extract_summary,
        "per_rule": per_rule_spec(),
    }

    report = {
        "_meta": {
            "purpose": "기계적 조문맞춤 권고 프로토타입 — verbatim 추출 + 구조적 처방 합성 (LLM 0회)",
            "pipeline": "run_all -> fpc.correct -> scorer.compute -> recommender.apply (baseline 동일)",
            "llm": False,
            "llm_calls": 0,
            "external_api_calls": 0,
            "sample_per_rule": base.SAMPLE_PER_RULE,
            "seed": base.RANDOM_SEED,
            "scoring_change": (
                "강화 구체 채점: '제N조' 존재·내부태그 인용은 0점. "
                "권고의 인용이 조문 full_text 의 verbatim 부분문자열(>=6자)일 때만 +1, "
                "길거나 다어절이면 +1 (최대 2). baseline 도 동일 강화기로 재채점."
            ),
            "anti_gaming": (
                "직전 시도(조문번호 주입)는 _ARTICLE_REF_RX 게이밍이었음. 본 강화기는 조문번호·"
                "내부태그를 무시하고 본문 verbatim 일치만 인정 → 게이밍 차단."
            ),
        },
        "summary": summary,
        "records": records,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout
    print(f"\nTP 전체: {total_tp}  표본: {len(sample)}  채점됨: {n}")
    print(f"스킵: {skipped}")
    print(f"LLM 호출: 0   외부 API 호출: 0")
    if n:
        b, m = baseline_ax, mech_ax
        print("\n[3축 비교 — baseline Layer1 vs 기계적 조문맞춤 / 강화 채점기 동일 적용]")
        print(f"  {'축':<16}{'baseline':>14}{'mechanical':>14}")
        print(f"  {'정확(0/1) mean':<14}{b['accuracy']['mean']:>14}{m['accuracy']['mean']:>14}")
        print(f"  {'구체(0/2) mean':<14}{b['specificity']['mean']:>14}{m['specificity']['mean']:>14}")
        print(f"  {'구체율(>=1)':<16}{b['specificity']['pct_specific_ge1']:>14}"
              f"{m['specificity']['pct_specific_ge1']:>14}")
        print(f"  {'실행(0/2) mean':<14}{b['actionability']['mean']:>14}{m['actionability']['mean']:>14}")
        print(f"\n  구체 분포  baseline={b['specificity']['dist']}  mechanical={m['specificity']['dist']}")
        print(f"\n[델타]  구체mean {deltas['specificity_mean']:+}  "
              f"구체율 {deltas['specificity_pct_ge1']:+}  실행 {deltas['actionability_mean']:+}")
        print(f"\n[verbatim 추출 성공률 / 등급별]")
        for g, s in sorted(extract_summary.items()):
            print(f"  {g:<8} n={s['n']:>2}  추출={s['extracted']:>2}  성공률={s['rate']}")

        # 예시 3건: verbatim 이 실제 조문 문구인지 눈으로 보이게
        print("\n[예시 3건 — verbatim 인용이 실제 조문 본문 문구인가]")
        shown = 0
        for x in scored:
            if not x["verbatim_extracted"]:
                continue
            print(f"  · {x['fid']} ({x['article']}, {x['pattern_id']}/{x['severity']}, "
                  f"grade={x['extract_grade']})")
            print(f"    내부태그(무의미): {x['internal_matched_text']!r}")
            print(f"    verbatim 추출  : 「{x['verbatim_extracted']}」")
            print(f"    baseline  구체={x['baseline']['specificity']}: {x['baseline_recommendation'][:65]}")
            print(f"    mechanical 구체={x['mechanical']['specificity']}: {x['mechanical_recommendation'][:110]}")
            shown += 1
            if shown >= 3:
                break
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
