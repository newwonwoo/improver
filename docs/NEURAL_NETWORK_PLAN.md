# 뇌신경망 구축 계획 (Neural Network Construction Plan)

> 메타인지적 자가 평가 후 도출된 실현 가능 단계별 진화 로드맵.
> 현재 SLM은 선형 가중합 (퍼셉트론 1층) — 진짜 신경망으로 진화.

## Phase 0: 환경 점검 (✓ 완료)

- Python 3.11, numpy 2.4, scikit-learn 1.8 가용
- CPU 4-core, memory unlimited
- PyTorch 미설치 — Phase 3에서 도입 검토

## Phase 1: sklearn LogisticRegression (1차 학습 도입)

### 목적
현재 hand-tuned weights 를 verdict 데이터에서 직접 학습.
선형 모델이지만 sigmoid 활성화로 확률 출력.

### 실현 방안
- Input X: FeatureVector (~45 dims)
- Label y: 카테고리별 binary (TP=1, FP=0)
- Train/test split: 80/20 stratified
- L2 regularization (C=1.0)
- balanced class_weight (불균형 보정)

### 비교 baseline
현재 hand-tuned weights F1 (Step 75: 0.612) 대비 측정.

### 구현
- `engine/slm/learn.py` — train_logistic_per_category
- `scripts/slm_train_logistic.py` — CLI
- 저장: `outputs/slm_logistic_weights.json` (각 카테고리별 coef + intercept)

## Phase 2: sklearn MLPClassifier (진짜 신경망)

### 목적
**비선형 활성화** + **multi-layer** 도입. 진짜 neural network.

### 아키텍처
```
Input layer:  45 dims (FeatureVector)
Hidden 1:     32 neurons (ReLU)
Hidden 2:     16 neurons (ReLU)
Output:       1 neuron (sigmoid) → 결함 확률
```

### 학습
- Adam optimizer, learning_rate=1e-3
- max_iter=500, early_stopping=True
- 카테고리별 별도 모델
- cross-validation 5-fold

### 검증 (held-out)
- augment verdicts 와 분리된 별도 test set
- 진짜 generalization 측정

### 구현
- `engine/slm/mlp_brain.py` — MLPCategoryBrain (sklearn wrapper)
- `scripts/slm_train_mlp.py`
- 저장: `outputs/slm_mlp_models.pkl` (joblib)

## Phase 3: PyTorch 본격 신경망 (옵션, 환경 허용시)

### 아키텍처
```
[FeatureVector]                # 45 dims
[Embedding for ArticleType]    # 12 → 8 dims
[Embedding for Subject]        # 6 → 4 dims
[Embedding for Modal]          # 5 → 3 dims
Concat → 60 dims
↓ Linear(60, 64) + ReLU + Dropout(0.2)
↓ Linear(64, 32) + ReLU + Dropout(0.2)
↓ Linear(32, 5)                # 5 카테고리 multi-task
↓ Sigmoid                      # 카테고리별 결함 확률
```

### 학습
- BCE loss per category (multi-task)
- AdamW optimizer
- 50 epochs, batch_size=64
- Train: 80%, Val: 10%, Test: 10%

### 구현 (Phase 2 통과시 도입)
- `engine/slm/torch_brain.py`
- `pip install torch` (~700MB)

## Phase 4: 데이터 보강 — 진짜 외부 검증 셋

### 문제
- 현재 verdict 의 augment 는 self-labeled
- 진짜 generalization 검증 불가

### 방안
- legalize-kr 의 외부 corpus 에서 **자동 라벨링 안 한** held-out test set
- Method B 와 분리된 별도 검증 셋
- 또는 LLM API (Claude Anthropic) 로 진짜 외부 검증 (환경 허용시)

## Phase 5: 비선형 신호 도입 (Feature Engineering)

### Interaction features
- `items_max × catchall_strict` (호 수 × 캐치올)
- `disp_strong × has_hearing` (강 처분 × 청문 부재)
- `cited_laws_count × is_disposition` (인용 × 처분)

### Polynomial features (degree=2)
sklearn.preprocessing.PolynomialFeatures 활용.

### Embedding-style (Phase 3)
범주형 신호 (Type, Subject, Modal) 을 dense vector 로 학습.

## 실행 순서 (실현가능성 우선)

1. **즉시 (Phase 1)**: sklearn LogisticRegression 학습
   - 현재 hand-tuned 대비 측정
   - 베이스라인 자동화 달성
2. **다음 (Phase 2)**: sklearn MLPClassifier
   - 비선형 활성화 도입
   - 진짜 multi-layer 신경망
3. **검증 (Phase 4)**: 외부 held-out test set
4. **고도화 (Phase 3)**: PyTorch (필요시)
5. **확장 (Phase 5)**: Interaction features

## 측정 목표 vs 실제 결과 (Step 76 측정)

| Phase | 모델 | 예상 F1 | 실측 F1 | 비고 |
|-------|------|---------|---------|------|
| 0 | hand-tuned ensemble | 0.612 | **0.612** | 현재 |
| 1 | LogReg | ~0.65 | 0.482 | 표본 부족 |
| 1+ | LogReg + Poly | ~0.65 | 0.488 | interaction features |
| 2 | MLP (16,) | ~0.70 | 0.458 | 단층 |
| 2+ | MLP (32,16) | ~0.70 | 0.468 | 다층 |

## 카테고리별 비교 — 비선형성 효과 확인

| 카테고리 | hand-tuned | LogReg+Poly | MLP(16,) | MLP(32,16) |
|---------|-----------|-------------|----------|-----------|
| 구조 | **0.727** | 0.556 | 0.417 | 0.400 |
| 공정성 | **0.751** | 0.583 | 0.435 | 0.400 |
| 적법성 | 0.474 | 0.316 | 0.286 | **0.533** ✓ |
| 거버넌스 | **0.570** | 0.419 | 0.488 | 0.512 |
| 효율성 | 0.569 | 0.500 | **0.588** | 0.533 |

**비선형성 효과 검증**:
- ✓ **적법성**: MLP (32,16) 가 hand-tuned 보다 +0.059 향상 — 비선형성이 실제 도움
- ✓ **효율성**: MLP (16,) 가 hand-tuned 보다 +0.019 향상
- ✗ **구조·공정성·거버넌스**: 표본 부족으로 underfit, hand-tuned 우세

## 다음 단계 결론

**Phase 6: 카테고리별 모델 선택 앙상블**
- 구조·공정성·거버넌스: hand-tuned ensemble 유지
- 적법성·효율성: MLP (32,16) / MLP (16,) 채택

**Phase 7: 표본 부족 극복**
- 데이터 증강 (SMOTE for imbalanced)
- pseudo-labeling (corpus 대규모 self-train)
- 외부 LLM API 검증 (held-out)

**Phase 8: PyTorch 도입 (조건부)**
- 표본 5000+ 확보시
- Embedding layer (categorical → dense)
- Multi-task output (5 카테고리 simultaneous)

## 핵심 인정

진짜 신경망 (MLP) 가 **카테고리에 따라** hand-tuned 보다 좋을 수 있음 확인.
하지만 표본 부족이 본격적 신경망 발전의 근본 제약.

