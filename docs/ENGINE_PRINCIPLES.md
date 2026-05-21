# 엔진 강화 최상위 원칙 (Engine Reinforcement Charter)

> 이 문서는 본 저장소의 모든 룰·점수·필터 변경에 우선합니다.
> 룰 코드와 이 문서가 충돌하면 **문서가 이깁니다.**
> 변경하려면 PR 본문에서 명시적으로 이 문서를 인용·수정해야 합니다.

---

## 0. 메타 원칙

**엔진은 LLM이 "맥락 파악"으로 도달한 판단을, 기계적 신호 조합으로 재현해야 한다.**

- 키워드 매칭은 **베이스라인(level 0)** 이지 목표가 아니다.
- 목표는 **SLM급 (level 3~4)** — 구조 인식 + 역할 식별 + 다중 신호 조합 + 정답지 캘리브레이션.
- "LLM이 머릿속으로 하는 일"을 **명시적 데이터 구조와 룰 합성**으로 재현하면 SLM급이다.

### 등급 표
| Level | 정의 | 예시 |
|---:|---|---|
| 0 | 키워드 매칭 | `"필요하다고 인정" in text` |
| 1 | 키워드 합성 | `A and B and not C` |
| 2 | 위치/순서 인식 | "단서 다음에 호 7개 이상" |
| 3 | **구조화 + 역할** | `actor.role == AGENCY and modal == MAY and action.kind == DISPOSITION` |
| 4 | **다중 신호 가중 합 + 캘리브레이션** | LLM 정답지에서 F1 최대화한 weighted vote |
| 5 | 실제 LLM 추론 | API 호출 |

**현재 상태: 0~1. 목표: 3~4.**

---

## 1. 강제 규칙 (Hard Rules)

### R1. 단일 키워드 발화 금지

모든 finding 생성은 **≥ 2개 독립 신호의 합**이어야 한다.
한 패턴 매칭만으로 `make_finding(...)` 을 호출하는 코드는 **reject**.

#### 위반 예
```python
if _STRONG.search(text):  # 단일 신호만 보고 발화
    return Finding(severity="심각", ...)
```

#### 준수 예
```python
signals = []
if _STRONG.search(text):           signals.append(("strong_prohibition", 0.5))
if subject.role == "CITIZEN":      signals.append(("citizen_subject", 0.3))
if not has_remedy_in_window(art):  signals.append(("no_remedy", 0.4))
if sum(w for _, w in signals) < THRESHOLD:
    return None
```

### R2. 주체-술부 분해 의무

각 조문은 룰 적용 전에 다음 구조로 분해돼야 한다:

```python
Article(
    type: REGULATION | DEFINITION | DELEGATION | PENALTY | COMMITTEE | PROCEDURE | DISPOSITION,
    paragraphs: [
        Paragraph(
            actor:    Span(text="...", role=AGENCY|OPERATOR|CITIZEN|OFFICIAL|UNKNOWN),
            modal:    MUST | MAY | PROHIBITED | DEFINITION | NONE,
            action:   Span(text="...", kind=GRANT|REVOKE|REPORT|REGISTER|...),
            target:   Span | None,
            conditions: [ Condition(kind=ALTERNATIVES|NESTED, items=[...]) ],
            exceptions: [ Span(...) ],
            refs:     [ CrossRef(law=..., article=...) ],
        ),
        ...
    ]
)
```

룰은 raw `art.full_text` 가 아니라 위 구조에 대해 동작한다.
구조 분해기(`engine/structure.py`)가 단일 진입점이다.

### R3. LLM 검증 데이터셋 회귀 의무

`outputs/verification_dataset.jsonl` 의 **2,318 verdicts** 는 엔진의 정답지다.

- 모든 룰 변경은 **F1 (macro)**, **F1 (per-rule)** 두 지표 모두 회귀 없이 통과해야 한다.
- CI 에서 `scripts/engine_harness.py` 가 자동 실행.
- F1 가 마지막 main 대비 -0.5% 이상 떨어지면 PR block.

#### BORDER verdict 처리 정책 (2개 메트릭 병행)

LLM 검증 데이터셋에는 TP/FP 외에 **BORDER** 라벨이 있다 (LLM이 결정 불가).
엔진 평가는 두 가지 정책을 병행 계산한다:

- **Strict F1**: BORDER 무시 (TP/FP만 카운트). 보수적·하한선 지표.
- **Lenient F1**: BORDER fired → TP, BORDER skipped → 무시.
  LLM이 결정 못한 케이스에 엔진의 합리적 발화는 보너스로 인정.

상업 활용 가능 목표는 **Lenient F1 ≥ 0.50** (실사용에서 모호한 케이스에
대한 합리적 추정도 가치).  Strict F1 ≥ 0.50 은 더 엄격한 학술 지표.

### R4. 신호 후보(322개)가 손-짠 regex 보다 우선

`outputs/signal_candidates.json` 에 등록된 LLM 추출 신호는
- 새 룰 작성 전 먼저 확인 의무
- 그대로 옮길 수 있으면 그것을 1차 옵션으로 선택
- 옮기지 않는 이유는 PR 설명에 명시

### R5. rationale + examples 의무

모든 새 신호/룰에는 다음이 코드 주석 또는 docstring 으로 동반돼야 한다:

```python
# Signal: "처분조+재량+다단단서 TP_BOOST"
# Source: signal_candidates.json :: E-01 :: idx 5
# Rationale: 침익적 처분조에서 다층단서+다호 결합은 예측가능성 침해
# Examples (verdicts that justify this):
#   - E-01-036@공동주택관리법 (LLM verdict: TP)
#   - E-01-007@국민체육진흥법 (LLM verdict: TP)
#   - E-01-011@낙동강수계물관리및주민지원등에관한법률 (LLM verdict: TP)
#   - E-01-017@기술의이전및사업화촉진에관한법률 (LLM verdict: TP)
# Counter-examples (verdicts this should NOT fire on):
#   - E-01-001@게임산업진흥에관한법률 (LLM verdict: FP — 정의조문)
def signal_disposition_multi_proviso(art: Article) -> float: ...
```

