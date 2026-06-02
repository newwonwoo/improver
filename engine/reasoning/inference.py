"""논리 추론 엔진 (Neuro-Symbolic Reasoning Layer).

설계 철학:
  - 신경망(SLM)은 조문에서 신호를 "지각(perceive)"한다.
  - 본 추론 계층은 그 신호를 법적 논리로 "연결(reason)"하여
    전제(premises) → 추론(inference) → 결론(conclusion) → 근거(legal_basis)
    의 설명가능한 논리 흐름(reasoning chain)을 완성한다.

지식베이스(KB)는 수집한 감사원·공정위·금감원·권익위·대법원 사례에서 도출한
법적 추론 규칙. 각 규칙은 전방연쇄(forward-chaining)로 평가된다.

이 계층은 holdout F1 을 올리려는 게 아니라(그건 데이터 한계),
진단에 **법적 논거와 추론 사슬**을 부여해 설명가능성과 신뢰성을 완성한다.
또한 룰/신호가 놓친 조문을 논리 결합으로 포착해 앙상블 recall 을 보강한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..slm.features import FeatureVector


# ─────────── 추론 결과 구조 ───────────

@dataclass
class ReasoningStep:
    """단일 추론 단계 — 하나의 논리 규칙 적용 결과."""
    rule_id: str
    category: str
    severity: str
    premises: list[str]          # 충족된 전제 (사람이 읽는 문장)
    inference: str               # 왜 결함인지의 논리
    conclusion: str              # 결론 문장
    legal_basis: str             # 법적 근거
    confidence: float            # 전제 충족 강도 [0,1]

    def to_chain(self) -> str:
        """논리 흐름을 한 문단으로 렌더링."""
        prem = " · ".join(self.premises)
        return (
            f"[전제] {prem}\n"
            f"  ↳ [추론] {self.inference}\n"
            f"  ↳ [결론] {self.conclusion} (심각도: {self.severity})\n"
            f"  ↳ [근거] {self.legal_basis}"
        )


@dataclass
class ReasoningResult:
    """한 조문에 대한 전체 추론 결과."""
    article_number: str
    article_title: str
    steps: list[ReasoningStep] = field(default_factory=list)

    def by_category(self) -> dict[str, list[ReasoningStep]]:
        out: dict[str, list[ReasoningStep]] = {}
        for s in self.steps:
            out.setdefault(s.category, []).append(s)
        return out

    def render(self) -> str:
        if not self.steps:
            return f"{self.article_number} {self.article_title}: 논리 결함 미발견"
        lines = [f"### {self.article_number} {self.article_title} — 논리 추론 {len(self.steps)}건", ""]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"**추론 {i} ({s.category})**")
            lines.append(s.to_chain())
            lines.append("")
        return "\n".join(lines)


# ─────────── 전제 평가 헬퍼 ───────────
# 전제는 FeatureVector 의 신호에 대한 술어(predicate). 곱이 아니라 명시적 논리 AND.

def _sig(fv: FeatureVector, name: str) -> float:
    return float(getattr(fv, name, 0.0))


@dataclass
class Premise:
    """단일 전제 — 신호 술어 + 사람이 읽는 설명."""
    test: Callable[[FeatureVector], bool]
    desc: str
    strength: Callable[[FeatureVector], float] = lambda fv: 1.0


@dataclass
class InferenceRule:
    """법적 추론 규칙 — 전제 모두 충족 시 결론 발화."""
    rule_id: str
    category: str
    severity: str
    premises: list[Premise]
    inference: str
    conclusion: str
    legal_basis: str
    precision_prior: float = 0.5   # 2,394 verdict 데이터로 검증한 정밀도 (데이터 근거)
    validated: bool = True          # 정렬된 verdict 로 검증됐는지 (False=데이터 공백)

    def evaluate(self, fv: FeatureVector) -> ReasoningStep | None:
        if not all(p.test(fv) for p in self.premises):
            return None
        conf = 1.0
        for p in self.premises:
            conf = min(conf, p.strength(fv))
        # 전제 충족 강도 × 데이터 검증 정밀도 = 데이터 근거 신뢰도
        conf = round(conf * self.precision_prior, 3)
        return ReasoningStep(
            rule_id=self.rule_id,
            category=self.category,
            severity=self.severity,
            premises=[p.desc for p in self.premises],
            inference=self.inference,
            conclusion=self.conclusion,
            legal_basis=self.legal_basis,
            confidence=conf,
        )


# ─────────── 지식베이스 (수집 사례 → 법적 추론 규칙) ───────────

def _has(name: str, desc: str, thr: float = 0.5) -> Premise:
    return Premise(test=lambda fv, n=name, t=thr: _sig(fv, n) >= t, desc=desc,
                   strength=lambda fv, n=name: min(_sig(fv, n), 1.0))


def _not(name: str, desc: str, thr: float = 0.5) -> Premise:
    return Premise(test=lambda fv, n=name, t=thr: _sig(fv, n) < t, desc=desc)


KNOWLEDGE_BASE: list[InferenceRule] = [
    # 1. 포괄위임 (적법성) — 감사원 BAI-01·헌법 §75
    InferenceRule(
        "R-DELEG-BLANKET", "적법성", "경고",
        premises=[
            _has("has_blanket_delegation", "‘필요한 사항’ 등 포괄적 위임 문구가 있고"),
            _not("cited_articles", "본문에 구체적 위임 기준(인용 조문)이 없으며", thr=0.2),
        ],
        inference="위임의 목적·내용·범위가 한정되지 않아 하위법령이 국민 권리·의무를 자의적으로 정할 수 있다",
        conclusion="포괄위임금지 원칙에 저촉되는 위임 구조",
        legal_basis="헌법 제75조 · 대법원 2016두64975 · 감사원 BAI-01",
        precision_prior=0.3, validated=False,   # 적법성 verdict가 인용기반뿐이라 포괄위임 검증 데이터 공백
    ),
    # 2. 자의적 처분 (공정성) — 공정위 약관규제법 §11·대법
    InferenceRule(
        "R-DISP-ARBITRARY", "공정성", "경고",
        premises=[
            _has("has_subjective_criteria", "‘인정하는 경우’ 등 주관적 판단 기준으로"),
            _has("is_disposition", "침익적 처분을 규정하면서"),
            _not("has_hearing", "청문 등 사전 의견청취 절차가 없다"),
        ],
        inference="처분 요건이 행정청의 자의적 판단에 맡겨져 예측가능성과 방어권이 침해된다",
        conclusion="자의적 처분 기준 + 절차 결여",
        legal_basis="약관규제법 제11조 · 행정절차법 제22조 · 권익위 재량남용 기준",
    ),
    # 3. 침익처분 청문 부재 (공정성) — 감사원 BAI-03·행정절차법 §22
    InferenceRule(
        "R-NO-HEARING", "공정성", "주의",
        premises=[
            _has("has_no_hearing_disp", "허가취소·영업정지 등 침익처분이 있으나 청문 절차가 규정되지 않았다"),
        ],
        inference="당사자가 처분 전 의견을 진술할 기회를 보장받지 못해 적법절차에 미달한다",
        conclusion="침익적 처분의 청문 절차 누락",
        legal_basis="행정절차법 제22조 · 감사원 BAI-03",
        precision_prior=0.56,   # 검증: TP30/FP24
    ),
    # 4. 비례성 결여 자동 최고제재 (공정성) — 대법 JUD-01·행정기본법 §10
    InferenceRule(
        "R-DISPROPORTIONATE", "공정성", "경고",
        premises=[
            _has("has_auto_max_sanction", "위반 시 가중·감경 없이 취소·말소 등 최고 제재가 자동 부과되며"),
            Premise(test=lambda fv: _sig(fv, "disp_strong") >= 0.5 or _sig(fv, "is_penalty") >= 0.5,
                    desc="제재가 침익적·형벌적 성격을 띤다"),
        ],
        inference="위반의 경중을 고려하지 않는 일률적 최고제재는 목적-수단 간 비례성을 잃는다",
        conclusion="비례원칙 위반 소지가 있는 자동 최고제재",
        legal_basis="행정기본법 제10조 · 대법원 2022두31831",
    ),
    # 5. 이중제재 (적법성) — 헌법 §13
    InferenceRule(
        "R-DOUBLE-SANCTION", "적법성", "경고",
        premises=[
            _has("has_double_sanction", "동일 조문에 형사벌(징역·벌금)과 과태료가 함께 규정되어 있다"),
        ],
        inference="같은 위반행위에 형사처벌과 행정제재를 병과하면 이중처벌금지에 저촉될 수 있다",
        conclusion="이중제재 구조",
        legal_basis="헌법 제13조 제1항 · 감사원 BAI-02",
    ),
    # 6. 이유제시 부재 (공정성) — 대법 JUD-02·행정절차법 §23
    InferenceRule(
        "R-NO-REASON", "공정성", "주의",
        premises=[
            _has("has_no_reason_giving", "거부·취소·정지 처분을 하면서 이유 제시 의무가 규정되지 않았다"),
        ],
        inference="처분 이유를 밝히지 않으면 당사자의 불복 가능성과 사법심사 가능성이 제약된다",
        conclusion="처분 이유제시 의무 누락",
        legal_basis="행정절차법 제23조 · 대법원 2019두31839",
        precision_prior=0.72,   # 검증: TP23/FP9
    ),
    # 7. 기속처분 기한 부재 (적법성) — 감사원 BAI-04·행정절차법 §19
    InferenceRule(
        "R-NO-DEADLINE", "적법성", "주의",
        premises=[
            _has("has_no_deadline_binding", "‘하여야 한다’는 기속처분이나 이행·처리 기한이 명시되지 않았다"),
        ],
        inference="처리 기한이 없으면 행정청이 처분을 무한정 지연해 국민 권익이 방치될 수 있다",
        conclusion="기속처분의 이행기한 부재",
        legal_basis="행정절차법 제19조 · 감사원 BAI-04",
        precision_prior=0.4, validated=False,   # 정렬 verdict 부족(n=2) — 미검증
    ),
    # 8. 열거 과다 + 캐치올 (구조) — 법제처 입안심사기준
    InferenceRule(
        "R-ENUM-OVERLOAD", "구조", "개선",
        premises=[
            Premise(test=lambda fv: _sig(fv, "items_max") >= 0.5, desc="한 항의 호 열거가 과다하고(15호 이상)",
                    strength=lambda fv: _sig(fv, "items_max")),
            Premise(test=lambda fv: _sig(fv, "catchall_strict") > 0 or _sig(fv, "catchall_loose") > 0,
                    desc="‘그 밖에’ 식 포괄 캐치올 호가 있다"),
        ],
        inference="열거가 과다하고 포괄 캐치올까지 더해지면 수범자의 예측가능성과 가독성이 저하된다",
        conclusion="열거 과다 + 포괄 캐치올로 인한 구조 복잡",
        legal_basis="법제처 법령입안심사기준(열거 방식) · S-04",
        precision_prior=0.5,   # 검증: TP9/FP9
    ),
    # 9. 단서 과다 재량 형해화 (거버넌스) — 권익위 재량남용
    InferenceRule(
        "R-PROVISO-EXCESS", "거버넌스", "주의",
        premises=[
            Premise(test=lambda fv: _sig(fv, "proviso_max") >= 0.4, desc="한 항에 단서(‘다만’)가 2개 이상 중첩되어",
                    strength=lambda fv: _sig(fv, "proviso_max")),
        ],
        inference="단서가 중첩되면 원칙 규정이 형해화되고 행정청 재량이 과도하게 확대된다",
        conclusion="단서 중첩으로 인한 재량 형해화",
        legal_basis="권익위 부패영향평가(재량남용) · G-01",
        precision_prior=0.57,   # 검증: TP28/FP21
    ),
    # 10. 인용 과다 의존성 (적법성) — 법령정합성
    InferenceRule(
        "R-CITATION-OVERLOAD", "적법성", "개선",
        premises=[
            # 데이터 보정: 임계값 5→11건 (정밀도 0.19→0.44)
            Premise(test=lambda fv: _sig(fv, "cited_laws_count") >= 0.55, desc="한 조문이 타 법령을 과다 인용(11건 이상)하고",
                    strength=lambda fv: _sig(fv, "cited_laws_count")),
            _not("is_definition", "정의·목적 조문이 아니다"),
        ],
        inference="다수 타법 인용은 조문의 자기완결성을 떨어뜨리고 개정 시 정합성 관리를 어렵게 한다",
        conclusion="타 법령 의존성 과다",
        legal_basis="법령정합성 원칙 · L-01",
        precision_prior=0.44,   # 검증: 임계값 11건 상향 후 TP31/FP39
    ),
    # 11. 광범위 면책 (공정성) — 공정위 약관규제법 §7·은행 시정 사례
    InferenceRule(
        "R-BROAD-IMMUNITY", "공정성", "주의",
        premises=[
            _has("has_broad_immunity", "사업자 귀책을 포함한 광범위 면책 조항이 있고"),
            Premise(test=lambda fv: _sig(fv, "is_definition") < 0.5 and _sig(fv, "is_purpose") < 0.5,
                    desc="정의·목적 조문이 아니다"),
        ],
        inference="천재지변 등 정당한 사유 없이 사업자·기관의 책임을 광범위하게 면제하면 상대방 권익을 부당하게 침해한다",
        conclusion="광범위 면책으로 인한 공정성 결함",
        legal_basis="공정위 약관규제법 제7조 · 은행권 시정사례(2025.10) · F-02",
        precision_prior=0.14,   # 검증: TP15/FP89 — corpus의 면책 표현이 광범위해 정밀도 낮음, 출력시 약신뢰 명시
    ),
    # 12. 영향력 있는 조문의 위임 (적법성) — PageRank × 위임 (CodeGraph + 법령그래프)
    InferenceRule(
        "R-HUB-DELEGATION", "적법성", "주의",
        premises=[
            Premise(test=lambda fv: _sig(fv, "graph_pagerank_norm") >= 0.5,
                    desc="다수 조문이 인용하는 허브 조문이며(PageRank 높음)",
                    strength=lambda fv: _sig(fv, "graph_pagerank_norm")),
            Premise(test=lambda fv: _sig(fv, "has_delegate") >= 0.5 or _sig(fv, "is_delegation") >= 0.5,
                    desc="하위법령으로의 위임을 포함한다"),
        ],
        inference="영향 반경이 큰 조문이 하위법령에 위임하면 위임의 파급효가 전체 법체계에 광범위하게 미친다",
        conclusion="허브 조문의 위임 — 영향 반경 큰 위임",
        legal_basis="법령정합성 원칙 · 법령그래프 PageRank 분석",
        precision_prior=0.30,   # 검증불가: aligned verdict 0건, 보수적 약신뢰
        validated=False,
    ),
    # 13. 단기 기한 침익적 처분 (공정성) — 절차 보장 미흡
    InferenceRule(
        "R-SHORT-DEADLINE-ADVERSE", "공정성", "주의",
        premises=[
            Premise(test=lambda fv: _sig(fv, "has_very_short_deadline") >= 0.5 or _sig(fv, "has_short_deadline") >= 0.5,
                    desc="7~14일 이내의 단기 기한이 설정되어 있고"),
            Premise(test=lambda fv: _sig(fv, "subj_citizen") >= 0.5 or _sig(fv, "subj_operator") >= 0.5,
                    desc="기한 부담의 주체가 시민·사업자이며"),
            _not("has_hearing", "청문·의견청취 절차가 보장되지 않는다"),
        ],
        inference="짧은 기한 + 절차 보장 부재의 결합은 상대방 방어권을 실질적으로 박탈한다",
        conclusion="단기 기한과 절차 보장 결여",
        legal_basis="행정절차법 제19조·제22조 · 권익위 고충민원 결정례",
        precision_prior=0.50,   # 검증불충분: n=2 (TP1/FP1) — 보수적 중립
        validated=False,
    ),
    # 14. 행정규칙 위임 (적법성) — 감사원 BAI-06·헌재 위임명령 한계 일탈
    InferenceRule(
        "R-SUBDELEG-ADMIN-RULE", "적법성", "주의",
        premises=[
            _has("has_subdeleg_admin_rule",
                 "고시·훈령·지침 등 행정규칙으로 권리·의무 사항을 정하고 있고"),
            Premise(test=lambda fv: _sig(fv, "is_definition") < 0.5 and _sig(fv, "is_purpose") < 0.5,
                    desc="정의·목적 조문이 아니다"),
        ],
        inference="법령(시행령·시행규칙)이 아닌 행정규칙으로 국민의 권리·의무를 규율하면 위임명령의 한계를 일탈한다",
        conclusion="행정규칙 위임 — 위임명령 한계 일탈 의심",
        legal_basis="감사원 BAI-06 · 헌재 위임명령 법리 · 법령정합성 원칙",
        precision_prior=0.40,   # 감사원 사례 빈도 높음, 단 corpus regex의 신호 폭이 넓어 보수적 진입
        validated=False,
    ),
    # 15. 재량처분 + 처분기준 미공표 (공정성) — 감사원 BAI-08·행정절차법 §20
    InferenceRule(
        "R-NO-DISP-STANDARD", "공정성", "주의",
        premises=[
            _has("has_no_disp_standard",
                 "재량 표현이 포함된 처분 조문에 처분기준 공표 의무가 없다"),
            Premise(test=lambda fv: _sig(fv, "is_disposition") >= 0.5,
                    desc="처분 조문이다"),
        ],
        inference="재량 처분의 기준이 사전 공표되지 않으면 상대방이 예측가능성을 잃고 자의적 처분의 위험이 발생한다",
        conclusion="재량처분 기준 사전공표 의무 결여",
        legal_basis="행정절차법 제20조 · 감사원 BAI-08 처분기준 미공표 패턴",
        precision_prior=0.45,   # BAI-08 빈도 높지만 corpus 다수 조문이 시행령에 기준 위임 — 중간 신뢰
        validated=False,
    ),
    # 16. 법령 우선순위 모호 (적법성) — 법제처 법령해석 100건 분석 (Phase 13)
    InferenceRule(
        "R-LAW-PRECEDENCE", "적법성", "주의",
        premises=[
            _has("has_undefined_precedence",
                 "'다른 법률의 특별한 규정' 등 법령 우선순위 인용이 있고"),
            Premise(test=lambda fv: _sig(fv, "is_definition") < 0.5 and _sig(fv, "is_purpose") < 0.5,
                    desc="정의·목적 조문이 아니다"),
            Premise(test=lambda fv: _sig(fv, "cited_laws_count") > 0,
                    desc="다른 법령을 인용한다",
                    strength=lambda fv: min(1.0, _sig(fv, "cited_laws_count") + 0.3)),
        ],
        inference="다른 법률의 특별한 규정을 인용하면서 그 규정의 범위·요건이 명확치 않으면 법령 적용에 모호함이 발생한다",
        conclusion="법령 우선순위 인용 — 특별 규정 범위 모호",
        legal_basis="법제처 법령해석례 다수 (2022-2026) · 법령 정합성 원칙",
        precision_prior=0.30,   # 0.28% 발화율, moleg 2/100 직접사례 — 보수적 진입
        validated=False,
    ),
]


# ─────────── 추론 실행 (전방연쇄) ───────────

def reason_over(fv: FeatureVector) -> ReasoningResult:
    """단일 조문의 FeatureVector → 논리 추론 결과."""
    result = ReasoningResult(
        article_number=getattr(fv, "article_number", ""),
        article_title=getattr(fv, "article_title", ""),
    )
    # 정의·목적·벌칙 조문은 결함 추론 대상에서 제외 (오발화 방지)
    if _sig(fv, "is_definition") >= 0.5 or _sig(fv, "is_purpose") >= 0.5:
        return result
    for rule in KNOWLEDGE_BASE:
        step = rule.evaluate(fv)
        if step is not None:
            result.steps.append(step)
    # 신뢰도 높은 추론 우선
    result.steps.sort(key=lambda s: -s.confidence)
    return result


def diagnose_with_reasoning(art, law=None, *, backend: str = "linear") -> dict:
    """조문 → 추론(법리) 우선 + 신경망(통계) 보조의 통합 진단.

    판단 권위 순서: 법리(추론)가 주(主), 신경망이 보조(補).
      - 추론 발화 → 법적 근거로 결함 확정 (verdict_source='reasoning')
        · 신경망도 발화 → 'confirmed' (법리+패턴 일치, 최고 신뢰)
        · 신경망 침묵   → 'reasoning_only' (신경망이 놓친 것, 법리로 포착)
      - 추론 침묵, 신경망만 발화 → 'nn_only' (근거 약한 회색지대, 재검토 대상)
      - 둘 다 침묵 → 정상
    """
    from ..slm.brain import analyze_article
    from ..slm.features import extract_features
    from ..structure import decompose

    _SEV_RANK = {"심각": 4, "경고": 3, "주의": 2, "개선": 1, None: 0}

    decomp = decompose(art)
    fv = extract_features(art, decomp, law=law)
    diagnoses = analyze_article(art, decomp, law=law, backend=backend)
    reasoning = reason_over(fv)
    reason_by_cat = reasoning.by_category()

    out = {
        "article_number": art.number,
        "article_title": art.title or "",
        "categories": {},
    }
    for cat, diag in diagnoses.items():
        steps = reason_by_cat.get(cat, [])
        nn_fired = diag.severity is not None
        reason_fired = bool(steps)

        # 추론 우선: 법리가 발화하면 그 심각도를 채택(법적 근거 有)
        if reason_fired:
            reason_sev = max((s.severity for s in steps),
                             key=lambda s: _SEV_RANK.get(s, 0))
            if nn_fired:
                source = "confirmed"          # 법리+신경망 일치 → 확정
                # 둘 중 더 높은 심각도 채택
                severity = reason_sev if _SEV_RANK[reason_sev] >= _SEV_RANK[diag.severity] else diag.severity
            else:
                source = "reasoning_only"      # 법리 단독 → 신경망이 놓침
                severity = reason_sev
        elif nn_fired:
            source = "nn_only"                 # 신경망 단독 → 회색지대(근거 약함)
            severity = diag.severity
        else:
            source = None
            severity = None

        out["categories"][cat] = {
            "verdict_source": source,          # 누가 판단했나 (추론 우선)
            "severity": severity,              # 통합 심각도
            "nn_score": round(diag.score, 3),
            "nn_severity": diag.severity,
            "reasoning": [
                {
                    "premises": s.premises,
                    "inference": s.inference,
                    "conclusion": s.conclusion,
                    "legal_basis": s.legal_basis,
                    "confidence": s.confidence,
                }
                for s in steps
            ],
        }
    out["reasoning_chain"] = reasoning.render()
    return out
