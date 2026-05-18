"""LLM 판단 응답을 다수 모아 룰·임계치·FP 필터를 튜닝하기 위한 학습 모듈.

엔진 강화의 핵심 — LLM(GPT/Gemini)이 다수 법령에 대해 내린 판단을
패턴/서브체크 단위로 집계하여:

1. **FP 비율** 추정 — 어느 패턴이 과탐인지, FP가 어떤 조문 유형에서 자주 나오는지
2. **등급 분포 시프트** — LLM이 룰 등급을 평균적으로 얼마나 조정했는지
3. **권고안 개선 사례** — LLM이 다시 쓴 권고안 모음 → 템플릿 갱신용
4. **새 패턴 후보** (X-NEW) — LLM이 제안한 새 룰
5. **임계치 조정 제안** — patterns.json의 thresholds 갱신 권고

워크플로:
    1. analyze_batch_sets.py → 1,720개 judgment MD
    2. (수동) 각 MD를 GPT/Gemini에 입력 → JSON 응답 받아 outputs/llm_responses/<법령명>.json 저장
    3. learner.aggregate(outputs/results/, outputs/llm_responses/) → tuning_proposals.json
    4. 사람이 검토 후 config/patterns.json, recommendations.json 수동 갱신
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_VALID_VERDICTS = {"TP", "FP", "BORDER"}
_SEVERITY_TO_NUM = {"양호": 0, "개선": 1, "주의": 2, "경고": 3, "심각": 4}
_NUM_TO_SEVERITY = {v: k for k, v in _SEVERITY_TO_NUM.items()}


@dataclass
class PatternStats:
    pattern_id: str
    total_candidates: int = 0
    tp: int = 0
    fp: int = 0
    border: int = 0
    severity_deltas: list[int] = field(default_factory=list)
    fp_reasons: Counter = field(default_factory=Counter)
    improved_recommendations: list[dict] = field(default_factory=list)

    @property
    def fp_rate(self) -> float:
        if not self.total_candidates:
            return 0.0
        return round(self.fp / self.total_candidates, 3)

    @property
    def tp_rate(self) -> float:
        if not self.total_candidates:
            return 0.0
        return round(self.tp / self.total_candidates, 3)

    @property
    def avg_severity_delta(self) -> float:
        if not self.severity_deltas:
            return 0.0
        return round(sum(self.severity_deltas) / len(self.severity_deltas), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "total_candidates": self.total_candidates,
            "tp": self.tp,
            "fp": self.fp,
            "border": self.border,
            "tp_rate": self.tp_rate,
            "fp_rate": self.fp_rate,
            "avg_severity_delta": self.avg_severity_delta,  # 음수=하향, 양수=상향
            "fp_top_reasons": self.fp_reasons.most_common(5),
            "sample_improved_recs": self.improved_recommendations[:3],
        }


def _load_json_dir(path: Path, suffix: str = ".json") -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for p in path.glob(f"*{suffix}"):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def aggregate(
    *,
    results_dir: Path,
    llm_responses_dir: Path,
) -> dict[str, Any]:
    """결과 + LLM 응답을 합쳐 패턴별 통계 + 튜닝 제안 산출."""
    results = _load_json_dir(results_dir)
    responses = _load_json_dir(llm_responses_dir)
    if not responses:
        return {"error": "LLM 응답이 없습니다.", "expected_dir": str(llm_responses_dir)}

    stats: dict[str, PatternStats] = defaultdict(lambda: PatternStats(pattern_id=""))
    missed_patterns: Counter = Counter()
    new_pattern_proposals: list[dict] = []
    overall_grade_opinions: Counter = Counter()
    agree_with_engine = Counter()
    laws_processed = 0
    checklist_freq: Counter = Counter()

    for law_name, response in responses.items():
        if law_name not in results:
            continue
        result = results[law_name]
        findings_by_id = {f["finding_id"]: f for f in result.get("findings", [])}
        laws_processed += 1

        for j in response.get("judgments", []):
            fid = j.get("finding_id")
            f = findings_by_id.get(fid)
            if not f:
                continue
            pid = f["pattern_id"]
            ps = stats.setdefault(pid, PatternStats(pattern_id=pid))
            ps.total_candidates += 1

            verdict = j.get("verdict")
            if verdict == "TP":
                ps.tp += 1
            elif verdict == "FP":
                ps.fp += 1
                reason = (j.get("reasoning") or "")[:80]
                if reason:
                    ps.fp_reasons[reason] += 1
            elif verdict == "BORDER":
                ps.border += 1

            old_sev = f.get("severity")
            new_sev = j.get("adjusted_severity")
            if old_sev in _SEVERITY_TO_NUM and new_sev in _SEVERITY_TO_NUM:
                delta = _SEVERITY_TO_NUM[new_sev] - _SEVERITY_TO_NUM[old_sev]
                ps.severity_deltas.append(delta)

            improved = j.get("improved_recommendation")
            if improved and verdict == "TP":
                ps.improved_recommendations.append({
                    "law": law_name,
                    "article": f.get("article_number"),
                    "severity": new_sev or old_sev,
                    "original_template": (f.get("recommendation") or {}).get("template"),
                    "improved": improved,
                })

        for m in response.get("missed_findings", []):
            pid = m.get("pattern_id", "X-NEW")
            if pid == "X-NEW":
                new_pattern_proposals.append({
                    "law": law_name,
                    "name": m.get("name"),
                    "article": m.get("article_number"),
                    "summary": m.get("summary"),
                })
            else:
                missed_patterns[pid] += 1

        oa = response.get("overall_assessment") or {}
        opinion = oa.get("law_grade_opinion")
        if opinion:
            engine_grade = result.get("law_grade")
            overall_grade_opinions[f"{engine_grade}→{opinion}"] += 1
            agree_with_engine[bool(oa.get("agree_with_engine"))] += 1

        for item in response.get("checklist", []) or []:
            # 30자 미만 + 자주 등장하는 권고는 표준 체크리스트로 승격 후보
            key = item.strip()[:80]
            if key:
                checklist_freq[key] += 1

    # 튜닝 제안 생성
    threshold_proposals: list[dict] = []
    fp_filter_proposals: list[dict] = []
    for pid, ps in sorted(stats.items()):
        if ps.fp_rate >= 0.4 and ps.total_candidates >= 10:
            fp_filter_proposals.append({
                "pattern_id": pid,
                "fp_rate": ps.fp_rate,
                "n": ps.total_candidates,
                "action": "FP 필터 강화 — 임계치 상향 또는 키워드 조건 추가",
                "top_reasons": ps.fp_reasons.most_common(3),
            })
        if abs(ps.avg_severity_delta) >= 0.6 and ps.total_candidates >= 10:
            direction = "하향" if ps.avg_severity_delta < 0 else "상향"
            threshold_proposals.append({
                "pattern_id": pid,
                "avg_delta": ps.avg_severity_delta,
                "n": ps.total_candidates,
                "action": f"등급 기준 {direction} (LLM이 일관되게 {direction} 평가)",
            })

    return {
        "laws_processed": laws_processed,
        "per_pattern_stats": {pid: ps.to_dict() for pid, ps in sorted(stats.items())},
        "missed_patterns_top": missed_patterns.most_common(20),
        "new_pattern_proposals": new_pattern_proposals[:30],
        "fp_filter_proposals": fp_filter_proposals,
        "threshold_proposals": threshold_proposals,
        "grade_opinion_distribution": dict(overall_grade_opinions.most_common(20)),
        "agree_with_engine": dict(agree_with_engine),
        "frequent_checklist_items": checklist_freq.most_common(30),
    }
