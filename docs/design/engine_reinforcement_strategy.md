# 엔진 강화 전략 — LLM 콘텐츠 검증 기반 신호 이식

## 1. 출발점 — 룰 엔진의 한계

현재 엔진은 **키워드/정규식 매칭**으로 1차 스캔한다.
- 예: S-02 위임 검증 → "필요한 사항", "대통령령으로 정하는", "그 밖에" 등 토큰 일치
- 결과: 1,704개 법령에서 150,294건의 후보 finding

이 방식의 본질적 한계:
- **의미·맥락을 못 본다**. "필요한 사항"이 정의조문에서 다른 법 인용을 위해 쓰였는지,
  실제 시행령 위임을 만드는지 구분 불가.
- **다층 신호를 못 본다**. "위임 키워드 + 시행령에 구체화 조항이 이미 있음" 같은
  교차 신호는 룰 한 줄로 표현 어려움.
- **새 결함 유형을 못 본다**. 인간이 룰을 미리 적어둔 것만 잡음.

따라서 키워드 매칭만으로는 **precision도 recall도 본질적 천장**이 있다.

## 2. 전략 — LLM을 일회성 distillation 으로

**LLM 의존을 영구화하지 않는다**. LLM 호출 비용·편향·재현성 문제 때문.
대신 LLM의 **콘텐츠 이해 능력**을 한 번 빌려서, 거기서 발견한 신호를
**엔진 코드의 새 분석 어휘**로 이식한다.

```
[1차 룰 키워드 매칭]
   ↓ 후보 finding 150K
[LLM이 콘텐츠 보고 검증]
   ↓ TP/FP 라벨 + reasoning + 발견한 신호 패턴
[신호를 엔진 코드로 이식]
   ↓
[강화된 엔진 — 키워드 → 구조신호 → 맥락신호]
```

이식의 형태:
1. **새 feature** — 기존 룰에 추가할 negative/positive 신호
   - 예: "조문 앞 절에 `'~란 ...을 말한다'`가 있으면 위임이 아닌 정의" → 정의조문 마커
2. **새 룰** — 키워드로 잡을 수는 있는데 인간이 못 적어둔 패턴
   - 예: "재량 거부 가능성" 같은 G-02 변종
3. **새 분석 차원** — 단일 매칭이 아닌 교차 신호
   - 예: "위임" + "시행령 매핑 존재" + "조문 유형=일반" → TP 강 신호

핵심: LLM이 본 것을 **사람이 읽고 코드로 옮긴다**. 자동 패치는 LLM 편향을 그대로 박는 위험.

## 3. 잘못된 접근 (배제)

- **❌ 통계 기반 빈도 분석**
  matched_text 빈도, 조문 분포 cross-tab 등. 이는 키워드 매칭의 본질적 한계를
  못 깬다 — 의미·맥락이 빠진 채 분포만 보기 때문. 강화 신호의 source 가
  아니다 (다만 LLM이 본 신호를 검증·정량화하는 보조 도구로는 유용).

- **❌ LLM 의존 영구화**
  매 분석마다 LLM 호출하는 파이프라인. 비용·편향·재현성 모두 나빠짐.
  LLM은 **한 번** 들여다보고 신호를 뽑은 다음 빠진다.

- **❌ 한 줄 압축으로 LLM에 묻기**
  matched_text + summary 만 주면 LLM도 결국 키워드 판정. 콘텐츠 검증의
  의미가 사라짐. **조문 본문 + 맥락** 이 LLM 입력의 최소 단위.

## 4. 4-Stage 청사진

엔진을 "키워드 매칭 → AI에 가까운 의미 feature 통합 판정"으로 진화시키는 전체 흐름.

| Stage | 목적 | LLM | 산출물 |
|-------|------|-----|--------|
| **A. 검증 데이터 수집** | 룰 1차 진단 결과를 LLM이 콘텐츠 보고 라벨링 | ◯ 일회성 | `outputs/verification_dataset.jsonl` |
| **B. 신호 추출** | 라벨 데이터에서 keyword 너머 feature 발굴 | ✗ | `docs/design/signal_catalog.md` |
| **C. 엔진 이식** | 신호를 코드/분류기로 — 진짜 강화 | ✗ | `engine/signals/*.py` + 룰 통합 |
| **D. 운영** | 새 법령 자동 분석은 LLM 없이 | ✗ (분기별 spot-check) | 영구 강화된 엔진 |

핵심: **C 단계에서 키워드 → 의미 feature 통합 판정으로 진화**. 예시 feature:

