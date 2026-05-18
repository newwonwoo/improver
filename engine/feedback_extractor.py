"""LLM 응답에서 엔진 자산(사례 DB + 권고 템플릿)을 자동 추출.

P1 — 컨텐츠 강화 핵심:
- extract_case_candidates(): LLM이 인용한 사례·기관 근거를 disciplinary_cases.json
  형식으로 변환. 인간 검토 후 confirm 단계에서 진짜 사례 DB에 병합.
- extract_template_candidates(): 같은 (pattern, severity)에 LLM이 일관되게 제안한
  improved_recommendation 을 모아 클러스터링 → recommendations.json 후보 템플릿.

설계 원칙:
- 자동 추가는 안 함. "후보(candidate)" 파일로만 출력 → 사람 검토 후 적용.
- 출처 추적: 어느 법령 + 어느 finding에서 나왔는지 메타 유지.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── 사례 추출 ────────────────────────────────────────────────────


_AGENCY_PATTERNS = [
    (re.compile(r"감사원\s*\d{4}"), "감사원"),
    (re.compile(r"금감원|금융감독원"), "금감원"),
    (re.compile(r"공정위|공정거래위원회"), "공정위"),
    (re.compile(r"권익위|국민권익위원회"), "권익위"),
    (re.compile(r"법제처"), "법제처"),
    (re.compile(r"인권위|국가인권위원회"), "인권위"),
    (re.compile(r"국토교통부|국토부"), "국토교통부"),
    (re.compile(r"보건복지부"), "보건복지부"),
    (re.compile(r"고용노동부|노동부"), "고용노동부"),
]
_DATE_PAT = re.compile(r"(20\d{2})[.\-\s]+(0?[1-9]|1[0-2])(?:[.\-\s]+(0?[1-9]|[12]\d|3[01]))?")
_URL_PAT = re.compile(r"https?://[^\s)>]+")
_LAW_REF_PAT = re.compile(r"「([^」]+)」\s*(?:제\d+조(?:의\d+)?(?:\s*제\d+항)?)?")


@dataclass
class CaseCandidate:
    case_id: str           # 자동 생성 (해시 기반)
    agency: str
    date: str | None
    summary: str
    law_reference: str | None
    agency_basis: str | None
    url: str | None
    related_patterns: list[str]
    related_sub_checks: list[str]
    source_law: str        # 어느 법령 분석에서 추출됐는지
    source_finding_id: str
    occurrences: int = 1   # 같은 사례 중복 카운트


def _detect_agency(text: str) -> str | None:
    for pat, agency in _AGENCY_PATTERNS:
        if pat.search(text):
            return agency
    return None


def _detect_date(text: str) -> str | None:
    m = _DATE_PAT.search(text)
    if not m:
        return None
    y, mth, d = m.group(1), m.group(2), m.group(3)
    return f"{y}-{int(mth):02d}" + (f"-{int(d):02d}" if d else "")


def _case_hash(agency: str, date: str | None, summary: str) -> str:
    key = f"{agency}|{date or ''}|{summary[:50]}".encode("utf-8")
    return hashlib.sha1(key).hexdigest()[:10]


def extract_case_candidates(
    *, results_dir: Path, llm_dir: Path,
) -> dict[str, CaseCandidate]:
    """LLM 응답의 judgments[].reference, missed_findings[].reference 에서 사례 후보 추출.

    같은 사례(agency+date+요약 유사)는 occurrences 카운트만 ↑.
    """
    candidates: dict[str, CaseCandidate] = {}

    for resp_path in llm_dir.glob("*.json"):
        if resp_path.name.startswith("_"):
            continue
        try:
            resp = json.loads(resp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        law_name = resp_path.stem.split("__", 1)[0]
        result_path = results_dir / f"{law_name}.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        findings_by_id = {f["finding_id"]: f for f in result.get("findings", [])}
        sources = list(resp.get("judgments", [])) + list(resp.get("missed_findings", []))

        for src in sources:
            ref = (src.get("reference") or "").strip()
            reasoning = (src.get("reasoning") or "").strip()
            text = " ".join(filter(None, [ref, reasoning]))
            if not text:
                continue
            agency = _detect_agency(text)
            if agency is None:
                continue
            date = _detect_date(text)
            url_m = _URL_PAT.search(text)
            url = url_m.group(0) if url_m else None
            law_ref_m = _LAW_REF_PAT.search(text)
            law_ref = law_ref_m.group(0) if law_ref_m else None

            fid = src.get("finding_id", "")
            f = findings_by_id.get(fid, {})
            pattern_id = f.get("pattern_id") or src.get("pattern_id", "")
            sub = (f.get("recommendation") or {}).get("sub_check_id")
            summary = (src.get("improved_recommendation")
                       or src.get("summary") or text)[:200]

            ch = _case_hash(agency, date, summary)
            if ch in candidates:
                candidates[ch].occurrences += 1
                if pattern_id and pattern_id not in candidates[ch].related_patterns:
                    candidates[ch].related_patterns.append(pattern_id)
                if sub and sub not in candidates[ch].related_sub_checks:
                    candidates[ch].related_sub_checks.append(sub)
                continue
            candidates[ch] = CaseCandidate(
                case_id=f"LLM-{ch}",
                agency=agency,
                date=date,
                summary=summary,
                law_reference=law_ref,
                agency_basis=ref if ref else None,
                url=url,
                related_patterns=[pattern_id] if pattern_id else [],
                related_sub_checks=[sub] if sub else [],
                source_law=law_name,
                source_finding_id=fid,
            )
    return candidates


# ── 권고 템플릿 추출 ─────────────────────────────────────────────


@dataclass
class TemplateCandidate:
    pattern_id: str
    severity: str
    occurrences: int = 0
    samples: list[dict] = field(default_factory=list)
    # 클러스터 대표 문장 (가장 많이 등장한 형태 또는 평균)
    suggested_template: str | None = None
    diverges_from_current: bool = False
    current_template: str | None = None


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _ngram_similarity(a: str, b: str, n: int = 4) -> float:
    """간단한 n-gram Jaccard 유사도."""
    def grams(s: str) -> set[str]:
        s = re.sub(r"\s+", "", s)
        return {s[i: i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


def extract_template_candidates(
    *,
    results_dir: Path,
    llm_dir: Path,
    current_templates: dict[str, dict[str, str]] | None = None,
    min_occurrences: int = 2,
    divergence_threshold: float = 0.4,
) -> dict[str, TemplateCandidate]:
    """LLM이 일관되게 다시 쓴 권고안을 (pattern, severity)별로 클러스터링.

    min_occurrences 이상 등장 + 현재 템플릿과 ngram 유사도 < divergence_threshold
    인 경우 → 후보 템플릿으로 승격.
    """
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for resp_path in llm_dir.glob("*.json"):
        if resp_path.name.startswith("_"):
            continue
        try:
            resp = json.loads(resp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        law_name = resp_path.stem.split("__", 1)[0]
        result_path = results_dir / f"{law_name}.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        findings_by_id = {f["finding_id"]: f for f in result.get("findings", [])}

        for j in resp.get("judgments", []):
            if j.get("verdict") != "TP":
                continue
            improved = (j.get("improved_recommendation") or "").strip()
            if not improved or len(improved) < 20:
                continue
            fid = j.get("finding_id")
            f = findings_by_id.get(fid)
            if not f:
                continue
            pattern_id = f["pattern_id"]
            severity = j.get("adjusted_severity") or f.get("severity")
            if not severity:
                continue
            by_key[(pattern_id, severity)].append({
                "law": law_name,
                "article": f.get("article_number"),
                "improved": _normalize_text(improved),
                "original_template": (f.get("recommendation") or {}).get("template"),
            })

    out: dict[str, TemplateCandidate] = {}
    current_templates = current_templates or {}
    for (pid, sev), items in by_key.items():
        if len(items) < min_occurrences:
            continue
        # 가장 자주 등장하는 패턴(텍스트 클러스터 대표) — 평균 길이 + ngram 군집 중 가장 큼
        texts = [it["improved"] for it in items]
        # 클러스터링: greedy
        clusters: list[tuple[str, int, list[int]]] = []  # (rep, count, indices)
        for i, t in enumerate(texts):
            placed = False
            for ci, (rep, _cnt, idxs) in enumerate(clusters):
                if _ngram_similarity(rep, t) >= 0.5:
                    clusters[ci] = (rep, _cnt + 1, idxs + [i])
                    placed = True
                    break
            if not placed:
                clusters.append((t, 1, [i]))
        clusters.sort(key=lambda x: -x[1])
        suggested = clusters[0][0] if clusters else None
        current = current_templates.get(pid, {}).get(sev)
        sim = _ngram_similarity(current or "", suggested or "")
        diverges = sim < divergence_threshold if current else True

        key = f"{pid}/{sev}"
        out[key] = TemplateCandidate(
            pattern_id=pid,
            severity=sev,
            occurrences=len(items),
            samples=items[:5],
            suggested_template=suggested,
            diverges_from_current=diverges,
            current_template=current,
        )
    return out


# ── 외부 진입점 ──────────────────────────────────────────────────


def export_proposals(
    *,
    results_dir: Path,
    llm_dir: Path,
    current_recommendations_path: Path | None = None,
    output_dir: Path,
) -> dict[str, Any]:
    """사례 후보 + 템플릿 후보를 한 번에 추출해 디렉토리에 저장."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = extract_case_candidates(results_dir=results_dir, llm_dir=llm_dir)
    cases_payload = {
        "doc": "LLM 응답에서 자동 추출된 사례 후보. 사람 검토 후 config/disciplinary_cases.json 에 병합.",
        "candidates": [
            {
                "case_id": c.case_id,
                "agency": c.agency,
                "date": c.date,
                "summary": c.summary,
                "law_reference": c.law_reference,
                "agency_basis": c.agency_basis,
                "url": c.url,
                "related_patterns": c.related_patterns,
                "related_sub_checks": c.related_sub_checks,
                "source_law": c.source_law,
                "source_finding_id": c.source_finding_id,
                "occurrences": c.occurrences,
            }
            for c in sorted(cases.values(), key=lambda x: -x.occurrences)
        ],
    }
    (output_dir / "case_candidates.json").write_text(
        json.dumps(cases_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    current = None
    if current_recommendations_path and current_recommendations_path.exists():
        try:
            current = json.loads(current_recommendations_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = None

    templates = extract_template_candidates(
        results_dir=results_dir, llm_dir=llm_dir,
        current_templates=current,
    )
    templates_payload = {
        "doc": "LLM 응답에서 자동 추출된 권고 템플릿 후보. 사람 검토 후 config/recommendations.json 에 반영.",
        "candidates": [
            {
                "pattern_id": t.pattern_id,
                "severity": t.severity,
                "occurrences": t.occurrences,
                "diverges_from_current": t.diverges_from_current,
                "current_template": t.current_template,
                "suggested_template": t.suggested_template,
                "samples": t.samples,
            }
            for t in sorted(templates.values(),
                            key=lambda x: (-int(x.diverges_from_current),
                                            -x.occurrences))
        ],
    }
    (output_dir / "template_candidates.json").write_text(
        json.dumps(templates_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "cases": len(cases),
        "templates": len(templates),
        "diverging_templates": sum(1 for t in templates.values()
                                    if t.diverges_from_current),
    }
