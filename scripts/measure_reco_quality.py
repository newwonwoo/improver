#!/usr/bin/env python3
"""v2 V6 — TP 조문 개선안(권고) 품질 1차 측정 하네스.

검수인이 "정체 해제 판정은 F1이 아닌 개선안 채택률"로 못박았으므로,
처음으로 TP(진짜 결함) 조문의 엔진 개선안 품질을 측정한다.

경로:
    outputs/verification_dataset.jsonl  — verdict==TP 행 (fid, rule_id, evidence)
    outputs/fid_article_map.json        — fid → article_number 매핑
    data/laws/raw/<법령명>/법률.md      — 법령 본문
    engine.rules.run_all → fpc.correct → scorer.compute → recommender.apply
                                         (scripts/analyze.py 와 동일 파이프라인, LLM 제외)

각 TP 조문에서: 매핑된 article 에서 발화한 그 rule_id finding 을 찾아
부착된 Layer1 권고(template)를 추출하고 3축 휴리스틱 채점.

3축 (팀장 정의):
    정확(accuracy)      0/1 — 권고가 그 finding 의 결함유형과 일치하나.
                              = finding.pattern_id 의 템플릿이 실제로 부착됐나
                                (recommendation.template 존재 & pattern_id 일치).
    구체(specificity)   0/2 — 권고가 그 조문 고유 문구/번호를 지칭하나.
                              0=generic, 1=조문참조 OR 인용/수치, 2=둘 다.
    실행가능(actionability) 0/2 — "무엇을 어떻게 고쳐라" 개정지시 형태인가.
                              0=일반훈수, 1=동작동사 있음, 2=동작동사+개정대상.

출력:
    outputs/reco_quality_measure.json
    stdout — 사람용 요약

측정 전용. 프로덕션 무수정. 커밋 금지.
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

VERDICTS_PATH = REPO / "outputs" / "verification_dataset.jsonl"
FID_MAP_PATH = REPO / "outputs" / "fid_article_map.json"
LAWS_DIR = REPO / "data" / "laws" / "raw"
REPORT_PATH = REPO / "outputs" / "reco_quality_measure.json"

# 표본: 카테고리(rule_id 접두) 별 고르게. None=전수.
SAMPLE_PER_RULE = 4   # rule_id 당 최대 표본 → 카테고리 고른 분포로 ~30~50건
RANDOM_SEED = 42

# --- 채점 어휘 (engine/recommend_quality.py 와 동일 계열, 측정용 독립 복제) ---
# 실행 동사 — "무엇을 어떻게 고쳐라"
_ACTION_RX = re.compile(
    r"한정|열거|명시|구체화|삭제|개정|신설|추가|통합|마련|정비|재배정|보완|"
    r"제정|보충|대체|전환|분리|이관|재편|배정|한정|환원|일원화|규정"
)
# 개정 대상 명사 — 동사가 무엇을 향하는지 (실행가능 2점 판정)
_TARGET_RX = re.compile(
    r"조문|조항|시행령|시행규칙|하위법령|단서|호|항|별표|위임|표현|기준|요건|절차|체계"
)
# 구체 참조 — 특정 조·항·호·별표·조문번호 지목
_ARTICLE_REF_RX = re.compile(r"제\s*\d+\s*조|제\s*\d+\s*항|제\s*\d+\s*호|각\s*호|별표|단서")
# 일반론 보일러플레이트
_GENERIC = ("조치 불요", "기회 있을 때", "검토 필요", "검토 바람", "필요시 검토",
            "검토.", "검토 ", "정비 검토")


def _categorize(name: str) -> str:
    if any(k in name for k in ("금융", "은행", "보험", "투자", "신용", "증권", "여신")):
        return "금융법"
    if any(k in name for k in ("공공기관", "공기업", "공단", "공사", "기금")):
        return "공공기관법"
    if any(k in name for k in ("민법", "상법", "계약", "채권", "물권")):
        return "민사법"
    if any(k in name for k in ("소송", "절차", "재판", "심판")):
        return "절차법"
    return "일반"


def _normalize_article(s: str) -> str:
    return (s or "").strip().replace(" ", "").replace(" ", "")


def _strip_frontmatter(text: str) -> str:
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def score_accuracy(finding, rec_text: str) -> int:
    """정확 0/1: 그 finding pattern_id 의 템플릿이 실제로 부착됐나.

    recommender 는 templates[pattern_id][severity] 만 부착하므로, template 텍스트
    존재 자체가 'pattern_id 일치' 를 보장. 빈 권고 / 양호 보일러플레이트는 0.
    """
    if not rec_text or not rec_text.strip():
        return 0
    if rec_text.strip() in ("조치 불요.", "조치 불요"):
        return 0
    return 1


def score_specificity(rec_text: str, article_no: str | None) -> int:
    """구체 0/1/2: 조문 고유 문구/번호 지칭."""
    t = (rec_text or "").strip()
    if not t:
        return 0
    pts = 0
    has_ref = bool(_ARTICLE_REF_RX.search(t)) or (bool(article_no) and article_no in t)
    has_quote_or_num = any(q in t for q in ("'", '"', "“", "「")) or bool(re.search(r"\d", t))
    if has_ref:
        pts += 1
    if has_quote_or_num:
        pts += 1
    return min(2, pts)


def score_actionability(rec_text: str) -> int:
    """실행가능 0/1/2: 개정지시 형태인가."""
    t = (rec_text or "").strip()
    if not t:
        return 0
    if any(g in t for g in ("조치 불요",)):
        return 0
    has_action = bool(_ACTION_RX.search(t))
    has_target = bool(_TARGET_RX.search(t))
    if has_action and has_target:
        return 2
    if has_action:
        return 1
    return 0


def main() -> int:
    fid_map = json.loads(FID_MAP_PATH.read_text(encoding="utf-8"))

    # 1) TP 행 수집
    tp_rows = []
    with VERDICTS_PATH.open(encoding="utf-8") as f:
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
                "fid": fid,
                "rule_id": d["rule_id"],
                "law_name": law_name,
                "evidence": d.get("evidence", ""),
                "article": fid_map.get(fid),
            })

    total_tp = len(tp_rows)

    # 2) 표본: rule_id 별 고르게 (결정론적, seed shuffle 후 head)
    import random
    rng = random.Random(RANDOM_SEED)
    by_rule = defaultdict(list)
    for r in tp_rows:
        by_rule[r["rule_id"]].append(r)
    sample = []
    for rule_id in sorted(by_rule):
        rows = by_rule[rule_id][:]
        rng.shuffle(rows)
        sample.extend(rows[:SAMPLE_PER_RULE])
    sample.sort(key=lambda r: (r["rule_id"], r["law_name"]))

    # 3) 법령별로 묶어 엔진 1회 실행
    by_law = defaultdict(list)
    for r in sample:
        by_law[r["law_name"]].append(r)

    records = []
    skipped = {"missing_law": 0, "fn_not_fired": 0, "unmapped": 0}

    for law_name, rows in by_law.items():
        md = LAWS_DIR / law_name / "법률.md"
        if not md.exists():
            for r in rows:
                skipped["missing_law"] += 1
                records.append({**r, "status": "missing_law", "recommendation": None})
            continue
        text = _strip_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        law = parse_law(text, name=law_name, law_category=_categorize(law_name))
        findings = run_all(law)
        findings = fpc.correct(law, findings)
        result = scorer.compute(law, findings)
        result = recommender.apply(result)  # Layer1 템플릿 부착

        # (pattern_id, normalized_article) → finding
        idx = {}
        for fobj in result.findings:
            idx[(fobj.pattern_id, _normalize_article(fobj.article_number))] = fobj

        for r in rows:
            art = r["article"]
            if not art:
                skipped["unmapped"] += 1
                records.append({**r, "status": "unmapped", "recommendation": None})
                continue
            fobj = idx.get((r["rule_id"], _normalize_article(art)))
            if fobj is None:
                # 엔진이 그 조문에서 발화 안함 (article-level FN). 채점 불가.
                skipped["fn_not_fired"] += 1
                records.append({**r, "status": "fn_not_fired", "recommendation": None})
                continue

            rec = fobj.recommendation or {}
            rec_text = rec.get("template") or ""
            layer = rec.get("layer")
            acc = score_accuracy(fobj, rec_text)
            spec = score_specificity(rec_text, art)
            actn = score_actionability(rec_text)
            records.append({
                **r,
                "status": "scored",
                "severity": fobj.severity,
                "pattern_id": fobj.pattern_id,
                "rec_layer": layer,
                "recommendation": rec_text,
                "accuracy": acc,
                "specificity": spec,
                "actionability": actn,
            })

    scored = [x for x in records if x["status"] == "scored"]

    # 4) 분포 집계
    def dist(key, maxv):
        c = {i: 0 for i in range(maxv + 1)}
        for x in scored:
            c[x[key]] += 1
        return c

    n = len(scored)
    summary = {
        "total_tp_rows": total_tp,
        "sample_size": len(sample),
        "scored": n,
        "skipped": skipped,
        "axes": {
            "accuracy": {
                "dist": dist("accuracy", 1),
                "mean": round(sum(x["accuracy"] for x in scored) / n, 3) if n else None,
                "max": 1,
            },
            "specificity": {
                "dist": dist("specificity", 2),
                "mean": round(sum(x["specificity"] for x in scored) / n, 3) if n else None,
                "pct_specific_ge1": round(sum(1 for x in scored if x["specificity"] >= 1) / n, 3) if n else None,
                "max": 2,
            },
            "actionability": {
                "dist": dist("actionability", 2),
                "mean": round(sum(x["actionability"] for x in scored) / n, 3) if n else None,
                "max": 2,
            },
        },
        "layer_dist": dict(_count(scored, "rec_layer")),
        "per_rule_mean": _per_rule(scored),
    }

    report = {
        "_meta": {
            "purpose": "v2 V6 TP-조문 개선안 품질 1차 측정 (Layer1 템플릿)",
            "pipeline": "run_all -> fpc.correct -> scorer.compute -> recommender.apply",
            "llm": False,
            "sample_per_rule": SAMPLE_PER_RULE,
            "seed": RANDOM_SEED,
            "scoring": {
                "accuracy": "0/1 — finding pattern_id 템플릿 부착 여부",
                "specificity": "0/2 — 조문 참조/인용/수치 지목 (generic vs specific)",
                "actionability": "0/2 — 개정지시(동작동사+개정대상) 형태 여부",
            },
            "caveat": "자동 휴리스틱 채점. 검수인이 요구한 '사람 블라인드 채택률'의 대용(proxy)임.",
        },
        "summary": summary,
        "records": records,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5) stdout 요약
    print(f"\nTP 전체: {total_tp}  표본: {len(sample)}  채점됨: {n}")
    print(f"스킵: {skipped}")
    ax = summary["axes"]
    print(f"\n[3축 분포 / 채점 {n}건]")
    print(f"  정확(0/1)      dist={ax['accuracy']['dist']}  mean={ax['accuracy']['mean']}")
    print(f"  구체(0/2)      dist={ax['specificity']['dist']}  mean={ax['specificity']['mean']}  "
          f"구체율(>=1)={ax['specificity']['pct_specific_ge1']}")
    print(f"  실행가능(0/2)  dist={ax['actionability']['dist']}  mean={ax['actionability']['mean']}")
    print(f"\nLayer 분포: {summary['layer_dist']}")
    print(f"\n[예시 3건]")
    for x in scored[:3]:
        print(f"  - {x['fid']} ({x['article']}, {x.get('severity')})")
        print(f"    권고: {x['recommendation'][:90]}")
        print(f"    정확={x['accuracy']} 구체={x['specificity']} 실행={x['actionability']}")
    print(f"\nWrote {REPORT_PATH}")
    return 0


def _count(rows, key):
    c = defaultdict(int)
    for r in rows:
        c[r.get(key)] += 1
    return c


def _per_rule(scored):
    by = defaultdict(list)
    for x in scored:
        by[x["rule_id"]].append(x)
    out = {}
    for rid, xs in sorted(by.items()):
        k = len(xs)
        out[rid] = {
            "n": k,
            "accuracy": round(sum(x["accuracy"] for x in xs) / k, 2),
            "specificity": round(sum(x["specificity"] for x in xs) / k, 2),
            "actionability": round(sum(x["actionability"] for x in xs) / k, 2),
        }
    return out


if __name__ == "__main__":
    sys.exit(main())
