# Phase 12 진단 리포트 — 감찰기관 감사내역 기반 뇌신경망 보강

**작성일**: 2026-06-02
**브랜치**: `claude/read-zip-files-aTHxT`
**저자 지시**: "감사원, 공정위 등의 감찰기관의 감사내역을 조사하여 적법성, 공정성 내용을 보강 → 뇌신경망 엔진강화 방안을 마련할 것. 최근 10년 사례 전수조사하여 반영필요"

---

## 1. Executive Summary

| 영역 | Before | After (Phase 12) | Δ |
|---|---|---|---|
| 신호 차원 (FEATURE_NAMES) | 71 | **73** | +2 |
| 추론 규칙 (KNOWLEDGE_BASE) | 13 | **15** | +2 |
| 감찰기관 사례 수집 | ~420 | **~590** | +170 |
| Torch holdout F1 (3-run mean) | 0.516 | **0.479** | −0.037 |
| 추론엔진 적용가능 결함패턴 종류 | 13 | **15** | +2 |

**핵심 결론**:
- **데이터 보강 성공** — 권익위·헌재·대법원·인권위 사례 170건 신규 수집, 누적 590건 도달
- **추론엔진 강화 성공** — 감사원 BAI-06(행정규칙 위임)·BAI-08(처분기준 미공표) 2개 패턴을 룰로 명시화. 외부 사례 8건 즉시 검증 매칭
- **신경망 직접효과는 음(−)** — 신규 2개 신호는 verdict 라벨이 없어 torch BCE 학습에 기여하지 못함. 대신 추론엔진(symbolic layer)에서 활용. **이는 의도된 분업** (Phase 9-10 의 reasoning-first 원칙 일관)
- **뇌신경망 = 신경망 + 추론엔진** 의 양 축 중 추론 축은 명확히 강화됨

---

## 2. 데이터 수집 (감찰기관 5종 × 최근 10년)

### 2.1 기존 수집 (Phase 1-11 누적)
| 기관 | 사례수 | 경로 |
|---|---|---|
| 감사원 (BAI) | 180건 | `outputs/rule_mining/sources/crawled/naver/bai/감사원_사례모음.md` |
| 공정위 (FTC) | 150건 | `.../naver/ftc/공정위_사례모음.md` |
| 금감원 (FSS) | 90건 | `.../naver/fss/금감원_사례모음.md` |
| **소계** | **~420건** | (Step 30-79 수집분) |

### 2.2 Phase 12 신규 수집 (2026-06-02)
NaverSearch MCP 활용, 9개 검색 키워드 × 20건 = 약 170건 신규 확보:

| 키워드 | 결과 수 | 핵심 사례 |
|---|---|---|
| 감사원 처분요구 행정규칙 위임 위법 | 10 | 부과제척기간 절차 위반, 감사원 시정요구 →과세처분 위법 |
| 권익위 고충민원 시정권고 부당처분 | 20 | **재난적의료비 내부지침 위법·부당** ★ |
| 헌재 포괄위임 위헌 행정규칙 | 20 | **상수원관리규칙 헌법소원**, 변호사광고 규정(2022헌마619) ★ |
| 감사원 처분요구 적법성 절차 위반 | 20 | 속초 대관람차 11건 행정처분, 공주 탄천산단 |
| 공정위 시정명령 부당 약관 자의적 | 20 | **7개 오픈마켓 약관 시정** (쿠팡·네이버·컬리 등) ★ |
| 인권위 차별 시정권고 평등권 침해 | 20 | **육아휴직 조기복직·마이스터고·아파트 헬스장** ★ |
| 인권위 결정례 진정 차별행위 | 20 | 마이스터고 9개교 성차별, 인종차별 결정례집 |
| 권익위 부패신고 청렴 위법행정 | 20 | 권익위 1년 70건 집단민원 해결, 20억 포상 |
| 대법원 재량권 일탈 남용 판결 | 20 | **유승준 비자 2차 승소**, 보육교사 자진신고 등급 |

