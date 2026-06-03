# 뇌신경망 SLM 구축 로드맵 — 학습·비선형성·아키텍처

## 0. 현재 상태 진단

### 데이터
- verdict 데이터: **2,127건** (TP 372 / FP 1,755, TP율 17.5%)
- 커버 법령: 946개 (전체 1,745개의 54%)
- 커버 룰: **12개** (실제 룰 28개 중 절반만 verdict 보유)
- L-04/05/06, F-07/08/09, S-01/02/03, E-02~05, G-02/05 verdict 부재

### 모델
- **Linear CategoryBrain**: F1=0.529 (SLM 단독), **F1=0.749 (앙상블 게이팅)**
- **TorchBrain (MLP)**: 61-dim, hidden=(32,16), holdout F1=0.488, 실사용 시 거의 0점 출력 — **underfitted**
- 캘리브레이션 v2 + 도메인 지식 가중치 결합 → 선형 모델로 0.749 달성

### 한계
1. **표본 부족**: 2,127건은 비선형 MLP 학습에 부족 (특히 카테고리당 30~100건 수준)
2. **레이블 편향**: TP율 17.5% → 클래스 불균형
3. **차원 제약**: 61-dim 정량신호만 활용, 텍스트 의미 정보 미활용
4. **조문 독립 가정**: 조문 간 그래프 정보를 신호로만 활용, 메시지 패싱 없음

---

## 1. 실현가능한 학습 방안

### 1A. 데이터 증강 (Data Augmentation) — 즉시 가능

#### 룰 마이닝 응답 → Pseudo-verdict 생성
- 신규 룰 ~57개 추가 시, 각 룰을 corpus 1,745 법령에 적용
- 추정 발화: 룰당 100~500건 → 총 **5,000~28,000 신규 후보**
- 이 중 borderline 케이스 → Phase 6b agentic export 로 Claude 웹 verdict 수집
- 목표: **verdict 5,000~10,000건** (5배 증가)

#### Self-training (반복 학습)
```
1. 현재 SLM + rule engine → 1,745 법령 분석
2. ensemble_score ≥ 0.85 또는 ≤ 0.15 인 케이스만 추출
3. 이를 pseudo-label 로 학습 데이터에 추가
4. 재학습 → 신뢰도 점진 향상
```
- 위험: 잘못된 pseudo-label 누적 (concept drift)
- 완화: 신뢰구간 좁게(0.85~0.15), 매 라운드 holdout 검증

### 1B. 능동학습 (Active Learning) — 비용 효율적

- borderline 케이스 (normalized 0.40~0.60) 만 사용자에게 질의
- 이미 `slm_agentic_export.py --mode verdict` 로 구현됨
- 1회 prompt 당 30 케이스 × 사용자 응답 → verdict 30건 확보
- 10회 라운드 = 300건 추가 (월간 1시간 노력)

### 1C. 사전 학습 임베딩 활용 (Pre-trained)

| 모델 | 비용 | 효과 추정 |
|------|------|---------|
| **TF-IDF + truncated SVD** (50-dim) | 0 (sklearn) | F1 +0.03 |
| **char n-gram (2,3,4)** + dense | 0 | F1 +0.05 |
| **KoBERT/KLUE-BERT** (Frozen) | 1회 임베딩 추출 후 캐시 | F1 +0.08 |
| **KLAW-BERT (법령 도메인)** | 모델 다운로드 + 추출 | F1 +0.10 (불확실) |

→ 단계적: TF-IDF → char n-gram → BERT

### 1D. 카테고리간 전이학습

- 각 카테고리별 binary classifier 가 아닌 **공유 backbone + 카테고리 head**
- 이미 `torch_brain.py` 에 multi-task 구조 있음
- 단, 현재는 카테고리당 라벨 100~300개 수준 → 학습 부족

---

## 2. 비선형성 도입 방안

### 2A. Interaction Features (즉시 효과, 위험 0)

현재 linear: `score = Σ w_i × x_i`
도입: `score = Σ w_i × x_i + Σ w_ij × x_i × x_j`

핵심 상호작용 (도메인 지식 기반):
```python
INTERACTIONS = [
    # 구조: 열거 과다 × 캐치올 → 더 강한 결함
    ("items_max", "catchall_strict"),
    # 적법성: 위임 × 침익적 → 포괄위임 결함
    ("has_delegate", "disp_strong"),
    # 적법성: 인용 다수 × 정의 부재 → 의존성 결함
    ("cited_laws_count", "is_definition"),  # 음의 상호작용
    # 공정성: 자의적 기준 × 처분 → 자의적 처분
    ("has_subjective_criteria", "is_disposition"),
    # 효율성: 조건 중첩 × 분기 다수
    ("condition_lead_norm", "graph_outdegree_norm"),
    # 거버넌스: 위원회 × 이해충돌 신호 부재
    ("is_committee", "is_general"),  # placeholder
]
```

