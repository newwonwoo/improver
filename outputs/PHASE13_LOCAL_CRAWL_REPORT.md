# Phase 13 — 사용자 로컬 크롤링 98건 처리 리포트

**작성일**: 2026-06-02
**입력**: 사용자 로컬 크롤링 (moleg_interp 90건 + ftc_press 8건 = 98건, 기존 + 추가)
**현재 누적 (집계 시)**: moleg 100건, ftc_press 14건

---

## 1. 자동 분류 결과

### moleg_interp 100건 — 법령해석 사례 → **추론엔진** 우선

| 패턴 | 발견 건수 | 비율 | 관련 룰 |
|---|---|---|---|
| **clarity_required** (명확성·구체성·예측가능성) | 100 | 100% | R-DISP-ARBITRARY, R-NO-DISP-STANDARD |
| **legislative_intent** (입법 취지 해석) | 59 | 59% | 일반 추론 보강 |
| **application_exclusion** (적용 배제) | 47 | 47% | 법령 정합성 |
| **law_harmony** (법령 상호 조화) | 10 | 10% | 법령 우선순위 |
| **procedural_protection** (절차 보장) | 6 | 6% | R-NO-HEARING |
| **law_precedence** ("다른 법률의 특별한 규정") | 2 | 2% | 신규 후보 |
| **admin_rule_delegation** (행정규칙 위임) | 1 | 1% | R-SUBDELEG-ADMIN-RULE ✓ |

**관찰**:
- `clarity_required` 100/100 (=100%) — 모든 법령해석이 명확성을 다룸 → **신호로는 무용** (변별력 0). 그러나 R-NO-DISP-STANDARD 의 *법리적 정당성* 은 확실
- `application_exclusion` 47% — 풍부한 패턴. 법령 정합성 추론에 활용 가능
- `admin_rule_delegation` 1건만 매칭 — Phase 12 R-SUBDELEG-ADMIN-RULE 의 *실세계 매칭 1건 확보*

### ftc_press 14건 — 공정위 보도자료 → 카테고리 라벨

| 카테고리 | 건수 | 매핑 룰 |
|---|---|---|
| 하도급 부당특약 | 4 | R-DISP-ARBITRARY (공정성) |
| 표시광고 | 2 | (공정성) |
| 제재 (과징금) | 2 | (적법성) |
| 담합 | 1 | (적법성) |
| 기타 | 5 | — |

**한계**: ftc_press .md 는 HTML 헤더 + 첨부파일(.hwp) 링크만 포함. 본문은 .hwp 안에 있어 **자동 추출 불가**. 제목 기반 카테고리만 활용.

---

## 2. corpus 매칭 (verdict 후보)

- **59개 법령**이 우리 corpus(1,745개 법령)와 일치 (예: 노인복지법, 지방자치법, 산업안전보건법, 환경영향평가법 등)
- **127개 verdict 후보** 생성 (각 moleg 해석례 × 인용 corpus 법령)

저장: `outputs/phase13_verdict_candidates.jsonl`

### 활용 시나리오
- **단순 활용**: 127개 후보를 LLM/사람이 review → TP/FP 라벨 부여 → verification_dataset.jsonl 확장 → torch 재학습
- **현재 한계**: 해석례 ≠ TP/FP 판정. 해석례는 "조문 X 가 조문 Y 의 적용배제 사유에 해당하는가" 같은 **법령간 관계 해석**이라, 우리 룰엔진 (조문 단위 결함 진단)에 직접 매핑되지 않음

---

## 3. 양 엔진 강화 효과 평가

### A. 추론엔진(symbolic) — 보강 효과 ★★
1. R-NO-DISP-STANDARD 법리 검증: 100/100 = 모든 법령해석이 명확성을 다툼
2. R-SUBDELEG-ADMIN-RULE 실 사례 1건 매칭 (행정규칙 위임)
3. R-NO-HEARING 실 사례 6건 매칭 (절차 보장)
4. **신규 후보 패턴**: `law_precedence` (다른 법률의 특별한 규정), `application_exclusion` — 법령 정합성 추론 영역, 추후 R-LAW-PRECEDENCE 로 코딩 가능