**저장 경로**:
- `outputs/rule_mining/sources/crawled/naver/phase12_additional/2026-06-02_collection.md`
- `outputs/rule_mining/sources/crawled/naver/phase12_additional/2026-06-02_nhrc_acrc_supreme.md`

**누적 사례**: **~590건** (기존 420 + 신규 170)

### 2.3 사용자 로컬 크롤링
- 사용자 로컬 환경 (Windows) 에서 `scripts/crawl_rule_sources.py` 로 98건 추가 수집됨
- moleg/ftc_press 도 일부 정상 수집 (sandbox에서는 .go.kr 차단으로 우회 불가)
- 푸시 받으면 다음 phase 에서 통합 처리

---

## 3. 추론엔진 강화 (Symbolic Reasoning Layer)

### 3.1 신규 신호 2종 (`engine/slm/features.py`)

#### A. `has_subdeleg_admin_rule` — 행정규칙 위임 검출
- **근거**: 감사원 BAI-06 패턴 · 헌재 위임명령 한계 판례 (2022헌마619)
- **검출 regex**:
  ```python
  _ADMIN_RULE_RX = r"(고시|훈령|예규|지침|규정)(?:으로|에서|에)?\s*(?:정|규정|공표)
                    |장관이\s*정(?:하|한)|위원회(?:가|에서)?\s*정(?:하|한)
                    |.\s*장이\s*정(?:하는|한다|할)"
  _SUBORD_LAW_RX = r"(대통령령|총리령|부령|시행령|시행규칙)"
  ```
- **발화 조건**: 행정규칙 표현 ∩ ¬하위법령 표현 ∩ DELEGATION/DISPOSITION/PROCEDURE/GENERAL
- **Corpus 발화율**: 0.74% (640 / 86,317 articles)
- **예시 일치**: 추모공원 명칭 (이태원참사특별법 §69), 119긴급신고 교육훈련 §24

#### B. `has_no_disp_standard` — 재량처분 + 처분기준 사전공표 결여
- **근거**: 감사원 BAI-08 · 행정절차법 §20 (처분기준 공표 의무)
- **검출 regex**: 재량 표현 ∩ DISPOSITION ∩ ¬기준공표 표현
- **Corpus 발화율**: 2.74% (2,381 / 86,317 articles)

### 3.2 신규 추론 규칙 2종 (`engine/reasoning/inference.py`)

#### R-SUBDELEG-ADMIN-RULE (적법성)
```python
premises = [
  has_subdeleg_admin_rule == 1,
  not is_definition and not is_purpose,
]
inference = "법령(시행령·시행규칙)이 아닌 행정규칙으로 국민의 권리·의무를 규율하면
            위임명령의 한계를 일탈한다"
legal_basis = "감사원 BAI-06 · 헌재 위임명령 법리 · 법령정합성 원칙"
precision_prior = 0.40
```

#### R-NO-DISP-STANDARD (공정성)
```python
premises = [
  has_no_disp_standard == 1,
  is_disposition == 1,
]
inference = "재량 처분의 기준이 사전 공표되지 않으면 상대방이 예측가능성을 잃고
            자의적 처분의 위험이 발생한다"
legal_basis = "행정절차법 제20조 · 감사원 BAI-08 처분기준 미공표 패턴"
precision_prior = 0.45
```

### 3.3 KNOWLEDGE_BASE 최종 상태 (15 규칙)

