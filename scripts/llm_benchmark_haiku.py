"""하이쿠 벤치마크 — 자체 SLM vs 소형 LLM(claude-haiku-4-5) 동일 표본 비교.

팀장 지시(2026-06-10): "최소 하이쿠 (하위)급 수준 성능을 자체적으로 내야 함 —
벤치마크 결과로 비교." 계획 v2 §3 프로토콜 수정조항(감사인 승인 조건):
  - 벤치 LLM 의 예측은 **라벨로 사용 금지** — 비교 전용. 학습/튜닝에 유입 0.
  - 블라인드: 프롬프트에 라벨·룰 발화 정보 비노출. CLI 는 레포 밖(/tmp)에서 실행.
  - 모든 호출 입출력 보존(outputs/llm_benchmark_calls/).
  - 표본·잣대 사전 고정: text_boost 실험과 동일 행에서 카테고리별 층화 샘플
    (category 라벨 보유 행에서 양성≤25·음성≤25, seed 42), micro-F1 + bootstrap CI.

비교 대상: 룰 단독 / E1~E4 (OOF — 해당 행이 test fold 였을 때의 예측) / 하이쿠.
하이쿠는 fold 학습이 없으므로 전 표본이 사실상 zero-shot test — 공정.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

from engine.slm.brain import CATEGORIES
from engine.slm.torch_brain import _prf

MODEL = "claude-haiku-4-5-20251001"
BATCH = 8
TEXT_CLIP = 1800
CALL_DIR = Path("outputs/llm_benchmark_calls")

CAT_DEF = {
    "구조": "조문 구조 결함 — 과도한 호 나열, 캐치올 남용, 비대한 단일 조문, 중복 규정 등 구조적 정비 필요.",
    "공정성": "공정성 결함 — 자의적 재량 기준, 청문·의견제출 절차 누락, 과도한 제재/면책, 간주 동의, 이유제시 없는 처분 등.",
    "적법성": "적법성 결함 — 포괄위임, 깨진/모순 인용, 이중제재, 기한 없는 처분권, 행정규칙 재위임 등 법체계 위반 소지.",
    "거버넌스": "거버넌스 결함 — 내부통제 요소 누락, 위원회 구성·이해충돌 관리 부실, 과도한 단서 조항 등 운영 통제 결함.",
    "효율성": "효율성 결함 — 불필요한 서면 절차 강제, 중복 보고, 제재 공백, 비효율적 행정 부담 등.",
}

SYSTEM = """당신은 법제처 규제 정비 심사관이다. 주어진 법령 조문에 대해, 지정된 평가 카테고리의
'실재하는 규정 결함(정비 필요점)'이 있는지 판정한다. 결함이 실재하면 "TP", 그 카테고리의
결함이 없거나 정상적 입법 형태면 "FP"로 답한다. 과잉 지적(정상 조문을 결함으로 모는 것)도
오답이고, 실재 결함을 놓치는 것도 오답이다.
응답은 반드시 JSON 배열만 출력: [{"id": <번호>, "verdict": "TP"|"FP"}, ...] (설명·코드펜스 금지)"""


def build_sample(y, rows, *, per_side=25, seed=42):
    """카테고리별 층화 샘플: (row_idx, cat_idx) 케이스 목록."""
    rng = np.random.default_rng(seed)
    cases = []
    for ci, cat in enumerate(CATEGORIES):
        col = y[:, ci]
        pos = np.where(col == 1)[0]
        neg = np.where(col == 0)[0]
        pos = rng.permutation(pos)[:per_side]
        neg = rng.permutation(neg)[:per_side]
        for ri in list(pos) + list(neg):
            cases.append(dict(row=int(ri), cat=ci))
    return cases


def make_prompt(batch_cases, rows):
    lines = []
    for j, c in enumerate(batch_cases):
        r = rows[c["row"]]
        cat = CATEGORIES[c["cat"]]
        text = r["text"][:TEXT_CLIP]
        lines.append(
            f"### 케이스 {j}\n- 평가 카테고리: {cat} — {CAT_DEF[cat]}\n"
            f"- 법령: {r['law']} {r['article']}\n- 조문:\n{text}\n")
    return "\n".join(lines) + f"\n위 {len(batch_cases)}개 케이스를 각각 판정하라."


def call_haiku(prompt, tag):
    CALL_DIR.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            p = subprocess.run(
                ["claude", "-p", "--model", MODEL,
                 "--append-system-prompt", SYSTEM],
                input=prompt, capture_output=True, text=True,
                timeout=300, cwd="/tmp")
            raw = p.stdout.strip()
        except subprocess.TimeoutExpired:
            raw = ""
        (CALL_DIR / f"{tag}_try{attempt}.json").write_text(json.dumps(
            dict(model=MODEL, prompt=prompt, raw=raw), ensure_ascii=False),
            encoding="utf-8")
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                arr = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))
                out = {}
                for item in arr:
                    if isinstance(item, dict) and "id" in item and \
                            str(item.get("verdict")).upper() in ("TP", "FP"):
                        out[int(item["id"])] = 1.0 if str(item["verdict"]).upper() == "TP" else 0.0
                if out:
                    return out
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        time.sleep(2 * (attempt + 1))
    return {}


def micro_f1_ci(y_true, y_pred, *, n_boot=1000, seed=42):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    valid = ~np.isnan(y_pred)

    def f1_of(idx):
        yt, yp = y_true[idx], y_pred[idx]
        m = ~np.isnan(yp)
        yt, yp = yt[m], yp[m]
        tp = float(((yp == 1) & (yt == 1)).sum())
        fp = float(((yp == 1) & (yt == 0)).sum())
        fn = float(((yp == 0) & (yt == 1)).sum())
        return _prf(tp, fp, fn)[2]

    n = len(y_true)
    point = f1_of(np.arange(n))
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for b in range(n_boot):
        stats[b] = f1_of(rng.integers(0, n, size=n))
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return dict(f1=point, ci_lo=float(lo), ci_hi=float(hi),
                coverage=float(valid.mean()))


def main():
    rows = [json.loads(l) for l in open("outputs/text_boost_rows.jsonl", encoding="utf-8")]
    npz = np.load("outputs/text_boost_oof.npz")
    y = npz["y"]
    systems = {"rule": npz["rule_pred"], "e1_text": npz["oof_e1_text"],
               "e2_boost": npz["oof_e2_boost"], "e3_combo": npz["oof_e3_combo"],
               "e4_select": npz["oof_e4_select"]}
    if "oof_e4b" in npz:
        systems["e4b_nested"] = npz["oof_e4b"]

    cases = build_sample(y, rows)
    print(f"벤치 표본: {len(cases)} 케이스 (카테고리별 양성≤25·음성≤25, seed 42)")

    batches = [cases[i:i + BATCH] for i in range(0, len(cases), BATCH)]

    def run_batch(bi):
        preds = call_haiku(make_prompt(batches[bi], rows), tag=f"b{bi:03d}")
        print(f"  배치 {bi + 1}/{len(batches)}: 응답 {len(preds)}/{len(batches[bi])}")
        return bi, preds

    haiku_pred = np.full(len(cases), np.nan)
    with ThreadPoolExecutor(max_workers=3) as ex:
        for bi, preds in ex.map(run_batch, range(len(batches))):
            for j, v in preds.items():
                gi = bi * BATCH + j
                if 0 <= gi < len(cases) and j < len(batches[bi]):
                    haiku_pred[gi] = v

    y_true = np.array([y[c["row"], c["cat"]] for c in cases])
    report = {"n_cases": len(cases),
              "haiku": micro_f1_ci(y_true, haiku_pred)}
    for name, mat in systems.items():
        sys_pred = np.array([mat[c["row"], c["cat"]] for c in cases])
        report[name] = micro_f1_ci(y_true, sys_pred)

    # 카테고리별 분해 (하이쿠 vs 자체 주력)
    own_best = "e4b_nested" if "e4b_nested" in systems else "e4_select"
    per_cat = {}
    for ci, cat in enumerate(CATEGORIES):
        idx = [k for k, c in enumerate(cases) if c["cat"] == ci]
        per_cat[cat] = {
            "haiku": micro_f1_ci(y_true[idx], haiku_pred[idx], n_boot=500),
            own_best: micro_f1_ci(
                y_true[idx],
                np.array([systems[own_best][cases[k]["row"], ci] for k in idx]),
                n_boot=500),
            "rule": micro_f1_ci(
                y_true[idx],
                np.array([systems["rule"][cases[k]["row"], ci] for k in idx]),
                n_boot=500),
        }
    report["per_cat"] = per_cat
    report["model"] = MODEL
    report["protocol"] = ("동일 표본(text_boost 행), 층화 샘플 seed 42, 블라인드 zero-shot, "
                          "하이쿠 예측은 비교 전용(라벨 사용 금지)")

    print(f"\n{'시스템':<12} {'micro-F1':>9}  {'95% CI':<18} {'응답률':>6}")
    print("-" * 50)
    order = ["haiku"] + list(systems)
    for name in order:
        r = report[name]
        print(f"{name:<12} {r['f1']:>9.3f}  [{r['ci_lo']:.3f},{r['ci_hi']:.3f}]"
              f"   {r['coverage']:>5.0%}")

    Path("outputs/llm_benchmark_haiku.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n(산출물 outputs/llm_benchmark_haiku.json — 하이쿠 예측 라벨 미사용)")


if __name__ == "__main__":
    main()