**구현 비용**: 1시간 (sklearn `PolynomialFeatures(degree=2, interaction_only=True)`)
**효과 추정**: F1 +0.02~0.05

### 2B. Shallow MLP (1 hidden layer)

- 현재 MLP 가 underfitted 한 이유는:
  1. hidden 크기가 너무 큼 (32×16 = 32 weights × 16 + 16×5 = 592 params)
  2. 데이터가 2,127건 → 표본:파라미터 = 3.6:1 (열악)

→ **단순화**: hidden=(8,) 로 축소 → 61×8 + 8×5 = 528 params (비슷)
   또는 hidden=(16,) 만 + L2=1e-2

**효과 추정**: 현재 holdout F1=0.488 → 0.52~0.55 (선형과 동급)

### 2C. Tree-based Boosting (선형보다 강력)

- **XGBoost/LightGBM**: 비선형성 + 작은 표본에 강건
- 카테고리당 binary classifier (multi-output gradient boosting)

```python
from xgboost import XGBClassifier
clf = XGBClassifier(
    max_depth=3, n_estimators=100,
    learning_rate=0.1, scale_pos_weight=pos_ratio,
    objective='binary:logistic'
)
```

**효과 추정**: F1 +0.05~0.10 (특히 적법성)
**해석성**: SHAP value 로 기여도 추출 가능

### 2D. Attention-based Aggregation (조문 내 항 단위)

- 현재: 조문 전체 → 1개 feature vector
- 도입: 각 항(paragraph) → feature vector → attention pooling

```python
# 각 paragraph 별 feature
para_features = [extract_features(para) for para in art.paragraphs]
# Attention weights (학습)
attn = softmax(Linear(para_features))
# Weighted sum
art_repr = Σ attn_i × para_features_i
```

**효과 추정**: F1 +0.03~0.05 (특히 다항 조문)

### 2E. Graph Neural Network (조문 간 관계)

이미 Phase 4 그래프 빌드됨 (84K 노드, 113K 엣지).

- GCN/GAT: 노드 = 조문, 엣지 = 인용/내부참조
- 메시지 패싱: 이웃 조문 정보를 본 조문 표현에 통합
- 특히 적법성에서 효과적 (인용 패턴이 핵심)

**비용**: PyTorch Geometric 설치 (CPU 가능)
**효과 추정**: 적법성 F1 +0.05~0.10

---

## 3. 뇌신경망 (Brain NN) 아키텍처 계획

### 단계적 진화 — 4 Phase

```
Phase A (즉시): Linear + Interactions    ← 우리 위치
                ↓
Phase B (1-2주): Char n-gram + MLP
                ↓
Phase C (1개월): GNN (graph-aware multi-task)
                ↓
Phase D (3개월): KoBERT fine-tuning + Hierarchical attention
```

### Phase A: Polynomial Brain (현 baseline + 비선형 보강)

```python
class PolynomialBrain:
    """Linear CategoryBrain + 도메인 상호작용 항 추가."""
    
    def __init__(self, cat):
        self.linear_weights = WEIGHTS[cat]          # 도메인 가중치
        self.interaction_weights = INTERACTIONS[cat] # 학습된 상호작용
        self.bias = 0.0
    
    def forward(self, fv):
        score = self.bias
        # Linear term
        for sig, w in self.linear_weights.items():
            score += w * fv[sig]
        # Interaction term
        for (sig1, sig2), w in self.interaction_weights.items():
            score += w * fv[sig1] * fv[sig2]
        return sigmoid(score)
```

**학습**: LogisticRegression with PolynomialFeatures(2, interaction_only=True)
**예상 F1**: 0.749 → 0.78 (앙상블)

### Phase B: Hybrid Text-Quant Brain

```
Input:
  - Quantitative features (61-dim)
  - Article text → TF-IDF (300-dim) or char n-gram (500-dim)
  
Architecture:
  text_emb = TfidfVectorizer(ngram_range=(2,4), analyzer='char', max_features=500)
  quant = StandardScaler(fv)
  combined = concat(text_emb, quant)  # 561-dim
  
  hidden = ReLU(Linear(561, 64))
  dropout = Dropout(0.3)
  category_logits = [Linear(64, 1) for _ in 5_categories]  # multi-head
  score = sigmoid(category_logits)
```

**예상 F1**: 0.78 → 0.82 (텍스트 의미정보 추가)

### Phase C: Graph-aware Multi-task Brain