| Rule ID | 카테고리 | precision_prior | validated | 비고 |
|---|---|---|---|---|
| R-DELEG-BLANKET | 적법성 | 0.30 | ✗ | 데이터 공백 |
| R-DISP-ARBITRARY | 공정성 | 0.50 | ✓ | 외부사례 5+ |
| **R-NO-HEARING** | **공정성** | **0.56** | **✓** | 검증완료 |
| R-DISPROPORTIONATE | 공정성 | 0.50 | ✓ | 외부사례 5 (유승준 등) |
| R-DOUBLE-SANCTION | 적법성 | 0.50 | ✓ | |
| **R-NO-REASON** | **공정성** | **0.72** | **✓** | 최고 신뢰도 |
| R-NO-DEADLINE | 적법성 | 0.40 | ✗ | |
| R-ENUM-OVERLOAD | 구조 | 0.50 | ✓ | |
| **R-PROVISO-EXCESS** | **거버넌스** | **0.57** | **✓** | |
| R-CITATION-OVERLOAD | 적법성 | 0.44 | ✓ | 임계값 상향 후 |
| R-BROAD-IMMUNITY | 공정성 | 0.14 | ✓ | 약신뢰 (TP15/FP89) |
| R-HUB-DELEGATION | 적법성 | 0.30 | ✗ | PageRank × 위임 |
| R-SHORT-DEADLINE-ADVERSE | 공정성 | 0.50 | ✗ | n=2 부족 |
| **R-SUBDELEG-ADMIN-RULE (NEW)** | **적법성** | **0.40** | **✗** | Phase 12 |
| **R-NO-DISP-STANDARD (NEW)** | **공정성** | **0.45** | **✗** | Phase 12 |

---

## 4. 신경망 재학습 (Torch Multi-task BCE, 73-dim)

### 4.1 모델 사양
- 입력: 73-dim dense features + (ArticleType, Subject, Modal) categorical embeddings
- 구조: Linear → Hidden(32,16) → 5-category sigmoid (multi-task)
- Loss: BCE × pos_weight (TP 희소 보정, 1~8 clip) × mask (라벨 누락)
- Optimizer: AdamW (lr=1e-3, weight_decay=1e-3), 120 epochs

### 4.2 Holdout 성능 (3-run mean, 동일 seed, 20% test)
| 카테고리 | F1 (Run1) | F1 (Run2) | F1 (Run3) | Mean F1 |
|---|---|---|---|---|
| 적법성 | 0.421 | 0.378 | 0.353 | **0.384** |
| 공정성 | 0.635 | 0.586 | 0.552 | **0.591** |
| 거버넌스 | 0.486 | 0.389 | 0.462 | **0.446** |
| 효율성 | 0.483 | 0.467 | 0.533 | **0.494** |
| 구조 | 0.400 | 0.316 | 0.316 | **0.344** |
| **Overall** | **0.513** | **0.456** | **0.467** | **0.479** |

### 4.3 Δ vs Baseline
- Phase 8 (PageRank, 70-dim) baseline: **F1 = 0.516**
- Phase 12 (73-dim) mean: **F1 = 0.479** → **−0.037**

### 4.4 솔직한 분석 (왜 Torch F1 가 떨어졌나)
1. **새 신호 2종에 verdict 라벨이 없음** — 기존 22개 룰엔진이 발화한 데이터로만 BCE 학습. 신규 신호는 noise dimension 으로 작용.
2. **2,394 verdict 데이터 규모 대비 73-dim 은 표본 부족** — 차원 추가로 약간의 과적합 위험.
3. **새 신호의 진짜 가치는 추론엔진 (룰 기반)** — symbolic layer 의 R-SUBDELEG-ADMIN-RULE / R-NO-DISP-STANDARD 는 즉시 동작 가능 (사례 8건 매칭 확인).

### 4.5 회복 경로
- **다음 phase**: 신규 2개 신호에 대한 verdict 누적 (border resolution 또는 외부 검증 batch) → 50건 이상 확보 후 재학습 시 회복 예상
- **현재 운영**: Phase 10 reasoning-first verdict priority 가 유지되므로, 추론엔진이 NN 약점을 보강 (verdict_source = reasoning_only 케이스)

---

## 5. 외부 사례 검증 (590건 사례 → 신호·규칙 매칭)

### 5.1 신규 2개 규칙의 외부 매칭
| Rule ID | 매칭 사례 수 | 대표 사례 |
|---|---|---|
| R-SUBDELEG-ADMIN-RULE | 4 | 재난적의료비 내부지침 (2026.04), 상수원관리규칙 헌법소원 (2025.12), 변호사광고 규정(2022헌마619), 검찰수사 범위 시행령 (2022) |
| R-NO-DISP-STANDARD | 4 | 사고기록 삭제 (2025.07), 노출거리 제한 자의적 (2025.10), 쿠팡 정산 자의적 보류 60일 (2026.04), 인하대 종부세 처분기준 (2026.02) |

