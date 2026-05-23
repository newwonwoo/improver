#!/usr/bin/env python3
"""BORDER verdict 해결 익스포터 — 신경망 강화를 위한 라벨 증강.

verification_dataset.jsonl 의 BORDER 판정(267건)을 Claude.ai 웹에서 TP/FP 로
확정하기 위한 prompt 를 생성한다. 각 BORDER 조문에 **수집 사례에서 추출한
카테고리별 전문가 FP 필터 기준**을 첨부하여 라벨 정확도를 높인다.

배경:
  - 현재 verdict: TP 372 / FP 1755 / BORDER 267 (12개 룰)
  - BORDER 267건 전부 corpus 법령 조문에 매핑됨 (도메인 불일치 없음)
  - 해결 시 +267 clean label → NN 재학습 (TP 대비 +72%)

워크플로:
  1. python scripts/border_resolution_export.py            # prompt 생성
  2. outputs/border_resolution/<rule>.md 를 Claude.ai 웹에 붙여넣기
  3. 응답 JSON 을 outputs/rule_verification_responses/ 에 저장
  4. python scripts/import_rule_verification.py             # verdict 갱신
  5. SLM/torch 재학습 → F1 측정

응답 포맷 (import_rule_verification.py 호환):
  {"bundle_id":"border_<rule>", "rule_id":"<rule>",
   "verdicts":[{"fid":"...", "v":"TP|FP"}]}
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.parser import parse_law  # noqa: E402

_DATASET = Path("outputs/verification_dataset.jsonl")
_FID_MAP = Path("outputs/fid_article_map.json")
_LAWS_DIR = Path("data/laws/raw")
_OUT_DIR = Path("outputs/border_resolution")
_BODY_MAX = 1000

# 룰 → 카테고리
RULE_CAT = {
    "S-01": "구조", "S-02": "구조", "S-03": "구조", "S-04": "구조",
    "F-01": "공정성", "F-02": "공정성", "F-03": "공정성", "F-04": "공정성", "F-05": "공정성",
    "L-01": "적법성", "L-02": "적법성", "L-03": "적법성",
    "G-01": "거버넌스", "G-02": "거버넌스", "G-03": "거버넌스", "G-04": "거버넌스", "G-05": "거버넌스",
    "E-01": "효율성", "E-02": "효율성", "E-03": "효율성", "E-04": "효율성", "E-05": "효율성",
}

# 수집 사례(감사원·공정위·금감원·권익위·인권위·대법원)에서 추출한
# 룰별 TP 신호 / FP 필터 — 라벨링 정확도를 높이는 전문가 기준
RULE_CRITERIA: dict[str, dict[str, list[str]]] = {
    "S-04": {
        "tp": [
            "한 항에 호가 과도하게 많아 가독성·예측가능성을 해침 (대체로 15호 이상)",
            "호 안에 다시 목·세목이 다단으로 중첩 (3단계 이상)",
            "캐치올('그 밖에 ~') 호가 구체적 기준 없이 광범위",
        ],
        "fp": [
            "단순 정의·용어 나열 (열거가 본질적으로 필요한 정의 조문)",
            "기술적·세부 항목 나열이 불가피한 별표·서식 성격",
            "각 호가 명확히 구분되고 예측 가능 (권익위 예측가능성 기준 충족)",
        ],
    },
    "E-01": {
        "tp": [
            "조건·단서가 다단 중첩되어 적용 단계가 불명확 (대법 재량 일탈 위험)",
            "'~경우로서 ~때에는 ~경우에 한하여' 식 조건 연쇄",
            "내부 참조(제N항·제N호)가 얽혀 절차 추적 곤란",
        ],
        "fp": [
            "조건이 많아도 각 단계가 명확히 구분되고 절차 명확화 목적",
            "예외·단서가 정당한 사유(천재지변·불가항력)를 명시",
            "절차 분기가 업무 특성상 불가피",
        ],
    },
    "G-01": {
        "tp": [
            "한 항에 단서('다만')가 2개 이상 중첩되어 원칙이 형해화",
            "단서가 행정청 재량을 광범위하게 확대 (권익위 재량남용 기준)",
            "예외 사유가 불명확('필요한 경우' 등)",
        ],
        "fp": [
            "단서가 가중·감경 사유를 명확히 규정 (대법 JUD-01 — 비례성 확보로 오히려 정상)",
            "단서가 1개이고 정당한 예외 (천재지변·긴급)",
            "단서 없이는 과잉규제가 되는 합리적 완화",
        ],
    },
    "G-03": {
        "tp": [
            "감독 조항에 범위·주기·방법·공개·시정권 5요소 중 다수 누락",
            "감독 결과 공개 의무 부재 (권익위 COR-02)",
            "감독이 사실상 자의적 (기준 없는 점검)",
        ],
        "fp": [
            "감독 5요소가 같은 조 또는 인접 조문에 규정",
            "타 법령(행정조사기본법 등)에서 절차 보장",
            "자문·권고 성격으로 침익적 감독 아님",
        ],
    },
    "G-04": {
        "tp": [
            "위원회·기관 설립에 이해충돌 방지·제척·기피 규정 부재 (감사원 BAI-07)",
            "1인 결정 체계 (합의·심의 없음, 권익위 ACRC-06)",
            "내부통제 장치 부재",
        ],
        "fp": [
            "이해충돌방지법·공직자윤리법이 이미 적용",
            "자문기구(의결권 없음)라 통제 필요성 낮음",
            "제척·기피가 인접 조문 또는 시행령에 규정",
        ],
    },
    "F-02": {
        "tp": [
            "사업자·기관의 책임을 부당하게 면제 (공정위 약관규제법 §7)",
            "고의·중과실 포함 광범위 면책",
        ],
        "fp": [
            "천재지변·불가항력·고객 귀책·제3자 귀책 면책 (정당)",
            "법령상 책임 한계를 확인하는 선언적 조항",
        ],
    },
    "F-03": {
        "tp": [
            "침익적 처분에 청문·의견제출 절차 부재 (감사원 BAI-03·행정절차법 §22)",
            "처분 기준 불명확 ('필요하다고 인정' 등)",
            "1:1 자동 최고제재, 가중·감경 없음 (대법 JUD-01)",
        ],
        "fp": [
            "청문 절차가 같은 법 다른 조문에 규정",
            "처분 기준이 시행령에 위임되어 구체화",
            "긴급 공익상 즉시 처분이 정당화",
        ],
    },
    "F-04": {
        "tp": [
            "일정 기간 무응답을 동의·승인으로 의제 (공정위 약관규제법 §12)",
            "의제로 국민 권리가 제한",
        ],
        "fp": [
            "인허가 의제가 절차 간소화 목적이고 사전 고지 충분",
            "의제 효과가 수익적 (국민에 유리)",
        ],
    },
    "L-01": {
        "tp": [
            "한 조문에 타 법령 인용이 과도(5건 이상)해 의존성 과다",
            "인용이 끊긴 참조(존재하지 않는 조문)",
        ],
        "fp": [
            "인용이 명확하고 실재하며 입법 체계상 필요",
            "관계 법령 특례·의제 맥락의 정당한 인용",
        ],
    },
    "L-03": {
        "tp": [
            "참조 대상 조문이 실재하지 않거나 개정으로 사라짐",
            "준용 연쇄가 추적 불가",
        ],
        "fp": [
            "참조가 정확하고 실재",
            "준용이 명확하고 입법 경제상 정당",
        ],
    },
}
# 카테고리 일반 기준 (룰별 기준 없을 때 fallback)
_CAT_FALLBACK = {
    "구조": RULE_CRITERIA["S-04"],
    "효율성": RULE_CRITERIA["E-01"],
    "거버넌스": RULE_CRITERIA["G-01"],
    "공정성": RULE_CRITERIA["F-03"],
    "적법성": RULE_CRITERIA["L-01"],
}


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rstrip() + " …(생략)"


def _load_law_articles(law_name: str):
    md = _LAWS_DIR / law_name / "법률.md"
    if not md.exists():
        return None
    text = md.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    try:
        law = parse_law(text, name=law_name)
    except Exception:
        return None
    return {a.number.replace(" ", ""): a for a in law.articles}


def _criteria_for(rule_id: str) -> dict[str, list[str]]:
    if rule_id in RULE_CRITERIA:
        return RULE_CRITERIA[rule_id]
    return _CAT_FALLBACK.get(RULE_CAT.get(rule_id, ""), {"tp": [], "fp": []})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", type=Path, default=_OUT_DIR)
    p.add_argument("--max-per-rule", type=int, default=40,
                   help="룰당 최대 케이스 수 (prompt 길이 제한)")
    args = p.parse_args(argv)

    rows = [json.loads(l) for l in _DATASET.open(encoding="utf-8")]
    fid_map = json.loads(_FID_MAP.read_text(encoding="utf-8"))

    border = [r for r in rows if r.get("verdict") == "BORDER"]
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for r in border:
        by_rule[r["rule_id"]].append(r)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    law_cache: dict[str, dict | None] = {}
    summary = {}

    for rule_id, cases in sorted(by_rule.items()):
        cat = RULE_CAT.get(rule_id, "?")
        crit = _criteria_for(rule_id)
        bundle_id = f"border_{rule_id}"

        lines = [
            f"# BORDER 판정 확정 — {rule_id} ({cat})",
            "",
            "당신은 한국 법제·규제 분석 전문가입니다 (법제처 입안길잡이·감사원 내부통제·",
            "공정위 약관규제법·권익위 규제개혁·대법원 행정판례에 정통).",
            "",
            f"규정개선 엔진이 아래 조문들을 **{rule_id}({cat})** 룰로 탐지했으나 TP/FP 판단을",
            "보류(BORDER)했습니다. 각 조문을 **TP(실제 결함)** 또는 **FP(정상 입법)** 로 확정하세요.",
            "",
            "## 판정 기준 (실제 감사·시정·판례 사례 기반)",
            "",
            "**TP (실제 결함) 신호:**",
        ]
        for s in crit.get("tp", []):
            lines.append(f"- {s}")
        lines.append("")
        lines.append("**FP (정상 입법) 신호:**")
        for s in crit.get("fp", []):
            lines.append(f"- {s}")
        lines += [
            "",
            "## 출력 (단일 JSON 객체만, 마크다운·설명 금지)",
            "```",
            json.dumps({
                "bundle_id": bundle_id,
                "rule_id": rule_id,
                "verdicts": [{"fid": "<그대로>", "v": "TP|FP"}],
            }, ensure_ascii=False),
            "```",
            "",
            "---",
            "",
        ]

        n_ok = 0
        for r in cases[: args.max_per_rule]:
            fid = r["fid"]
            if "@" not in fid:
                continue
            law_name = fid.split("@", 1)[1]
            an = fid_map.get(fid)
            if not an:
                continue
            if law_name not in law_cache:
                law_cache[law_name] = _load_law_articles(law_name)
            arts = law_cache[law_name]
            if not arts:
                continue
            art = arts.get(an.replace(" ", ""))
            if not art:
                continue
            n_ok += 1
            lines.append(f"### fid: {fid}")
            lines.append(f"- 법령: {law_name} · 조문: {an} · 탐지근거: {r.get('evidence','')}")
            lines.append("")
            lines.append("```")
            lines.append(_clip(art.full_text, _BODY_MAX))
            lines.append("```")
            lines.append("")

        out = args.out_dir / f"{bundle_id}.md"
        out.write_text("\n".join(lines), encoding="utf-8")
        summary[rule_id] = n_ok
        print(f"  {bundle_id}: {n_ok}건 → {out}")

    # 메타 sidecar
    total = sum(summary.values())
    (args.out_dir / "_summary.json").write_text(
        json.dumps({"by_rule": summary, "total": total,
                    "current_tp": sum(1 for r in rows if r["verdict"] == "TP"),
                    "potential_gain_pct": round(100 * total / max(sum(1 for r in rows if r["verdict"] == "TP"), 1), 1)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cur_tp = sum(1 for r in rows if r["verdict"] == "TP")
    print(f"\n총 {total}건 BORDER 케이스 export — 현재 TP {cur_tp}건 대비 +{round(100*total/max(cur_tp,1),1)}% 라벨 증강 잠재력")
    print(f"→ {args.out_dir}/  (Claude.ai 웹에 붙여넣기 → 응답을 import_rule_verification.py 로 반영)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
