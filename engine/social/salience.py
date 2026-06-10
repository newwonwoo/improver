"""사회 현저성 지수(SSI) — 사회 보편 인식의 우선순위 신호화.

설계 원칙(회의 합의 + 감사인 4조건):
1. SSI 는 라벨·학습·F1 에 유입 금지 — 정비 *우선순위 정렬* 과 리포트 '사회적 맥락' 전용.
2. 점수에 곱하지 않는다(메트릭 게이밍 방지). 결함 점수는 법리 그대로.
3. 사전(lexicon)·집계식은 공개·재현 가능. 출처/쿼리/원자료는 호출측이 보존.
4. valence 는 사전 기반(LLM 0회). 불편/부담/과도(정비요구↑) vs 보호/안전/강화(정비요구↓).

세 축(사회학자 교수 조작화):
  salience : 공론장 현저성  = log1p(거론 빈도)
  valence  : 체감 방향      = (정비요구 - 보호요구) / 총
  reach    : 수범자 범위    = citizen_facing(국민·사업자 대면) 가중
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ── 주제어 추출: 법령 조문에서 사회 검색에 쓸 핵심 명사구 후보 ──
# 기계 생성(체리피킹 금지): 행정 상투어·조사·접속어 제거 후 2~6자 한글 토큰.
_STOP = {
    "이하", "이상", "경우", "다음", "각호", "해당", "관련", "대통령령", "행정안전부령",
    "총리령", "부령", "조례", "규칙", "법률", "이법", "이영", "제외", "포함", "기준",
    "사항", "여야", "수있다", "한다", "하여야", "위하여", "관하여", "대하여", "따라",
    "또는", "그리고", "다만", "각각", "모든", "기타", "등을", "등의", "등에", "등은",
}
_TOKEN = re.compile(r"[가-힣]{2,6}")

# ── valence 사전 (정비요구 방향 = 사회가 '고쳐달라'는 쪽) ──
_DEMAND_REFORM = (
    "불편", "불합리", "과도", "부담", "복잡", "지연", "번거", "낡은", "구시대",
    "이중규제", "중복규제", "과잉규제", "애로", "걸림돌", "규제완화", "간소화",
    "철폐", "개선요구", "민원", "불만", "차별", "형평", "역차별",
)
_DEMAND_PROTECT = (
    "보호", "안전", "강화필요", "피해", "사각지대", "취약계층", "권익", "구제",
    "방지", "예방", "엄격", "규제강화", "처벌강화",
)


def extract_topic_terms(text: str, *, title: str | None = None, top_k: int = 5) -> list[str]:
    """조문 텍스트 → 사회 검색용 주제어(빈도 상위, 행정 상투어 제거)."""
    freq: dict[str, int] = {}
    src = (title or "") + " " + (text or "")
    for tok in _TOKEN.findall(src):
        if tok in _STOP or tok.endswith(("하여", "에게", "으로", "에서")):
            continue
        freq[tok] = freq.get(tok, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [t for t, _ in ranked[:top_k]]


def score_valence(snippets: list[str]) -> tuple[float, int, int]:
    """검색 스니펫 모음 → valence in [-1,1].

    +1: 사회가 '정비(완화·간소화)' 요구가 강함. -1: '보호·강화' 요구가 강함.
    반환: (valence, demand_reform_hits, demand_protect_hits)
    """
    blob = " ".join(snippets)
    d = sum(blob.count(w) for w in _DEMAND_REFORM)
    p = sum(blob.count(w) for w in _DEMAND_PROTECT)
    total = d + p
    if total == 0:
        return 0.0, 0, 0
    return (d - p) / total, d, p


@dataclass
class SocialSalience:
    """조문 1건의 사회 현저성 산출 결과 (리포트·정렬 전용)."""

    article_number: str
    topic_terms: list[str]
    hit_count: int = 0
    salience: float = 0.0           # log1p(hit_count) — 절대 현저성
    valence: float = 0.0            # [-1,1] 정비요구 방향
    reach_citizen: bool = False     # 국민·사업자 대면 여부
    ssi: float = 0.0                # 정규화 우선순위 점수 [0,1]
    note: str = ""
    sources: list[dict] = field(default_factory=list)


_CITIZEN_FACING = re.compile(
    r"(신청|신고|제출|청구|요청|등록|발급|교부|이의신청|실태\s*조사|과태료|처분|허가|면허)"
)


def compute_ssi(
    article_number: str,
    text: str,
    *,
    title: str | None = None,
    search_fn=None,
    period: str = "",
    top_k: int = 5,
) -> SocialSalience:
    """조문 → SSI. search_fn(query)->list[{'title','desc',...}] 주입(없으면 빈 결과).

    F1 에 영향 0: 이 함수는 findings 를 만들지 않는다. 우선순위·맥락만 산출.
    """
    terms = extract_topic_terms(text, title=title, top_k=top_k)
    reach = bool(_CITIZEN_FACING.search(text))
    res = SocialSalience(article_number=article_number, topic_terms=terms,
                         reach_citizen=reach)
    if not search_fn or not terms:
        res.note = "검색 미수행(주제어/검색기 부재) — reach 만 산정"
        res.ssi = 0.15 if reach else 0.0
        return res

    snippets: list[str] = []
    seen = set()
    query = " ".join(terms[:3]) + " 규제 OR 불편 OR 개선"
    try:
        items = search_fn(query) or []
    except Exception as e:  # 검색 실패는 치명 아님 — reach 로 폴백
        res.note = f"검색 실패({type(e).__name__}) — reach 폴백"
        res.ssi = 0.15 if reach else 0.0
        return res

    for it in items:
        url = it.get("url") or it.get("originallink") or it.get("link") or ""
        if url in seen:
            continue
        seen.add(url)
        snippets.append((it.get("title", "") + " " + it.get("desc", "")
                         + " " + it.get("description", "")))
        res.sources.append({"title": it.get("title", "")[:120], "url": url})

    res.hit_count = len(snippets)
    res.salience = math.log1p(res.hit_count)
    res.valence, dref, dpro = score_valence(snippets)
    res.note = (f"기간={period or 'NA'} 거론{res.hit_count}건 "
                f"정비요구{dref}/보호요구{dpro} reach={'국민대면' if reach else '내부'}")
    # SSI: 현저성(주) + 정비요구 방향(가산) + reach(가산), [0,1] 클립.
    # 점수 곱셈 아님 — 정렬·표시용 합성 지표.
    raw = 0.6 * (res.salience / math.log1p(10)) \
        + 0.25 * max(res.valence, 0.0) \
        + 0.15 * (1.0 if reach else 0.0)
    res.ssi = max(0.0, min(1.0, raw))
    return res
