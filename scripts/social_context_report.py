"""라운드3 — SSI 실데이터 end-to-end 실행 + 사회적 맥락 리포트.

회의록 §4 + 감사인 4조건. 실제 NaverSearch 결과(호출측 주입)로 SSI 산출.
국민 체감이 큰 생활밀착 법령 샘플에 대해 '사회적 맥락' 절을 생성.

이 스크립트는 검색 결과를 outputs/social_context/raw_searches.json 에서 읽는다
(MCP 호출은 세션에서 수행해 그 파일로 저장 — 호출/원자료 보존, 감사 조건3).
검색 파일이 없으면 reach-only 폴백으로 동작(LLM·외부호출 0).
"""
from __future__ import annotations

import json
from pathlib import Path

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

from engine.parser import parse_law
from engine.rules import run_all
from engine.social import compute_ssi

RAW = Path("outputs/social_context/raw_searches.json")
OUT = Path("outputs/social_context/report.json")

# 국민 생활밀착·체감 큰 법령 샘플 (정비 우선순위 시연용)
SAMPLE_LAWS = [
    "가맹사업거래의공정화에관한법률",
    "119구조ㆍ구급에관한법률",
]


def load_law(name):
    md = Path(f"data/laws/raw/{name}/법률.md")
    if not md.exists():
        return None
    text = md.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    try:
        return parse_law(text, name=name)
    except Exception:
        return None


def main():
    searches = {}
    if RAW.exists():
        searches = json.loads(RAW.read_text(encoding="utf-8"))
        print(f"실검색 결과 로드: {len(searches)}개 쿼리키")
    else:
        print("실검색 파일 없음 — reach-only 폴백(LLM·외부호출 0)")

    def search_fn_for(key):
        def fn(query):
            return searches.get(key, [])
        return fn

    report = {"laws": [], "protocol": "SSI 실데이터 end-to-end, 점수 비곱셈(F1 불변), "
              "감사 4조건(라벨미유입·출처보존·기간고정·수렴검증)"}

    for name in SAMPLE_LAWS:
        law = load_law(name)
        if law is None:
            continue
        findings = run_all(law)
        fnd_by_art = {}
        for f in findings:
            fnd_by_art.setdefault(f.article_number.replace(" ", ""), []).append(f)

        law_entry = {"law": name, "articles": []}
        # 결함이 탐지된 조문에 한해 SSI 부여(우선순위 정렬) — 결함 없는 곳은 생략
        for art in law.articles:
            an = art.number.replace(" ", "")
            arts_findings = fnd_by_art.get(an, [])
            if not arts_findings:
                continue
            key = f"{name}::{an}"
            ssi = compute_ssi(art.number, art.full_text, title=art.title,
                              search_fn=search_fn_for(key), period="2026-05~06")
            law_entry["articles"].append({
                "article": art.number,
                "title": art.title or "",
                "defects": [f"{f.pattern_id}/{f.severity}" for f in arts_findings],
                "topic_terms": ssi.topic_terms,
                "ssi": round(ssi.ssi, 3),
                "salience_hits": ssi.hit_count,
                "valence": round(ssi.valence, 3),
                "reach_citizen": ssi.reach_citizen,
                "social_context": ssi.note,
                "sources": ssi.sources[:3],
            })
        # 정비 우선순위 = 법리결함 × 사회현저성(정렬용, 점수 곱셈 아님 — 결함점수 불변)
        law_entry["articles"].sort(key=lambda a: -a["ssi"])
        report["laws"].append(law_entry)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 콘솔 요약
    for le in report["laws"]:
        print(f"\n## {le['law']} — 결함조문 {len(le['articles'])}건 (SSI 우선순위 정렬)")
        for a in le["articles"][:5]:
            print(f"  [{a['ssi']:.2f}] {a['article']} {a['title']} "
                  f"| 결함 {','.join(a['defects'])} | 거론 {a['salience_hits']} "
                  f"valence {a['valence']:+.2f} | 주제 {a['topic_terms'][:3]}")
    print(f"\n(산출물 {OUT})")


if __name__ == "__main__":
    main()
