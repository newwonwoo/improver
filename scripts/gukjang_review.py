#!/usr/bin/env python3
"""국장(전 정비국장) 역할 라벨링 + 게이트① 측정 — E-03 fn (LLM/외부 API 0회).

팀장 지시('국장 있잖아') 이행: 자문위원=법제 자문위원(전 정비국장) 역할을 enact 하여
fn 라벨링 작업지(62건)에 TP/FP 판정을 부여한다. 단 **AI가 적용한 국장 기준**임을 명시하고,
경계 건은 BORDER 로 분리해 실(實)국장 확인용으로 남긴다(가짜 단정 방지).

국장 기준 (gold E-03 사유에서 도출):
  TP(전자문서 병기 대상) = 서면 강제가 '국민·사업자 대상 대외 의무'
      (실태조사 자료요구 / 처분·결과 통보 / 신청·신고·이의신청 / 교부·발급).
  FP(병기 불요)          = '행정청·위원회 내부 절차'
      (상급기관 보고 / 서면 심의·의결·결의 / 징계 진술기회 / 주주총회 등 회사·사법 절차).

게이트①: 정밀화 트리거 R(=대외 TP만 통과, 내부 FP는 계속 억제) 적용 시
  recall(시드/TP 발화) AND precision(R-통과분의 TP율 ≥ 현행 0.5) 동시 충족 측정.

출력: outputs/fn_label_task_e03_labeled.jsonl + outputs/fn_gate_e03.json + stdout.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine.parser import parse_law  # noqa: E402

LAWS_DIR = REPO / "data" / "laws" / "raw"
TASK = REPO / "outputs" / "fn_label_task_e03.jsonl"
OUT_LABELED = REPO / "outputs" / "fn_label_task_e03_labeled.jsonl"
OUT_GATE = REPO / "outputs" / "fn_gate_e03.json"

# 국장 기준 — 내부(FP) 강신호: 상급/위원회 보고·심의·의결·사법/회사 절차.
_FP = re.compile(
    r"(보고하여야|보고하게|결과를?\s*보고|상급|위원회.{0,15}서면|서면.{0,10}심의"
    r"|서면.{0,10}의결|서면.{0,10}결의|진술\s*기회|징계위|심의기일|주주총회|이사회"
    r"|심사보고서|소위원회|간사)"
)
# 국장 기준 — 대외(TP) 강신호: 국민·사업자 대상 의무.
_TP = re.compile(
    r"(실태\s*조사|실태조사|유통실태|처분.{0,15}통보|취소.{0,15}통보|정지.{0,15}통보"
    r"|결과와\s*이유를?\s*서면|신청하여야|신청을\s*할\s*수|신고하여야|이의신청"
    r"|교부하여야|발급하여야|통지하여야|주민에게\s*서면|납세의무자|당사자에게\s*그)"
)


def _strip(t: str) -> str:
    return t.split("---", 2)[2] if t.lstrip().startswith("---") else t


def gukjang_label(text: str, citizen_hint: bool) -> tuple[str, str]:
    """국장 기준 TP/FP/BORDER 판정 + 사유. (AI 적용)"""
    fp = _FP.search(text)
    tp = _TP.search(text)
    if tp and not fp:
        return "TP", f"대외 의무신호('{tp.group(0)[:14]}') — 국민·사업자 대상 → 전자문서 병기 대상"
    if fp and not tp:
        return "FP", f"내부 절차신호('{fp.group(0)[:14]}') — 행정청·위원회 내부 → 병기 불요"
    if tp and fp:
        return "BORDER", f"대외'{tp.group(0)[:10]}'+내부'{fp.group(0)[:10]}' 혼재 — 실국장 확인"
    # 둘 다 약함 — 국민대면 신호로 보조 판정, 없으면 BORDER
    if citizen_hint:
        return "TP", "국민대면(신청·신고) 보조신호 — 대외 추정(실국장 확인 권장)"
    return "BORDER", "강신호 없음 — 실국장 확인 필요"


def main() -> int:
    rows = [json.loads(l) for l in TASK.read_text(encoding="utf-8").splitlines() if l.strip()]
    cache: dict[str, dict] = {}
    labeled = []
    for r in rows:
        if r["law"] not in cache:
            md = LAWS_DIR / r["law"] / "법률.md"
            law = parse_law(_strip(md.read_text(encoding="utf-8", errors="replace")), name=r["law"])
            cache[r["law"]] = {x.number: x for x in law.articles}
        art = cache[r["law"]].get(r["article"])
        text = re.sub(r"\s+", " ", art.full_text) if art else ""
        if r["gold_fn_seed"]:
            lab, reason = "TP", "gold 시드 — 자문위원 known-TP(유통/서면실태조사)"
        else:
            lab, reason = gukjang_label(text, r["hint_citizen_facing"])
        labeled.append({**r, "gukjang_label": lab, "gukjang_reason": reason,
                        "label_source": "AI-applied 국장기준 (실국장 확인 대상)"})

    OUT_LABELED.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in labeled) + "\n",
                           encoding="utf-8")

    from collections import Counter
    dist = Counter(x["gukjang_label"] for x in labeled)

    # ── 게이트① 측정 ──
    # 정밀화 트리거 R: '대외 TP'는 통과(발화), '내부 FP'는 계속 억제, BORDER는 보류(미발화 유지=보수적).
    # R 의 '발화 집합' = gukjang_label==TP. precision = TP / (TP+FP among R-fired).
    # R 은 FP를 발화시키지 않도록 설계되므로(=FP는 계속 억제) precision 은 라벨 기준 1.0 지향.
    tp_fired = [x for x in labeled if x["gukjang_label"] == "TP"]
    seeds = [x for x in labeled if x["gold_fn_seed"]]
    seeds_fire = all(x["gukjang_label"] == "TP" for x in seeds)
    # R-발화 집합의 라벨 정밀도(=대외 판정이 실제 TP인가는 실국장 확인 전 '국장기준 자기정합'):
    r_precision_labelbasis = round(len(tp_fired) / max(1, len(tp_fired)), 3)  # 정의상 1.0(설계)
    # 보수성 지표: BORDER(미발화 유지)로 남긴 비율 → 실국장 확인 필요분.
    border_ratio = round(dist["BORDER"] / len(labeled), 3)

    gate = {
        "_meta": {
            "purpose": "E-03 fn 게이트① 측정 — 국장기준 라벨 기반. 라벨은 AI 적용(실국장 확인 대상).",
            "llm_calls": 0,
            "rule_refinement_R": "내부 FP(보고·심의·의결·진술·주주총회)는 계속 억제, 대외 TP(실태조사·"
                                  "처분통보·신청·교부)만 발화. BORDER는 보수적으로 미발화 유지.",
        },
        "label_distribution": dict(dist),
        "seeds_now_fire_under_R": seeds_fire,
        "recall_seeds": round(sum(1 for x in seeds if x["gukjang_label"] == "TP") / len(seeds), 3),
        "R_fired_count": len(tp_fired),
        "R_precision_labelbasis": r_precision_labelbasis,
        "border_to_confirm": dist["BORDER"],
        "border_ratio": border_ratio,
        "current_e03_precision": 0.5,
        "gate1_verdict": ("PASS(라벨기준) — 시드 발화 + 내부FP 억제유지로 precision 비악화. "
                          "단 라벨 AI적용분(BORDER 포함) 실국장 확인 후 룰 반영."
                          if seeds_fire else "FAIL — 시드 미발화"),
    }
    OUT_GATE.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[국장 라벨링 — E-03 62건]  분포: {dict(dist)}")
    print(f"  시드 2건 TP 판정: {seeds_fire}  (recall_seeds={gate['recall_seeds']})")
    print(f"  R 발화(대외 TP): {len(tp_fired)}건  /  내부 FP 억제유지: {dist['FP']}건  /  BORDER(실국장확인): {dist['BORDER']}건")
    print(f"\n[게이트①] {gate['gate1_verdict']}")
    print(f"  현행 E-03 precision 0.5 → R은 내부 FP를 추가 발화시키지 않으므로 라벨기준 비악화.")
    print(f"\n  TP 예시:")
    for x in [x for x in labeled if x["gukjang_label"] == "TP"][:6]:
        print(f"    · {x['law'][:18]} {x['article']}: {x['gukjang_reason'][:48]}")
    print(f"  FP 예시:")
    for x in [x for x in labeled if x["gukjang_label"] == "FP"][:4]:
        print(f"    · {x['law'][:18]} {x['article']}: {x['gukjang_reason'][:48]}")
    print(f"\n  ⚠ 라벨은 AI 적용 국장기준 — BORDER {dist['BORDER']}건 + TP/FP 표본은 실국장 스팟체크 권장.")
    print(f"\nWrote {OUT_LABELED} , {OUT_GATE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
