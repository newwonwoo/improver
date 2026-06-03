#!/usr/bin/env python3
"""Article-level engine harness — verdict가 매핑된 정확한 article 에서 룰이 발화했는지 측정.

기존 scripts/engine_harness.py 는 법령-level fired 측정. 본 스크립트는
번들 md 파일에서 추출한 fid → article 매핑을 활용해 article-level fired
측정. 룰 패치의 정밀 효과 측정용.

입력:
    outputs/verification_dataset.jsonl  — LLM verdicts
    outputs/fid_article_map.json        — fid → article_number 매핑
    data/laws/raw/<법령명>/법률.md

출력:
    outputs/harness_article_report.json
    stdout — 사람용 표
"""
from __future__ import annotations

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
FID_MAP_PATH = REPO / "outputs" / "fid_article_map.json"
REPORT_PATH = REPO / "outputs" / "harness_article_report.json"
LAWS_DIR = REPO / "data" / "laws" / "raw"


@dataclass
class Metrics:
    tp: int = 0; fp: int = 0; fn: int = 0; tn: int = 0
    border_fired: int = 0; border_skipped: int = 0
    missing: int = 0; unmapped: int = 0

    @property
    def precision(self):
        d = self.tp + self.fp; return self.tp / d if d else None
    @property
    def recall(self):
        d = self.tp + self.fn; return self.tp / d if d else None
    @property
    def f1(self):
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0: return None
        return 2 * p * r / (p + r)
    def to_dict(self):
        return {**asdict(self), "precision": self.precision, "recall": self.recall, "f1": self.f1}


def _categorize(name):
    if any(k in name for k in ("금융", "은행", "보험", "투자", "신용", "증권", "여신")): return "금융법"
    if any(k in name for k in ("공공기관", "공기업", "공단", "공사", "기금")): return "공공기관법"
    return "일반"


def _normalize_article(s):
    """제N조의M → 표준형식. 둘 다 가능."""
    return s.strip().replace(" ", "").replace(" ", "")


def evaluate():
    fid_map = json.loads(FID_MAP_PATH.read_text(encoding='utf-8'))
    verdicts = {}
    with VERDICTS_PATH.open(encoding='utf-8') as f:
        for line in f:
            d = json.loads(line)
            fid = d.get("fid")
            if not fid or "@" not in fid: continue
            _, law_name = fid.split("@", 1)
            verdicts[fid] = {
                "verdict": d["verdict"],
                "rule_id": d["rule_id"],
                "law_name": law_name,
                "evidence": d.get("evidence", ""),
            }

    by_law = defaultdict(list)
    for fid in verdicts:
        by_law[verdicts[fid]["law_name"]].append(fid)

    per_rule = defaultdict(Metrics)
    overall = Metrics()

    for law_name, fids in by_law.items():
        law_dir = LAWS_DIR / law_name
        md = law_dir / "법률.md"
        if not md.exists():
            for fid in fids:
                per_rule[verdicts[fid]["rule_id"]].missing += 1
                overall.missing += 1
            continue
        text = md.read_text(encoding='utf-8', errors='replace')
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3: text = parts[2]
        law = parse_law(text, name=law_name, law_category=_categorize(law_name))
        findings = run_all(law)
        # article-level fired index: (rule_id, normalized_article) → fired
        fired_at_article = set()
        fired_law_level = set()
        for f in findings:
            fired_at_article.add((f.pattern_id, _normalize_article(f.article_number)))
            fired_law_level.add(f.pattern_id)

        for fid in fids:
            info = verdicts[fid]
            rule_id = info["rule_id"]
            verdict = info["verdict"]
            art = fid_map.get(fid)
            m = per_rule[rule_id]

            if art:
                fired = (rule_id, _normalize_article(art)) in fired_at_article
            else:
                # 매핑 없으면 법령-level fallback
                m.unmapped += 1
                fired = rule_id in fired_law_level

            if verdict == "BORDER":
                if fired:
                    m.border_fired += 1; overall.border_fired += 1
                else:
                    m.border_skipped += 1; overall.border_skipped += 1
                continue
            if verdict == "TP":
                if fired:
                    m.tp += 1; overall.tp += 1
                else:
                    m.fn += 1; overall.fn += 1
            elif verdict == "FP":
                if fired:
                    m.fp += 1; overall.fp += 1
                else:
                    m.tn += 1; overall.tn += 1

    return {
        "overall": overall.to_dict(),
        "per_rule": {r: m.to_dict() for r, m in sorted(per_rule.items())},
        "n_verdicts": sum(m.tp + m.fp + m.fn + m.tn for m in per_rule.values()),
    }


def main():
    report = evaluate()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    print(f"\n{'Rule':<8} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5} {'P':>7} {'R':>7} {'F1':>7}  {'unmap':>5}")
    print("-" * 75)
    for rule, m in report["per_rule"].items():
        p = m["precision"] or 0
        r = m["recall"] or 0
        f1 = m["f1"] or 0
        print(f"{rule:<8} {m['tp']:>5} {m['fp']:>5} {m['fn']:>5} {m['tn']:>5} "
              f"{p:>7.3f} {r:>7.3f} {f1:>7.3f}  {m['unmapped']:>5}")
    print("-" * 75)
    o = report["overall"]
    p = o["precision"] or 0
    r = o["recall"] or 0
    f1 = o["f1"] or 0
    print(f"{'TOTAL':<8} {o['tp']:>5} {o['fp']:>5} {o['fn']:>5} {o['tn']:>5} "
          f"{p:>7.3f} {r:>7.3f} {f1:>7.3f}  {o['unmapped']:>5}")
    print(f"\nBORDER fired/skipped: {o['border_fired']}/{o['border_skipped']}")
    print(f"missing 법령: {o['missing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