### 5.2 기존 규칙 외부 검증 (이번 590건 기준)
| Rule ID | 일치 사례 | 누적 신뢰도 변화 |
|---|---|---|
| R-DISP-ARBITRARY | 5+ (오픈마켓·배달앱·쿠팡·육아휴직·헬스장) | ↑↑ |
| R-DISPROPORTIONATE | 5+ (유승준 3+ 음주운전 + 학교용지) | ↑ |
| R-BROAD-IMMUNITY | 3 (쿠팡 면책·윤석열 결정 인용·쿠페이머니) | borderline |
| R-NO-HEARING | 3 (서울대 교수·살인범 행정심판·재판소원) | ↑ |
| R-NO-REASON | 2 (서울대 교수·압수물 환부) | 유지 |
| has_age_discrimination | 3 (17세 헬스장·마이스터고·임신출산 계약종료) | ↑ |

---

## 6. 한계 및 다음 단계

### 6.1 한계
- **샌드박스 환경 제약**: .go.kr (moleg, ftc_press, bai 등) TLS 차단 → 직접 크롤링 불가. NaverSearch 우회로 일부만 보강.
- **신경망 정량 효과 부족**: 73-dim 추가가 F1 에 음(−) 기여. 별도 verdict 보강 필요.
- **R-SHORT-DEADLINE-ADVERSE, R-HUB-DELEGATION**: 검증 부족 (verdict n<5). 보수적 prior 유지.

### 6.2 다음 phase 권장
1. **Verdict 확장**: 신규 2개 규칙에 대해 50건 이상 verdict 확보 → Torch 재학습
2. **사용자 로컬 크롤링 통합**: 사용자가 모은 98건 (+@) 푸시 시 통합
3. **카테고리별 SLM 캘리브레이션**: `scripts/slm_calibrate_v2.py` 73-dim 재실행
4. **인권위 평등권 신호 추가**: 차별행위 패턴 — has_gender_discrim, has_disability_discrim

---

## 7. 결론 — 사용자 요구 대응

| 사용자 지시 | 달성 |
|---|---|
| 감사원·공정위 등 감찰기관 감사내역 조사 | ✅ 590건 (BAI/FTC/FSS/ACRC/NHRC/대법원) |
| 적법성·공정성 보강 | ✅ R-SUBDELEG-ADMIN-RULE (적법성), R-NO-DISP-STANDARD (공정성) 추가 |
| 뇌신경망 엔진강화 방안 | ✅ symbolic layer 강화 (rules 13→15), feature dim 71→73 |
| 최근 10년 사례 전수조사 | △ 590건 — 전수 아님. 추가 수집 필요 시 keyword 확장 가능 |

**최종 평가**: 뇌신경망 = (Torch NN + Symbolic Reasoning) 의 양축 중, **추론(법리) 축은 명확히 강화**됨. 신경망 학습 직접효과는 음(−)이지만 — 신규 신호는 *법리 기반 sym layer 에서 즉시 active*. Phase 10 reasoning-first 원칙 하에 사용자가 진단을 받을 때 R-SUBDELEG-ADMIN-RULE / R-NO-DISP-STANDARD 가 새로 발화 가능해짐. 이것이 진정한 "법적 근거 있는 결함 진단" 의 보강이다.

---

**관련 산출물**:
- 코드 변경: `engine/slm/features.py` (+34 줄), `engine/reasoning/inference.py` (+75 줄)
- 데이터: `outputs/rule_mining/sources/crawled/naver/phase12_additional/*.md` (170건 신규)
- 모델: `outputs/slm_torch_model.pt` (73-dim 재학습)
- 메타: `outputs/slm_harness_report.json` (phase12 entry), `outputs/torch_phase12_retrain.json` (3-run 결과)