- `article_type_classifier` — 정의/벌칙/절차/일반 등 조문 유형 분류
- `delegation_concreteness_score` — 위임의 구체성 0~1
- `relief_vs_burden_classifier` — 수익적 vs 침익적 조문
- `enforcement_decree_coverage` — 시행령 구체화 정도

LLM은 A에서만 등장, B 이후는 코드로만 동작.

## 5. Stage A — 검증 데이터 수집

### 5.1 sample 설계

- 모집단: 150,294 finding (룰 1차 진단 결과, 1,704 법령 누적)
- 학습 데이터로 충분한 양: 룰별 stratified **300~500건 = 총 ~7~10K**
- ChatGPT Plus 가정 (128K 입력 / 16K 출력)
- sub-bundle 한 번 = **50건** (입력 ~60KB / 출력 ~10KB) → 호출 약 ~150회

### 5.2 sub-bundle 형태 (콘텐츠 포함)

한 sub-bundle 안에:
- 시스템 프롬프트 1회
- 응답 스키마 1회
- finding 50건, 각 finding은:
  - 전역 식별자 `<finding_id>@<법령명>`
  - 법령·조문·severity·매칭 텍스트
  - **조문 본문 전체** (중복 조문은 본문 1번만, finding 여러 개는 참조)
  - **시행령 매핑 본문** (있는 경우만)

### 5.3 LLM에게 묻는 것

1. 각 finding의 **TP/FP/BORDER + 콘텐츠 인용 근거** (짧게)
2. **새 신호** — 키워드로 못 잡지만 콘텐츠에서 보이는 패턴 (코드화 가능한 표현)
3. **놓친 패턴** — 룰이 잡지 못한 결함 유형 (recall 신호)

### 5.4 응답 JSON 스키마 (효율 최적화)

```json
{
  "bundle_id": "S-02_part01",
  "rule_id": "S-02",
  "verdicts": [
    {"fid": "S-02-001@금융거래지표의관리에관한법률",
     "v": "TP|FP|BORDER",
     "ev": "조문 인용 ≤30자"}
  ],
  "new_signals": [
    {"name": "정의조문 인용형 위임",
     "logic": "article.title contains '정의' AND prev_clause matches '~란.*말한다'",
     "effect": "FP_FILTER",
     "examples": ["S-02-001@금융거래지표의관리에관한법률"]}
  ],
  "missed_patterns": [
    {"name": "...",
     "logic": "...",
     "examples": ["「법령」 §X"]}
  ]
}
```

- 짧은 키 (`fid`, `v`, `ev`) → 출력 토큰 절약
- `verdicts` 는 1줄 / `new_signals` 는 풍부
- `rule_assessment` 등 메타는 Stage B에서 별도 분석 (응답 토큰 절약)

### 5.5 파이프라인

1. `scripts/bundle_rule_verification.py` — 룰별 stratified sample → sub-bundle MD
2. 사용자가 sub-bundle 하나씩 ChatGPT Plus 에 복붙 → 응답 저장
3. `scripts/import_rule_verification.py` — 응답 검증 + 통합 jsonl 생성
4. 진척 추적용 `_index.json` (몇 개 처리됨, 어느 게 누락)

## 6. Stage B — 신호 추출 (LLM 없음)

A의 jsonl 을 사람이 / 분석 스크립트가 보고:
- 동일 신호의 다른 표현을 통합 (중복 제거)
- 적용 빈도 / 영향력 (TP↑ N건 / FP↓ N건) 정량화
- 코드화 가능 여부 평가
- 채택할 신호 목록 → `docs/design/signal_catalog.md`

## 7. Stage C — 엔진 이식 (LLM 없음)

각 채택된 신호별로:
- `engine/signals/<name>.py` 작성 — pure function, finding 또는 조문 받아 score/bool 반환
- 기존 룰 (`engine/rules/*.py`) 에 신호 통합 — keyword + signal score → 종합 판정
- 또는 작은 분류기 (logistic regression / gradient boosting) 로 feature 벡터 → label
- 재스캔 + `scripts/evaluate.py` 로 precision/recall 변화 측정
- 개선 확인 → commit. 효과 없음 → 롤백.

## 8. 명시적으로 안 하는 것

- LLM 응답을 자동으로 룰 코드에 patch (편향 박힘)
- 매 분석마다 LLM 호출 (의존 영구화)
- 룰 번들에 콘텐츠 빼고 메타만 (v1 실패 사유)
- 통계 분석을 일차 강화 source 로 (보조 도구만)
