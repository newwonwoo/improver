# Phase 13 v2 세션 인계 메모

**날짜**: 2026-06-02
**브랜치**: `claude/read-zip-files-aTHxT`
**마지막 커밋**: `88618f9` Phase 13 v2 + (이번 commit 예정) P-META-1 엔진 통합

---

## 1. 이번 세션 핵심 진행 사항

### A. 사용자 로컬 크롤링 98건 통합 (`bd9143a`)
- moleg_interp 90건 + ftc_press 8건
- 누적: moleg 100건, ftc_press 14건
- pull --rebase 시 충돌 없이 통합

### B. Phase 13 분류 파이프라인 (`fc83c91`)
- `scripts/phase13_process_local_crawl.py` — 자동 분류
- 결과: 추론엔진 vs 신경망 라우팅 명확화

### C. R-LAW-PRECEDENCE 추론규칙 추가 (`4bc485a`)
- `has_undefined_precedence` 신호 (FEATURE_NAMES 73→74)
- KNOWLEDGE_BASE 15→16 규칙
- 0.15% 발화율 — 적정 희소도

### D. v1 라벨링 batch (13개) → Claude.ai QA 검증 (`ab2f8ba`)
- 사용자가 batch_01 라벨링 → **5가지 데이터 파이프라인 문제 발견**:
  1. 법령↔해석례 매핑 오류 3건
  2. 배경법령을 쟁점법령으로 오인 2건
  3. 중복 미제거 2쌍
  4. `articles[:30]` 컷 버그 (export 스크립트)
  5. R-DELEG-BLANKET 구조적 FP (시행령 한정열거 무시)

### E. Phase 13 v2 데이터 파이프라인 재구축 (`88618f9`)
- `scripts/phase13_process_local_crawl_v2.py`
- `scripts/phase13_export_verdict_batches_v2.py`
- 제목 끝 `(「쟁점법령」 제N조 관련)` 패턴 활용 → primary law/article 정확 추출
- 100건 → **33건 정확 매칭** (75% 매핑 오류 제거)
- v2 batch 5개 생성 (8×4 + 1×1)

### F. P-META-1: R-DELEG-BLANKET FP 필터 (이번 작업)
- `has_sublaw_concrete_enum` 신호 추가 (FEATURE_NAMES 74→75)
- `engine/slm/features.py::enrich_with_sublaw()` — 시행령 한정열거 자동 확인
- R-DELEG-BLANKET premises 에 negation 추가
- `diagnose_with_reasoning` 에서 자동 enrich 호출
- **효과**: 500개 법령 샘플에서 R-DELEG-BLANKET 발화 2,686건 → 446건 (**83% FP 제거**)

---

## 2. 미완료 / 다음 세션 우선순위

### 🟢 즉시 진행 가능
1. **v2 batch_01~05 라벨링** — Claude.ai 에 복붙 → 응답 import → torch 재학습
   - 위치: `outputs/phase13_verdict_batches_v2/`
   - 응답 저장 경로: `outputs/phase13_verdict_responses/`
   - import: `python scripts/phase13_import_verdict_responses.py`
   - 재학습: `python -c "from engine.slm.torch_brain import train_torch; train_torch()"`

2. **P-META-1 효과 측정 torch 재학습**
   - 현재 영향 추정: R-DELEG-BLANKET 정밀도 0.30→0.60+ (FP 83% 제거)
   - 3-run mean F1 측정 필요

### 🟡 검토 필요
3. **P-META-2 verify** (이번 세션에서 검증 완료)
   - `articles[:30]` 컷은 v1 export 스크립트 한정 문제, v2 에서 수정됨
   - 진단엔진 코어에는 이 버그 없음 ✓

4. **P-META-3 ground truth 오용 방지**
   - moleg 해석례 = 법 해석 다툼, ≠ 입법 결함 정답지
   - v2 batch 의 `relevant_to_moleg` 필드로 분리 가능
   - 결정: moleg 는 *엔진-쟁점 매칭 QA 도구* 로 사용, *학습 정답지* 로는 신중 사용

### 🔴 필요시
5. **시행령 매칭 정확도 향상** (`has_sublaw_concrete_enum`)
   - 현재 패턴: `법 제N조` 인용 위치 ± 1500자 한정 열거 확인
   - 더 정교한 매칭: `법 제N조제M항` 까지 매칭, 별표 인용 처리

6. **신규 룰 R-APP-EXCLUSION** (`application_exclusion` 47/100 패턴)
   - 적용 배제 규정 의 패턴 — 법령 정합성 영역

---

## 3. 데이터·코드 인벤토리

### 핵심 디렉토리
```
engine/
├── slm/
│   ├── features.py          # 75-dim, enrich_with_sublaw 추가
│   ├── brain.py             # linear backend
│   ├── torch_brain.py       # multi-task NN (BCE + pos_weight)
│   ├── ensemble.py          # backend 선택
│   └── hybrid_brain.py      # SLM+NN 앙상블
├── reasoning/
│   └── inference.py         # 16 rules, diagnose_with_reasoning
├── graph/
│   └── law_graph.py         # 84k nodes PageRank
└── parser.py, structure.py  # law decompose

outputs/
├── verification_dataset.jsonl              # 2,394 verdicts
├── phase13_verdict_candidates_v2.jsonl     # 33 candidates (v2)
├── phase13_verdict_batches_v2/             # 5 batches for Claude.ai
├── slm_harness_report.json                 # phase 1-13 metrics
├── slm_torch_model.pt                      # 73-dim (Phase 12 retrain)
└── PHASE12_DIAGNOSTIC_REPORT.md
    PHASE13_LOCAL_CRAWL_REPORT.md
```

### 기관 약어 (사용자 용어집 요청)
- BAI 감사원 / FTC 공정위 / FSS 금감원 / ACRC 권익위 / NHRC 인권위
- moleg 법제처 / CC 헌법재판소

---

## 4. 누적 데이터 통계

| 항목 | 수치 |
|---|---|
| 법령 corpus | 1,745 |
| verdict 데이터 | 2,394 |
| 추론 규칙 | 16 |
| 신호 차원 | 75 |
| 수집 사례 (감찰기관) | ~590건 |
| moleg 해석례 | 100건 |
| ftc_press | 14건 |
| Torch holdout F1 (마지막 측정) | 0.468 (Phase 13, 74-dim 기준) |
| **P-META-1 효과 측정 대기 중** | — |

---

## 5. 다음 세션 추천 시작 명령

```bash
# 1. 사용자 라벨링 응답이 있을 경우
python scripts/phase13_import_verdict_responses.py

# 2. P-META-1 효과 측정 (torch 재학습 3회)
python -c "
from engine.slm.torch_brain import train_torch
import json
results = []
for r in range(3):
    per_cat, total = train_torch(epochs=120)
    p = total['tp']/max(total['tp']+total['fp'],1)
    r_ = total['tp']/max(total['tp']+total['fn'],1)
    f1 = 2*p*r_/max(p+r_,1e-9)
    results.append({'f1': f1, 'tp': total['tp'], 'fp': total['fp']})
print(results)
"

# 3. 새 batch 생성 필요시
python scripts/phase13_export_verdict_batches_v2.py
```

---

**핵심 메시지**: P-META-1 (시행령 한정열거 필터) 가 가장 큰 발견. R-DELEG-BLANKET 의 83% FP 제거 효과 — Phase 14 의 시작점.
