#!/usr/bin/env python3
"""fn 보강용 신규 라벨링 작업 패키지 생성 — E-03 착수분 (LLM/외부 API 0회).

팀장 결정: 'fn 보강을 위한 신규 라벨링 착수'.
라벨 자체는 사람(자문위원/검수자) 판정이라 세션이 찍지 않는다. 세션은 **라벨러가 TP/FP만
표시하면 게이트①(precision 비악화)을 검증할 수 있는 작업지(worksheet)** 를 만든다.

대상(착수): E-03(정밀도 0.5, 신호 명확). fn 원인 = FP필터 `_INTERNAL_WRITTEN`(서면 조사·
보고)이 자문위원이 TP로 본 '서면 강제(전자문서 병기 대상)'까지 억제. 그래서:
  · 코퍼스 전수에서 'E-03 _STRONG 매칭 AND _INTERNAL_WRITTEN 억제'인 조문을 후보로 모은다.
  · 각 후보에 verbatim 서면절 + 맥락 + (참고용) citizen-facing 신호 + 생성될 처방을 붙인다.
  · 라벨란(label)은 공란 → 라벨러가 TP/FP 표시. gold fn 2건은 known-TP 시드로 표시.

산출: outputs/fn_label_task_e03.jsonl (라벨러 작업지) + stdout 요약.
이후 흐름: 라벨 완료 → recall(시드 발화) + precision(억제해제 후 FP율) 동시 측정 → 게이트①.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine.parser import parse_law  # noqa: E402
from engine.rules import e03_analog as e3  # noqa: E402
import scripts.mechanical_reco as mr  # noqa: E402

LAWS_DIR = REPO / "data" / "laws" / "raw"
OUT_PATH = REPO / "outputs" / "fn_label_task_e03.jsonl"

# gold fn 시드 (자문위원이 TP로 본 미발화 — known positive).
_GOLD_FN_SEED = {
    ("관세법", "제266조"),
    ("독점규제및공정거래에관한법률", "제87조"),
}


def _strip_frontmatter(text: str) -> str:
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def main() -> int:
    rows = []
    n_law = 0
    for law_dir in sorted(LAWS_DIR.iterdir()):
        md = law_dir / "법률.md"
        if not md.exists():
            continue
        n_law += 1
        try:
            law = parse_law(_strip_frontmatter(md.read_text(encoding="utf-8", errors="replace")),
                            name=law_dir.name)
        except Exception:
            continue
        for art in law.articles:
            if art.is_purpose() or art.is_definition():
                continue
            text = art.full_text or ""
            if not e3._STRONG.search(text):
                continue
            # 다른 정당한 FP필터에 걸리면 라벨 후보에서 제외(이건 진짜 FP 가능성↑) —
            # 오직 _INTERNAL_WRITTEN 단독 억제분만 '판정 보류 후보'로 올린다.
            if e3._LEGAL_PROC.search(text) or e3._DOC_MGMT.search(text) \
                    or e3._CORP_DOC.search(text) or e3._REGISTRY_DOC.search(text):
                continue
            if not e3._INTERNAL_WRITTEN.search(text):
                continue  # 억제 안 됨 = 이미 발화 → 라벨 불요
            verbatim, method = mr.extract_verbatim(art, "E-03")
            citizen = bool(e3._CITIZEN_FACING.search(text))
            seed = (law_dir.name, art.number) in _GOLD_FN_SEED
            rows.append({
                "rule_id": "E-03",
                "law": law_dir.name,
                "article": art.number,
                "title": art.title,
                "verbatim_서면절": verbatim,
                "suppressed_by": "_INTERNAL_WRITTEN",
                "hint_citizen_facing": citizen,   # 참고 신호(라벨 아님)
                "gold_fn_seed": seed,             # True=자문위원 known-TP
                "would_generate": (mr.make_mechanical(art, type("F", (), {"pattern_id": "E-03",
                                   "matched_text": None})())[0] if verbatim else None),
                "label": "TP" if seed else "",    # 라벨러가 채움(TP/FP)
            })

    OUT_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                        encoding="utf-8")

    seeds = [r for r in rows if r["gold_fn_seed"]]
    citizen_n = sum(1 for r in rows if r["hint_citizen_facing"])
    print(f"\n[fn 라벨링 작업지 — E-03 착수]")
    print(f"  스캔 법령: {n_law}   라벨 후보(_INTERNAL_WRITTEN 단독 억제): {len(rows)}")
    print(f"  gold fn 시드(known-TP, 라벨 선기입): {len(seeds)}")
    print(f"  참고: citizen-facing 신호 있는 후보 {citizen_n}건 (TP 우선검토 후보)")
    print(f"\n  라벨러 할 일: 각 행 label 에 TP/FP 표시. (서면 강제가 국민·사업자 대상이면 TP=전자문서 "
          f"병기대상 / 내부 보고·심의면 FP)")
    print(f"  시드 예시:")
    for r in seeds:
        print(f"    · {r['law']} {r['article']} 「{r['verbatim_서면절']}」 (citizen={r['hint_citizen_facing']})")
    print(f"\n  다음: 라벨 완료 후 → recall(시드 발화) + precision(_INTERNAL_WRITTEN 정밀화 후 FP율) "
          f"동시 측정으로 게이트① 검증.")
    print(f"\nWrote {OUT_PATH}  ({len(rows)} 후보)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