```
1. 조문별 base representation (Phase B 출력)
2. 그래프 위에서 메시지 패싱 (GAT):
   h_v^{l+1} = Attention(h_v^l, {h_u^l : u ∈ N(v)})
3. 카테고리별 head:
   score_cat = MLP(h_v^final)
```

**효과 추정**: 적법성 +0.05, 거버넌스 +0.03 (인용·위임 관계 활용)
**예상 F1**: 0.82 → 0.85

### Phase D: KoBERT + Hierarchical Attention

```
Article text → KoBERT (frozen or fine-tuned) → [CLS] embedding (768-dim)
Article structure → paragraph-level encoding
                  → attention pooling over paragraphs
Combined: BERT + struct + quant → final classifier

5 카테고리 heads (multi-task)
```

**예상 F1**: 0.85 → 0.88+ (단, 작은 데이터셋 한계로 BERT fine-tuning 효과는 제한적)

---

## 4. 우선순위 실행 계획

### 즉시 (이번주)
1. **Polynomial Brain (Phase A)** — 1시간 작업
   - sklearn `PolynomialFeatures(2, interaction_only=True)` + `LogisticRegression`
   - 카테고리별 학습 → 가중치 추출 → `WEIGHTS_INTERACT` 사전 저장
   - 검증: SLM harness 재실행, F1 측정
   
2. **XGBoost baseline (Phase A 대안)** — 2시간 작업
   - 비교 baseline 으로 활용
   - SHAP value 로 도메인 신호 검증

### 단기 (1~2주)
3. **TF-IDF + MLP (Phase B 진입)**
   - 텍스트 feature 추가, 정량 신호와 결합
   - hidden=(64, 32), dropout=0.3
   
4. **룰 마이닝 → verdict 증강**
   - 사용자 Claude 웹 응답 import → 신규 verdict 1,000~3,000건 확보
   - 재학습 → F1 측정

### 중기 (1개월)
5. **GNN 도입 (Phase C)**
   - PyG 설치, GAT layer 1~2개
   - 적법성 보강 효과 측정
   
6. **Active learning loop**
   - 매주 borderline 30건 export → Claude 웹 → import → 재학습

### 장기 (3개월)
7. **KoBERT fine-tuning (Phase D)**
   - 단, verdict 5,000건 이상 확보 후
   - Frozen BERT + MLP head 부터 시작 (full fine-tune 은 최종)

---

## 5. 성공 지표

| Phase | 타임라인 | 예상 F1 (앙상블) | Δ vs 현재 |
|-------|---------|-----------------|----------|
| 현재 | — | 0.749 | — |
| A (Polynomial) | 1주 | 0.78 | +0.03 |
| A + Tree | 2주 | 0.80 | +0.05 |
| B (TF-IDF MLP) | 1개월 | 0.83 | +0.08 |
| B + verdict 5K | 1.5개월 | 0.85 | +0.10 |
| C (GNN) | 2개월 | 0.87 | +0.12 |
| D (BERT) | 3개월 | 0.90 | +0.15 |

각 단계는 **누적 가능** — 이전 단계 결과를 보존하면서 단계적 성능 향상.

---

## 6. 위험 요소 및 완화

| 위험 | 영향 | 완화책 |
|------|------|--------|
| 데이터 부족 (소표본) | MLP/BERT 오버피팅 | regularization 강화, early stopping, k-fold CV |
| Pseudo-label 오류 누적 | concept drift | 매 라운드 holdout 검증, 신뢰구간 좁게 |
| 해석성 손실 | 사용자 신뢰 ↓ | SHAP/attention 시각화 유지 |
| 한국어 BERT 도메인 미스매치 | BERT 효과 ↓ | KLAW-BERT 또는 frozen BERT 만 사용 |
| 계산 비용 (GPU) | 학습 불가 | CPU-friendly 모델 우선 (XGBoost, frozen BERT) |

---

## 7. 결론

**현 단계 (Linear + 도메인 + 캘리브레이션 + 앙상블 게이팅)** 으로 F1=0.749 달성은 작은 데이터셋 환경에서 매우 견고한 baseline.

비선형성·뇌신경망 진화는 **데이터 증강 (룰 마이닝 → verdict 5K+) 과 병행**해야 안정적. 단순히 MLP/BERT 만 도입하면 표본 부족으로 오히려 성능 저하 위험.

**가장 ROI 높은 다음 단계**:
1. Polynomial interactions (1시간, F1 +0.03)
2. XGBoost (2시간, F1 +0.05, baseline 비교)
3. 룰 마이닝 → verdict 증강 (1주, F1 +0.05)
4. TF-IDF char n-gram (3일, F1 +0.05)

→ **1개월 내 F1 0.85 달성 가능**.
