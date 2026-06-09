#!/usr/bin/env python3
"""결정 2·3 + 버그 측정 하네스 — 자문위원 gold 상관 검증 (LLM/외부 API 0회).

목적 (TF 인수인계서 '다음 세션 시작점'):
  결정 2  채점기 재튜닝: 자동 구체성(글자수) → **자문위원 채택판정과 상관**되는
          score_adoption 으로 교체. 같은(=자문위원이 실제 검토한) 권고문에 두 채점기를
          적용해 채택(채택 vs 수정) 판별력을 AUC + bootstrap CI 로 비교한다.
  결정 3  처방 합성 '단정→근거기반 검토제시': 같은 표본에서 구(舊) 처방과 신(新) 처방을
          재생성해, gold 가 반려/수정 사유로 든 '근거 없는 숫자 단정'이 제거됐는지 측정.
  버그    L-03 추출 어긋남: 인용 결함의 verbatim 이 matched_text 인용에 정합(anchored)
          하게 바뀌었는지 4건에서 측정. L-01 폐지 단정: config 에서 제거됐는지 점검.

규율 (인수인계서): 측정 먼저, 단정 금지. 평가는 bootstrap CI. LLM 0회.
표본: outputs/gold_reco_review.jsonl(55) ∩ outputs/reco_mechanical_measure.json(자문위원이
      검토한 바로 그 권고문) ∩ data/laws/raw(본문). 채점 대상은 권고가 존재한 scored 33건.

출력: outputs/gold_correlation_measure.json + stdout.
측정 전용 — 프로덕션은 config/recommendations.json(L-01) 만 수정.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine import fpc, recommender, scorer  # noqa: E402
from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402
import scripts.mechanical_reco as mr  # noqa: E402

GOLD_PATH = REPO / "outputs" / "gold_reco_review.jsonl"
REVIEWED_PATH = REPO / "outputs" / "reco_mechanical_measure.json"
LAWS_DIR = REPO / "data" / "laws" / "raw"
RECO_CONFIG = REPO / "config" / "recommendations.json"
REPORT_PATH = REPO / "outputs" / "gold_correlation_measure.json"

VERDICT_ORD = {"반려": 0, "수정": 1, "채택": 2}
BOOT_N = 2000
SEED = 42


def _strip_frontmatter(text: str) -> str:
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def _norm_art(s: str) -> str:
    return (s or "").strip().replace(" ", "").replace(" ", "")


# ── AUC(양성=채택 vs 음성=수정) + bootstrap CI ─────────────────────────────
def _auc(scores: list[float], labels: list[int]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for q in neg:
            wins += 1.0 if p > q else (0.5 if p == q else 0.0)
    return wins / (len(pos) * len(neg))


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _bootstrap_auc(scores, labels, n=BOOT_N, seed=SEED):
    rng = random.Random(seed)
    m = len(scores)
    vals = []
    for _ in range(n):
        idx = [rng.randrange(m) for _ in range(m)]
        a = _auc([scores[i] for i in idx], [labels[i] for i in idx])
        if a is not None:
            vals.append(a)
    if not vals:
        return None
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[int(0.975 * len(vals))]
    return round(lo, 3), round(hi, 3)


def main() -> int:
    gold = {json.loads(l)["fid"]: json.loads(l) for l in GOLD_PATH.read_text(encoding="utf-8").splitlines() if l.strip()}
    # ⚠️ reco_mechanical_measure.json 은 '자문위원이 검토한 그 권고문' = 고정 스냅샷이어야 한다.
    #    measure_reco_mechanical.py 를 재실행하면 신 처방으로 덮어써져 '검토된 텍스트' 검증이
    #    깨진다(채점기를 신 텍스트로 채점). 덮어썼다면 `git checkout` 로 복원할 것.
    reviewed = {r["fid"]: r for r in json.loads(REVIEWED_PATH.read_text(encoding="utf-8"))["records"]}

    # 검토 대상: 권고가 실재한(scored) 행만 — 자문위원이 채택/수정 판정한 표본.
    fids = [f for f in gold if reviewed.get(f, {}).get("status") == "scored"]

    # 법령 본문 1회 파싱 → article 객체 확보 (피처·신처방 재생성용).
    by_law: dict[str, list[str]] = {}
    for f in fids:
        by_law.setdefault(f.split("@", 1)[1], []).append(f)

    rows = []
    for law_name, flist in by_law.items():
        md = LAWS_DIR / law_name / "법률.md"
        if not md.exists():
            continue
        law = parse_law(_strip_frontmatter(md.read_text(encoding="utf-8", errors="replace")), name=law_name)
        art_by_norm = {_norm_art(a.number): a for a in law.articles}
        for f in flist:
            rec = reviewed[f]
            article = art_by_norm.get(_norm_art(rec["article"]))
            if article is None:
                continue
            finding = SimpleNamespace(pattern_id=rec["pattern_id"],
                                      matched_text=rec.get("internal_matched_text"))
            verdict = gold[f]["verdict"]

            # 자문위원이 검토한 '구(舊) 권고문' (as-reviewed).
            reviewed_text = rec["mechanical_recommendation"]
            old_verbatim = rec.get("verbatim_extracted")
            old_method = rec.get("extract_method", "none")
            old_autospec = rec["mechanical"]["specificity"]  # 구 채점기 점수 (0/1/2)

            # 신(新) 채점기를 '검토된 그 권고문'에 적용 → gold 와 상관 검증.
            new_score_on_reviewed, feats = mr.score_adoption(reviewed_text, old_verbatim, old_method, finding, article)

            # 결정 3 + 라운드2(코더): 신 처방 재생성 (단정→근거기반, 조문특성 분기).
            new_text, new_verb, new_method = mr.make_mechanical(article, finding)
            new_score, _ = mr.score_adoption(new_text, new_verb, new_method, finding, article)

            rows.append({
                "fid": f, "pattern_id": rec["pattern_id"], "verdict": verdict,
                "matched_text": finding.matched_text,
                "reviewed_text": reviewed_text,
                "old_verbatim": old_verbatim, "old_method": old_method,
                "old_autospec": old_autospec,
                "adoption_score": new_score_on_reviewed, "adoption_features": feats,
                "old_has_unfounded_number": mr._has_unfounded_number(reviewed_text, article),
                "new_text": new_text, "new_verbatim": new_verb, "new_method": new_method,
                "new_has_unfounded_number": mr._has_unfounded_number(new_text, article),
                "new_adoption_score": new_score,
                "g04_absent_named": (rec["pattern_id"] == "G-04" and "확인되지 않음" in new_text),
                "s04_branch": ("정렬" if "체계적 정렬" in new_text else
                               ("별표" if "별표" in new_text else None)) if rec["pattern_id"] == "S-04" else None,
            })

    # ── 결정 2: 채택판정 판별력 (채택=1 vs 수정=0), 구 채점기 vs 신 채점기 ──
    bin_rows = [r for r in rows if r["verdict"] in ("채택", "수정")]
    labels = [1 if r["verdict"] == "채택" else 0 for r in bin_rows]
    old_scores = [float(r["old_autospec"]) for r in bin_rows]
    new_scores = [float(r["adoption_score"]) for r in bin_rows]

    auc_old = _auc(old_scores, labels)
    auc_new = _auc(new_scores, labels)
    ci_old = _bootstrap_auc(old_scores, labels)
    ci_new = _bootstrap_auc(new_scores, labels)

    ords = [VERDICT_ORD[r["verdict"]] for r in bin_rows]
    sp_old = _spearman(old_scores, [float(o) for o in ords])
    sp_new = _spearman(new_scores, [float(o) for o in ords])

    # ── 결정 3: 근거 없는 숫자 단정 제거 측정 ──
    old_num = [r["fid"] for r in rows if r["old_has_unfounded_number"]]
    new_num = [r["fid"] for r in rows if r["new_has_unfounded_number"]]
    removed = sorted(set(old_num) - set(new_num))

    # ── 버그 L-03: 인용 verbatim 이 matched_text 에 정합(anchored)됐나 ──
    l03 = [r for r in rows if r["pattern_id"] == "L-03"]
    l03_old_aligned = sum(1 for r in l03 if r["old_method"] == "anchored")
    l03_new_aligned = sum(1 for r in l03 if r["new_method"] == "anchored")

    # ── 버그 L-01: config 에서 '폐지' 단정이 제거됐나 ──
    cfg = json.loads(RECO_CONFIG.read_text(encoding="utf-8"))
    l01_cfg = cfg.get("L-01", {})
    l01_repealed_residue = any("폐지" in (v or "") for v in l01_cfg.values())

    # ── 라운드2 (코더): G-04 누락요소 지목 / S-04 호개수 분기 ──
    g04 = [r for r in rows if r["pattern_id"] == "G-04"]
    g04_named = sum(1 for r in g04 if r["g04_absent_named"])
    s04 = [r for r in rows if r["pattern_id"] == "S-04"]
    s04_branch = {r["fid"].split("@")[0] + "@" + r["fid"].split("@")[1][:6]: r["s04_branch"] for r in s04}
    # 신 처방의 '예측' 채택성(자문위원 재검 전, 단정 금지) — 검토된 권고 대비 상승분.
    pred_old = [r["adoption_score"] for r in rows]
    pred_new = [r["new_adoption_score"] for r in rows]
    pred_delta = round(sum(pred_new) / len(pred_new) - sum(pred_old) / len(pred_old), 4) if rows else None

    report = {
        "_meta": {
            "purpose": "결정2(채점기 gold상관 재튜닝)+결정3(단정→검토제시)+버그(L-03/L-01) 측정",
            "llm_calls": 0, "external_api_calls": 0,
            "sample": "gold scored 33건 (채택 vs 수정). 반려는 권고 부재(fn_not_fired)라 제외.",
            "discipline": "측정 먼저, bootstrap CI, 차이<0.04 노이즈. 신 처방의 채택률은 자문위원 재검 전까지 단정 금지.",
        },
        "decision2_scorer": {
            "n": len(bin_rows), "n_adopt": sum(labels), "n_modify": len(labels) - sum(labels),
            "old_scorer": "auto_specificity (글자수/verbatim 길이)",
            "new_scorer": "score_adoption (정형성·근거성·지목정합)",
            "auc_adopt_vs_modify": {"old": auc_old, "new": auc_new},
            "auc_ci95": {"old": ci_old, "new": ci_new},
            "spearman_vs_verdict_ord": {"old": sp_old, "new": sp_new},
        },
        "decision3_prescription": {
            "old_unfounded_number_count": len(old_num),
            "new_unfounded_number_count": len(new_num),
            "removed_fids": removed,
            "note": "근거 없는 숫자(예 F-04 '14일') 제거. 채택률 단정은 자문위원 재검 게이트 대상.",
        },
        "bug_l03_extraction": {
            "n": len(l03),
            "old_anchored": l03_old_aligned, "new_anchored": l03_new_aligned,
            "detail": [{"fid": r["fid"], "matched_text": r["matched_text"],
                        "old_verbatim": r["old_verbatim"], "new_verbatim": r["new_verbatim"],
                        "old_method": r["old_method"], "new_method": r["new_method"]} for r in l03],
        },
        "bug_l01_repealed_residue": {
            "config_still_has_폐지_assertion": l01_repealed_residue,
            "L-01_templates": l01_cfg,
        },
        "round2_coder": {
            "g04_n": len(g04), "g04_absent_named": g04_named,
            "s04_branch_by_ho": s04_branch,
            "predicted_adoption_on_new_text": {
                "old_mean": round(sum(pred_old) / len(pred_old), 4) if rows else None,
                "new_mean": round(sum(pred_new) / len(pred_new), 4) if rows else None,
                "delta": pred_delta,
                "caveat": "score_adoption(gold AUC 0.94)의 '예측'. 실제 채택률은 자문위원 재검 게이트 전까지 단정 금지.",
            },
        },
        "rows": rows,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── stdout ──
    d2 = report["decision2_scorer"]
    print("\n[결정 2] 채점기 gold 상관 — 채택(={}) vs 수정(={}) 판별력".format(d2["n_adopt"], d2["n_modify"]))
    print(f"  구 채점기(auto-spec)  AUC={auc_old}  CI95={ci_old}  Spearman={sp_old}")
    print(f"  신 채점기(adoption)   AUC={auc_new}  CI95={ci_new}  Spearman={sp_new}")
    if auc_old is not None and auc_new is not None:
        print(f"  ΔAUC = {auc_new - auc_old:+.3f}  (CI 겹침 여부로 유의성 판단)")
    print("\n[결정 3] 근거 없는 숫자 단정 제거")
    print(f"  구 처방 단정 {len(old_num)}건 → 신 처방 {len(new_num)}건. 제거: {len(removed)}건")
    for f in removed:
        print(f"    - {f}")
    print("\n[버그 L-03] 인용 verbatim matched_text 정합(anchored)")
    print(f"  구 {l03_old_aligned}/{len(l03)}  →  신 {l03_new_aligned}/{len(l03)}")
    for r in l03:
        print(f"    · {r['fid'].split('@')[0]}@…  matched={r['matched_text']!r}")
        print(f"      구: ({r['old_method']}) {str(r['old_verbatim'])[:55]}")
        print(f"      신: ({r['new_method']}) {str(r['new_verbatim'])[:55]}")
    print("\n[버그 L-01] config 폐지 단정 잔재:", l01_repealed_residue)
    print("\n[라운드2/코더] G-04 누락요소 지목  {}/{}".format(g04_named, len(g04)))
    print("              S-04 호개수 분기:", s04_branch)
    print("              신 처방 예측 채택성(자문위원 재검 전 단정 금지): "
          f"{report['round2_coder']['predicted_adoption_on_new_text']['old_mean']} "
          f"→ {report['round2_coder']['predicted_adoption_on_new_text']['new_mean']} "
          f"(Δ{pred_delta:+})")
    print(f"\nWrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