### B. 신경망(neural) — 직접 보강 효과 ☆ (라벨 부재)
- 127개 verdict 후보 형태로 저장됨
- 그러나 TP/FP 라벨이 없어 torch BCE 학습엔 즉시 활용 불가
- 라벨링 작업(LLM batch 또는 수동) 후 재학습 가능

### C. 종합 효과
| 항목 | 효과 |
|---|---|
| 추론엔진 법리 검증 강화 | ✅ 100/100 명확성, 59/100 입법취지 |
| 신규 룰 후보 발굴 | 1-2개 (R-LAW-PRECEDENCE, R-APP-EXCLUSION 검토) |
| Torch 즉시 재학습 데이터 | ❌ (라벨 없음 — 후속 작업 필요) |
| 사례 다양성 (1,745 법령 매칭) | 59개 법령 cross-link 확보 |

---

## 4. 솔직한 한계

1. **moleg 해석례 ≠ verdict** — 우리는 "조문 X 는 적법성 결함인가" 를 학습하지만, moleg 는 "조문 X 의 의미는 무엇인가" 를 답함. 직접 라벨 변환 어려움.
2. **ftc_press 본문 부재** — .hwp 첨부에 있어서 .md만으로는 제목 분류만 가능
3. **`clarity_required` 100% 발화율** — 신호로는 변별력 0. 법리 정당성 확인 외 활용 제한
4. **127건 verdict 후보** — 후속 라벨링 작업 필요. 즉시 NN 재학습 불가

---

## 5. 권장 후속 작업 (우선순위)

1. **★★★ R-LAW-PRECEDENCE 신규 룰 검토**
   - 패턴: 두 법령이 동일 사항 규율 시 우선순위 모호
   - 발화 신호: cited_laws_count ≥ 2 + 특별한 규정 표현 부재
   - moleg 2/100 사례에서 직접 학습

2. **★★ moleg-corpus 매핑 활용**
   - 59개 법령에 대해 우리 진단엔진 실행 → moleg 해석과 충돌 시 추론 hint
   - 예: 노인복지법 §X 분석 결과 vs moleg 해석례 cross-check

3. **★ ftc_press 첨부 보강 (수동)**
   - 14건 제목 인덱스만 있음. 사용자가 .hwp 본문 텍스트 별도 추출 시 추론엔진 강화 가능

4. **수동 verdict 라벨링** — 127건 후보 중 50건만 라벨링해도 NN 재학습 가능

---

## 6. 사용자 질문 답변 (재정리)

> "신경망이랑 추론엔진을 어떤방식으로 강화하는건지 이해가 잘 안되네"

| 강화 방식 | 추론엔진 | 신경망 |
|---|---|---|
| **입력 데이터** | 사례/판례 markdown | verdict 라벨 (TP/FP) |
| **강화 방법** | 사람이 신호+규칙 코딩 | gradient descent 자동 학습 |
| **즉시 동작** | ✅ | ❌ (라벨 부재 시) |
| **이번 98건 효과** | 패턴 검증 + 1-2 신규 룰 후보 | 127 verdict 후보 (라벨 대기) |

> "어떤자료는 신경망 강화에 반영하고 어떤건 추론엔진 강화하고 이런 분류기준이 있나"

**자동 분류 기준** (이번 phase13 적용):
1. 사례 모음/판례 markdown → 추론엔진 (패턴 추출 + 룰 코딩)
2. 조문별 TP/FP 라벨 데이터 → 신경망 (BCE 학습)
3. 법령해석례 (moleg) → 양쪽 후보, 라벨링 필요 시 신경망 활용
4. 보도자료 (ftc_press) → 추론엔진 카테고리 인덱싱

---

**산출물**:
- `outputs/phase13_routing.json` — 자동 분류 결과
- `outputs/phase13_verdict_candidates.jsonl` — 127건 verdict 후보
- `scripts/phase13_process_local_crawl.py` — 처리 스크립트 (재실행 가능)
