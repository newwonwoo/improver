#!/usr/bin/env python3
"""엔진 강화 하네스 — docs/ENGINE_PRINCIPLES.md R3 시행.

본 스크립트는 LLM 검증 정답지에 대해 현재 엔진의 정밀도/재현율/F1 을
측정하고 baseline 과 비교한다.  F1 회귀가 발생하면 비-0 종료코드로 PR 을
막는다.

입력:
    outputs/verification_dataset.jsonl  — LLM verdicts (정답지)
    outputs/harness_baseline.json       — 마지막 통과 점수 (없으면 baseline 으로 저장)
    data/laws/raw/<법령명>/법률.md      — 분석 대상 본문

출력:
    outputs/harness_report.json         — 룰별/전체 metrics
    outputs/harness_baseline.json       — F1 가 개선되면 갱신
    stdout                              — 사람용 표

종료 코드:
    0  baseline 통과 (또는 baseline 생성)
    1  사용 오류
    2  F1 회귀 — PR block
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine.parser import parse_law  # noqa: E402
from engine.rules import run_all  # noqa: E402


VERDICTS_PATH = REPO / "outputs" / "verification_dataset.jsonl"
BASELINE_PATH = REPO / "outputs" / "harness_baseline.json"
REPORT_PATH = REPO / "outputs" / "harness_report.json"
LAWS_DIR = REPO / "data" / "laws" / "raw"

# F1 가 이 값 이상 떨어지면 회귀로 간주하고 PR 차단
F1_REGRESSION_TOLERANCE = 0.005


@dataclass
class Metrics:
    """단일 룰 또는 전체에 대한 confusion matrix + 파생 지표."""

    tp: int = 0  # 엔진 발화 + LLM TP
    fp: int = 0  # 엔진 발화 + LLM FP
    fn: int = 0  # 엔진 미발화 + LLM TP
    tn: int = 0  # 엔진 미발화 + LLM FP
    border_fired: int = 0
    border_skipped: int = 0
    missing: int = 0  # 정답지에 있는데 법령 파싱 실패

    @property
    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def _categorize(name: str) -> str:
    if any(k in name for k in ("금융", "은행", "보험", "투자", "신용", "증권", "여신")):
        return "금융법"
    if any(k in name for k in ("공공기관", "공기업", "공단", "공사", "기금")):
        return "공공기관법"
    return "일반"


def _load_verdicts() -> dict[str, dict[str, str]]:
    """fid → {verdict, rule_id, law_name, evidence}.

    fid 형식: "<rule_id>-<seq>@<법령명>"  (예: "E-01-002@가정폭력범죄의처벌등에관한특례법")
    """
    if not VERDICTS_PATH.exists():
        print(f"검증 데이터셋 없음: {VERDICTS_PATH}", file=sys.stderr)
        print("먼저 scripts/import_rule_verification.py 실행", file=sys.stderr)
        sys.exit(1)
    verdicts: dict[str, dict[str, str]] = {}
    with VERDICTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            fid = d.get("fid")
            if not fid or "@" not in fid:
                continue
            _rule_seq, law_name = fid.split("@", 1)
            verdicts[fid] = {
                "verdict": d["verdict"],
                "rule_id": d["rule_id"],
                "law_name": law_name,
                "evidence": d.get("evidence", ""),
            }
    return verdicts


def _engine_findings_for(law_name: str) -> list:
    """법령명을 받아 현재 엔진의 finding 목록을 돌려준다.

    파싱이 실패하면 빈 리스트를 반환하고 missing 으로 카운트하도록 한다.
    """
    law_dir = LAWS_DIR / law_name
    md = law_dir / "법률.md"
    if not md.exists():
        return None  # type: ignore
    text = md.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    law = parse_law(text, name=law_name, law_category=_categorize(law_name))
    return run_all(law)


# 룰 → 카테고리 매핑 (engine/rules/*.py 의 category 속성)
RULE_CATEGORY = {
    "S-01": "구조", "S-02": "구조", "S-03": "구조", "S-04": "구조",
    "F-01": "공정성", "F-02": "공정성", "F-03": "공정성",
    "F-04": "공정성", "F-05": "공정성",
    "L-01": "적법성", "L-02": "적법성", "L-03": "적법성",
    "G-01": "거버넌스", "G-02": "거버넌스", "G-03": "거버넌스",
    "G-04": "거버넌스", "G-05": "거버넌스",
    "E-01": "효율성", "E-02": "효율성", "E-03": "효율성",
    "E-04": "효율성", "E-05": "효율성",
}


def evaluate() -> dict:
    """정답지 vs 엔진 비교."""
    verdicts = _load_verdicts()

    # 법령별로 검증 대상 fid 그룹화 — 같은 법령은 한 번만 파싱
    by_law: dict[str, list[str]] = defaultdict(list)
    for fid, info in verdicts.items():
        by_law[info["law_name"]].append(fid)

    per_rule: dict[str, Metrics] = defaultdict(Metrics)
    per_category: dict[str, Metrics] = defaultdict(Metrics)
    overall = Metrics()
    cases: list[dict] = []  # 디버깅용 — fp/fn 만 기록

    for law_name, fids in by_law.items():
        findings = _engine_findings_for(law_name)
        if findings is None:
            for fid in fids:
                per_rule[verdicts[fid]["rule_id"]].missing += 1
                overall.missing += 1
            continue

        # 엔진이 이 법령에서 발화한 pattern_id 집합
        fired_rules = {f.pattern_id for f in findings}

        for fid in fids:
            info = verdicts[fid]
            rule_id = info["rule_id"]
            verdict = info["verdict"]
            fired = rule_id in fired_rules

            m = per_rule[rule_id]
            cat = RULE_CATEGORY.get(rule_id, "기타")
            cm = per_category[cat]

            if verdict == "BORDER":
                if fired:
                    m.border_fired += 1; cm.border_fired += 1
                    overall.border_fired += 1
                else:
                    m.border_skipped += 1; cm.border_skipped += 1
                    overall.border_skipped += 1
                continue

            if verdict == "TP":
                if fired:
                    m.tp += 1; cm.tp += 1; overall.tp += 1
                else:
                    m.fn += 1; cm.fn += 1; overall.fn += 1
                    cases.append({
                        "fid": fid, "kind": "FN", "category": cat,
                        "evidence": info["evidence"],
                    })
            elif verdict == "FP":
                if fired:
                    m.fp += 1; cm.fp += 1; overall.fp += 1
                    cases.append({
                        "fid": fid, "kind": "FP", "category": cat,
                        "evidence": info["evidence"],
                    })
                else:
                    m.tn += 1; cm.tn += 1; overall.tn += 1

    report = {
        "overall": overall.to_dict(),
        "per_rule": {
            r: m.to_dict() for r, m in sorted(per_rule.items())
        },
        "per_category": {
            c: m.to_dict() for c, m in sorted(per_category.items())
        },
        "n_verdicts": sum(
            m.tp + m.fp + m.fn + m.tn
            for m in per_rule.values()
        ),
        "fp_fn_cases": cases[:200],  # 처음 200개만 — 디버깅용
    }
    return report


def _print_table(report: dict) -> None:
    print()
    print(f"{'Rule':<8} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5} {'P':>7} {'R':>7} {'F1':>7}  {'Δ vs base':>10}")
    print("-" * 78)
    baseline = _load_baseline()
    base_per_rule = baseline.get("per_rule", {}) if baseline else {}

    for rule, m in report["per_rule"].items():
        p = m["precision"] or 0
        r = m["recall"] or 0
        f1 = m["f1"] or 0
        base_f1 = (base_per_rule.get(rule, {}).get("f1") or 0)
        delta = f1 - base_f1
        delta_str = f"{delta:+.3f}" if baseline else "—"
        print(
            f"{rule:<8} {m['tp']:>5} {m['fp']:>5} {m['fn']:>5} {m['tn']:>5} "
            f"{p:>7.3f} {r:>7.3f} {f1:>7.3f}  {delta_str:>10}"
        )

    print("-" * 78)
    o = report["overall"]
    base_o = baseline.get("overall", {}) if baseline else {}
    p = o["precision"] or 0
    r = o["recall"] or 0
    f1 = o["f1"] or 0
    base_f1 = base_o.get("f1") or 0
    delta = f1 - base_f1
    delta_str = f"{delta:+.3f}" if baseline else "—"
    print(
        f"{'TOTAL':<8} {o['tp']:>5} {o['fp']:>5} {o['fn']:>5} {o['tn']:>5} "
        f"{p:>7.3f} {r:>7.3f} {f1:>7.3f}  {delta_str:>10}"
    )
    print()
    print(f"BORDER fired/skipped: {o['border_fired']}/{o['border_skipped']}")
    print(f"missing (법령 파일 누락): {o['missing']}")

    # 카테고리별 진단
    print()
    print(f"{'Category':<10} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5} {'P':>7} {'R':>7} {'F1':>7}")
    print("-" * 60)
    base_per_cat = baseline.get("per_category", {}) if baseline else {}
    for cat, m in report.get("per_category", {}).items():
        p = m["precision"] or 0
        r = m["recall"] or 0
        f1 = m["f1"] or 0
        delta = f1 - (base_per_cat.get(cat, {}).get("f1") or 0)
        delta_str = f" Δ{delta:+.3f}" if baseline else ""
        print(
            f"{cat:<10} {m['tp']:>5} {m['fp']:>5} {m['fn']:>5} {m['tn']:>5} "
            f"{p:>7.3f} {r:>7.3f} {f1:>7.3f}{delta_str}"
        )
    print()


def _load_baseline() -> dict | None:
    if BASELINE_PATH.exists():
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return None


def _save_baseline(report: dict) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "overall": report["overall"],
        "per_rule": report["per_rule"],
        "n_verdicts": report["n_verdicts"],
    }
    BASELINE_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="현재 점수를 새 baseline 으로 저장 (CI 에선 사용 금지)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="F1 가 baseline 보다 떨어지면 비-0 종료 (CI 게이트)",
    )
    args = parser.parse_args()

    report = evaluate()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _print_table(report)

    baseline = _load_baseline()
    if baseline is None:
        _save_baseline(report)
        print(f"baseline 생성: {BASELINE_PATH.relative_to(REPO)}")
        return 0

    cur_f1 = report["overall"]["f1"] or 0
    base_f1 = baseline["overall"].get("f1") or 0
    delta = cur_f1 - base_f1

    if args.update_baseline:
        if delta < -F1_REGRESSION_TOLERANCE:
            print(f"⚠ F1 회귀 (Δ={delta:+.4f}). baseline 갱신 거부.", file=sys.stderr)
            return 2
        _save_baseline(report)
        print(f"baseline 갱신: Δ={delta:+.4f}")
        return 0

    if args.strict and delta < -F1_REGRESSION_TOLERANCE:
        print(
            f"❌ F1 회귀 — base={base_f1:.4f} cur={cur_f1:.4f} Δ={delta:+.4f}",
            file=sys.stderr,
        )
        print("→ docs/ENGINE_PRINCIPLES.md R3 위반. PR 차단.", file=sys.stderr)
        return 2

    print(f"OK — base F1 {base_f1:.4f} → cur F1 {cur_f1:.4f} (Δ {delta:+.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