예시 ≥ 5건, 반례 ≥ 2건 권장.

---

## 2. 작업 파이프라인 (Data → Code → Eval)

```
[LLM 검증 응답]                  outputs/rule_verification_responses/*.json
       │                          (2,318 verdicts, 47/111 번들)
       ▼
[정답지 + 신호 추출]              outputs/verification_dataset.jsonl
       │                          outputs/signal_candidates.json (322 patterns)
       ▼
[구조화 분해기]                   engine/structure.py
       │                          Article(type, paragraphs[Actor, Modal, Action, ...])
       ▼
[룰 = 신호 합성]                  engine/rules/*.py
       │                          fire = weighted_sum(signals) > threshold
       ▼
[하네스 검증]                     scripts/engine_harness.py
       │                          F1 per rule + macro + drift gate
       ▼
[CI 게이트]                       PR block if F1 regresses
```

각 단계는 단방향이고, 상위 단계가 하위 단계의 진실 공급원이다.
**손-짠 regex 가 정답지를 무시하고 들어오면 R3 에서 막힌다.**

---

## 3. 즉시 시행 항목

다음 작업은 본 문서가 머지되는 즉시 착수한다:

1. `scripts/engine_harness.py` 작성
   - verification_dataset.jsonl 로드
   - 현재 엔진을 fixture/실법령에 돌려 finding 생성
   - LLM verdict 와 confusion matrix 산출
   - 룰별 + 전체 F1 표 출력
   - 마지막 baseline 비교 (`outputs/harness_baseline.json`)

2. `engine/structure.py` 작성
   - parse_law 출력의 Article 을 구조화 객체로 변환
   - 우선 type 분류 + actor role 식별만이라도 구현

3. 322 signals 룰 통합 (점진)
   - 가장 효과 큰 패턴부터: TP_BOOST 우선, FP_FILTER 후순위
   - 각 통합마다 harness 회귀 확인

4. 미검증 64 번들 LLM 검증 보충
   - F-01, F-05, S-01~S-03, G-02, G-05, L-02 — 핵심 룰이 미커버
   - bundle → LLM 응답 → import 사이클 완주

---

## 4. 변경 절차

- 이 문서 자체 수정: 별도 PR, 본문에 "최상위 원칙 변경 — 사유" 명기
- 룰 코드 변경: 본 문서 R1~R5 준수 + harness 통과 + verdict examples 동반
- 신호 추가: signal_candidates.json 등록 후 코드 통합

---

## 5. 한 줄 요약

> **너처럼 동작하는 로직을 만들기 위함이다.**
> 단어를 잡지 말고, **구조를 잡고, 역할을 식별하고, 신호를 합산하고, 정답지로 보정하라.**

---

## 6. 뇌신경망 SLM (`engine/slm/`)

룰 엔진과 병행 운영되는 SLM ladder level 4 모듈.

### 6.1 입력층 (`engine/slm/features.py`)
`extract_features(art, decomp)` → `FeatureVector` (~40 차원):
- 범주형: ArticleType (12 one-hot), Subject (6), Modal (5), ActionKind (10 multi-hot)
- 정량: items_max, items_total, catchall_strict/loose, proviso_total/max
- 인용: cited_laws_count, cited_articles, internal_refs
- 처분: disp_strong/mid/weak, has_hearing, has_standard, has_deemed_assent
- 시간: has_short_deadline (<14일), has_very_short_deadline (<7일)

### 6.2 은닉층 (`engine/slm/brain.py`)
카테고리별 신경망 모듈 `CategoryBrain`:
- 5 카테고리 (구조/공정성/적법성/거버넌스/효율성) 독립 가중치
- `forward(fv)` → score [0,1] + severity (심각/경고/주의/개선) + contributing_signals
- 가중치 = 도메인 지식 WEIGHTS + verdict-fitted calibrated_weights 평균

### 6.3 캘리브레이션 (R3)
`scripts/slm_calibrate.py`: verdict 데이터에서 신호별 TP/FP 평균 gap 산출
- `outputs/slm_signal_stats.json`: 카테고리별 신호 통계
- `outputs/slm_weights_calibrated.json`: gap × (1 - fp_mean) 보정 가중치
- 빈출 신호 (fp_mean 高) 자동 감쇄로 잡음 통제

### 6.4 앙상블 (`engine/slm/ensemble.py`)
`ensemble_analyze(law, findings)` → 룰 + SLM 결합 진단:
- source = "rule" | "slm" | "both"
- 카테고리별 SLM 단독 임계값 `_CAT_SLM_THRESHOLD`

### 6.5 사용
```bash
python scripts/slm_analyze.py <법령명>          # 단일 법령 카테고리 진단
python scripts/slm_analyze.py --all              # 전체 corpus 요약
python scripts/slm_harness.py                    # SLM 단독 평가
python scripts/slm_ensemble_harness.py           # 룰+SLM 앙상블 평가
```

### 6.6 평가 (Step 72 기준)
| 카테고리 | SLM 단독 F1 | 앙상블 F1 |
|---------|-----------|-----------|
| 구조 | 0.475 | **0.764** |
| 공정성 | 0.455 | **0.724** |
| 거버넌스 | 0.496 | 0.570 |
| 적법성 | 0.435 | 0.395 |
| 효율성 | 0.366 | 0.360 |
| TOTAL | 0.457 | **0.559** |
