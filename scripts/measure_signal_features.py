"""V2 단계 V4(신호 통합) — **측정만** (TF '코더', 레인: 측정만).

목적
----
라벨링이 추출한 신호 후보(outputs/signal_candidates.json)를 **조문→boolean 피처**로
구현해 기존 dense 피처에 append 했을 때, 동일 holdout(StratifiedKFold k=5, micro-F1,
bootstrap 95% CI)에서 MLP 의 TOTAL F1 이 유의하게 오르는가를 측정한다.

확정 기준선(동일 holdout)
-------------------------
  룰단독 0.495 [0.457,0.530] / 룰+SLM 앙상블 0.537 [0.505,0.574] / 순수MLP 0.508
  → 목표: 0.537 을 CI 비겹침으로 유의하게 넘는 신호가 있나.

누수 경고 (보고 필수)
---------------------
  신호 후보는 *이 라벨* 에서 뽑혀 *같은 라벨* 로 평가된다. 즉 어떤 신호 테마를
  '선택'하는 행위 자체가 full-data 라벨 정보를 사용한다(soft leakage). 따라서 본
  측정은 신호가 holdout 에서 '일반화'되는지의 **상한(optimistic)** 추정이다.
  단, 개별 신호는 generic 한 조문 구조/정규식(정의·벌칙·위원회·계획·수익적 등)이라
  law-specific 누수가 아니라 구조 일반화 측정으로서 의미가 있다.
  test-fold 누수는 없다: scaler/모델 fit 은 train fold 로만, 신호 피처는 라벨과
  무관한 텍스트 정규식이므로 fold 별로 재계산할 필요 없이 행 고정값이다.

레인 준수
---------
  engine/slm/features.py·룰·프로덕션 모델 영구수정/저장 없음. 신호 추출기는 본 파일
  내부 임시 모듈. baseline dense 는 torch_brain.collect_torch_data 와 동일 추출 사용.
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from engine.parser import parse_law
from engine.structure import decompose
from engine.slm.brain import CATEGORIES
from engine.slm.features import FEATURE_NAMES
from engine.slm.torch_brain import (
    _extract_dense_and_cat, _fit_eval_once, _prf,
    RULE_CAT, REASONING_RULE_CAT,
)


# ══════════════════════════════════════════════════════════════════════════
#  1. 신호 후보 로드 + 빈도/중복 정리 → 상위 테마 선별
# ──────────────────────────────────────────────────────────────────────────
#  선별 기준 (명시):
#   - effect == FP_FILTER 만 (코드화 명확, 295개 중에서). TP_BOOST/NEW_RULE 제외.
#   - 381 신호의 logic 은 prose+regex 혼합이라 1:1 자동파싱 불가 → 반복 출현하는
#     '조문 구조 테마'로 군집화하고, 빈도 상위 테마를 generic 정규식 boolean 으로 구현.
#   - 각 테마는 조문 제목/본문에 대한 generic 정규식(특정 법령명 비의존)으로만 정의
#     → law-specific 누수 아님(구조 신호).
#   - 선별 N = 빈도≥4 인 11개 테마(아래 SIGNAL_THEMES). signal_candidates 의
#     FP_FILTER 거의 전부를 커버.
# ══════════════════════════════════════════════════════════════════════════

# 테마명 → (signal_candidates 내 빈도 측정용 키워드 rx, 조문 boolean 추출용 함수)
# 빈도 키워드는 후보의 name+logic+rationale 텍스트에서 테마 등장 횟수 집계용.
_THEME_FREQ_RX = {
    "sig_enumeration": r"각 호|단순 열거|호 개수|열거",
    "sig_definition": r"정의|용어의?\s*뜻|용어.*뜻",
    "sig_penalty": r"벌칙|과태료|징역|벌금|몰수|추징|양벌",
    "sig_procedure": r"송달|통지|발급|공시|공표|촉탁|재결|청문",
    "sig_mutatis": r"준용|의제|본다|적용한다",
    "sig_beneficial": r"지원|보조금|포상|감면|급여|육성|진흥|촉진|장려",
    "sig_committee": r"위원회|심의위원회|구성[\s및ㆍ]*운영",
    "sig_delegation": r"필요한 사항|그 밖에|대통령령|총리령|부령",
    "sig_plan": r"기본계획|종합계획|관리계획|조성계획|사업계획|개발계획",
    "sig_internal_report": r"보고서|계획서|대장|회계|중앙관서",
    "sig_effort_duty": r"노력하여야|예산의 범위",
}


def load_and_rank_signals():
    """signal_candidates.json 로드 → FP_FILTER 테마별 빈도 집계.

    반환: (ranked: [(theme, freq)], meta: dict) — freq 내림차순.
    """
    d = json.loads(Path("outputs/signal_candidates.json").read_text(encoding="utf-8"))
    fp_sigs = []
    eff_counter = Counter()
    for k, v in d.items():
        for s in v.get("new_signals", []):
            eff_counter[s.get("effect", "?")] += 1
            if s.get("effect") == "FP_FILTER":
                fp_sigs.append(s)

    theme_cnt = Counter()
    for s in fp_sigs:
        blob = f"{s.get('name','')} {s.get('logic','')} {s.get('rationale','')}"
        for theme, rx in _THEME_FREQ_RX.items():
            if re.search(rx, blob):
                theme_cnt[theme] += 1
    ranked = theme_cnt.most_common()
    meta = dict(
        n_bundles=len(d),
        n_total=sum(eff_counter.values()),
        effects=dict(eff_counter),
        n_fp_filter=len(fp_sigs),
    )
    return ranked, meta


# ══════════════════════════════════════════════════════════════════════════
#  2. 조문 → 신호 boolean 피처 추출기 (임시 모듈, features.py 미수정)
# ──────────────────────────────────────────────────────────────────────────
#  각 신호는 조문 title + full_text 에 대한 generic 정규식. 특정 법령명 비의존.
#  return: dict[theme] = 0.0/1.0  (SIGNAL_FEATURE_NAMES 순서로 배열화)
# ══════════════════════════════════════════════════════════════════════════

SIGNAL_FEATURE_NAMES = [
    "sig_definition", "sig_penalty", "sig_committee", "sig_plan",
    "sig_beneficial", "sig_effort_duty", "sig_procedure", "sig_mutatis",
    "sig_delegation", "sig_enumeration", "sig_internal_report",
]

# generic 정규식 (조문 구조 — 법령명 비의존)
_RX_DEF_TITLE = re.compile(r"\((정의|용어의?\s*(뜻|정의))\)")
_RX_DEF_BODY = re.compile(r"용어의?\s*뜻은 다음과 같다|이 법에서 사용하는 용어|(이|라)\s*(함은|란).{0,15}말한다")
_RX_PEN_TITLE = re.compile(r"\((벌칙|과태료|몰수|추징|양벌규정|형벌|처벌)\)")
_RX_PEN_BODY = re.compile(r"\d+\s*년 이하의 징역|\d+\s*[천백만]+\s*원 이하의 (벌금|과태료)|(징역|벌금|구류|과료|사형|무기).{0,8}처한다")
_RX_COMMITTEE = re.compile(r"위원회|심의회|평의(원)?회")
_RX_COMMITTEE_BODY = re.compile(r"(구성|운영).{0,12}(필요한 사항|대통령령|총리령)|다음 각 호의 사항을 (심의|자문|의결|조정)")
_RX_PLAN = re.compile(r"(기본|종합|관리|조성|사업|개발|시행)계획")
_RX_PLAN_BODY = re.compile(r"다음 각 호의 사항.{0,20}포함|포함되어야 한다|고려하여")
_RX_BENEFICIAL = re.compile(r"지원|보조금|포상|감면|급여|육성|진흥|촉진|장려|보조|융자|육성한다")
_RX_ADVERSARIAL = re.compile(r"취소|정지|제재|처분|강제|벌|금지|철회|환수|박탈")
_RX_EFFORT = re.compile(r"노력하여야 한다|예산의 범위( 안|)에서|장려하여야")
_RX_PROCEDURE = re.compile(r"\((송달|통지|발급|공시|공표|촉탁|재결|기재|청문|열람|교부)\)")
_RX_MUTATIS = re.compile(r"준용한다|의제|본다|에 관하여는.{0,15}적용")
_RX_CITE_LAW = re.compile(r"「[^」]+법」")
_RX_DELEG = re.compile(r"(필요한 사항|그 밖에).{0,20}(대통령령|총리령|부령|조례)|(대통령령|총리령|부령)으로 정한다")
_RX_ITEM = re.compile(r"^\s*\d+\.\s|\n\s*\d+\.\s")
_RX_INTERNAL_REPORT = re.compile(r"(보고서|계획서|대장|장부|회계).{0,15}(작성|제출|보고)|중앙관서의 장")


def _count_items(text: str) -> int:
    return len(_RX_ITEM.findall(text))


def extract_signal_features(art) -> dict:
    """조문 1개 → 신호 boolean dict (SIGNAL_FEATURE_NAMES). features.py 미수정."""
    title = art.title or ""
    body = art.full_text or ""
    head = body[:300]  # 첫 문장/도입부

    n_items = _count_items(body)
    has_adv = bool(_RX_ADVERSARIAL.search(body))

    f = {n: 0.0 for n in SIGNAL_FEATURE_NAMES}
    # 정의조문
    f["sig_definition"] = float(bool(_RX_DEF_TITLE.search(title) or _RX_DEF_TITLE.search(head)
                                     or _RX_DEF_BODY.search(head)))
    # 벌칙/과태료
    f["sig_penalty"] = float(bool(_RX_PEN_TITLE.search(title) or _RX_PEN_TITLE.search(head)
                                  or _RX_PEN_BODY.search(body)))
    # 위원회 구성·심의
    f["sig_committee"] = float(bool((_RX_COMMITTEE.search(title) or _RX_COMMITTEE.search(head))
                                    and _RX_COMMITTEE_BODY.search(body)))
    # 계획 수립 (항목 열거형)
    f["sig_plan"] = float(bool((_RX_PLAN.search(title) or _RX_PLAN.search(head))
                               and _RX_PLAN_BODY.search(body) and not has_adv))
    # 수익적/지원 재량 (침익 키워드 부재)
    f["sig_beneficial"] = float(bool(_RX_BENEFICIAL.search(body) and not has_adv))
    # 노력의무·정책의무
    f["sig_effort_duty"] = float(bool(_RX_EFFORT.search(body) and not has_adv))
    # 절차조문 (송달·통지·공시 등)
    f["sig_procedure"] = float(bool(_RX_PROCEDURE.search(title) or _RX_PROCEDURE.search(head)))
    # 준용·의제 + 다수 법령 인용
    f["sig_mutatis"] = float(bool(_RX_MUTATIS.search(body) and len(_RX_CITE_LAW.findall(body)) >= 2))
    # 위임/포괄위임
    f["sig_delegation"] = float(bool(_RX_DELEG.search(body)))
    # 단순 호 열거 (단서·침익 부재 + 다수 호)
    f["sig_enumeration"] = float(bool(n_items >= 5 and "다만" not in body and not has_adv))
    # 내부 보고/대장/회계
    f["sig_internal_report"] = float(bool(_RX_INTERNAL_REPORT.search(body)))
    return f


# ══════════════════════════════════════════════════════════════════════════
#  3. 데이터 적재 (baseline dense + signal dense). collect_torch_data 와 동일 표본.
# ──────────────────────────────────────────────────────────────────────────
#  baseline dense: _extract_dense_and_cat (== collect_torch_data 가 쓰는 추출)
#  signal dense  : extract_signal_features (본 파일 임시 추출기)
# ══════════════════════════════════════════════════════════════════════════

def collect_with_signals():
    """동일 표본 적재 → (dense_base, dense_sig, ti, si, mi, y, sig_active).

    sig_active: 각 신호 컬럼이 1인 행 수 (참고용).
    torch_brain.collect_torch_data 의 적재 로직을 그대로 따르되 article 객체를
    유지해 신호 피처를 추가 계산한다(동일 키 집합·동일 순서 보장).
    """
    with open("outputs/verification_dataset.jsonl") as fh:
        rows = [json.loads(l) for l in fh]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    from engine.structure import ArticleType, Subject, Modal  # noqa: F401 (parity)

    art_labels: dict = defaultdict(dict)
    art_objects: dict = {}
    law_cache: dict = {}

    def get_law(law_name: str):
        if law_name in law_cache:
            return law_cache[law_name]
        md = Path(f"data/laws/raw/{law_name}/법률.md")
        if not md.exists():
            law_cache[law_name] = None
            return None
        text = md.read_text(encoding="utf-8", errors="replace")
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                text = parts[2]
        try:
            law = parse_law(text, name=law_name)
            law_cache[law_name] = law
            return law
        except Exception:
            law_cache[law_name] = None
            return None

    for r in rows:
        if r["verdict"] not in ("TP", "FP"):
            continue
        rule_id = r["rule_id"]
        cat = RULE_CAT.get(rule_id) or REASONING_RULE_CAT.get(rule_id)
        if not cat:
            continue
        fid = r["fid"]
        if "@" not in fid:
            continue
        _, ln = fid.split("@", 1)
        an = fid_map.get(fid)
        if not an:
            continue
        law = get_law(ln)
        if law is None:
            continue
        art = next((a for a in law.articles
                    if a.number.replace(" ", "") == an.replace(" ", "")), None)
        if not art:
            continue
        key = (ln, an)
        art_objects[key] = art
        label = 1 if r["verdict"] == "TP" else 0
        prev = art_labels[key].get(cat)
        if prev is None or label > prev:
            art_labels[key][cat] = label

    dense_base_list, dense_sig_list = [], []
    type_list, subj_list, modal_list, y_list = [], [], [], []
    sig_active = Counter()
    for key, art in art_objects.items():
        dense, ti, si, mi = _extract_dense_and_cat(art)
        dense_base_list.append(dense)
        type_list.append(ti); subj_list.append(si); modal_list.append(mi)
        sf = extract_signal_features(art)
        for nm in SIGNAL_FEATURE_NAMES:
            if sf[nm] > 0:
                sig_active[nm] += 1
        dense_sig_list.append([sf[nm] for nm in SIGNAL_FEATURE_NAMES])
        y_list.append([art_labels[key].get(c, -1) for c in CATEGORIES])

    return (
        np.array(dense_base_list, dtype=np.float32),
        np.array(dense_sig_list, dtype=np.float32),
        np.array(type_list, dtype=np.int64),
        np.array(subj_list, dtype=np.int64),
        np.array(modal_list, dtype=np.int64),
        np.array(y_list, dtype=np.float32),
        dict(sig_active),
    )


# ══════════════════════════════════════════════════════════════════════════
#  4. 동일 holdout CV (evaluate_cv 와 동일 fold/micro-F1/CI) — baseline vs +signal
# ══════════════════════════════════════════════════════════════════════════

def _oof_eval(dense, ti, si, mi, y, *, k=5, seed=42, n_boot=1000, n_pos_min=15,
              epochs=100, hidden=(32, 16)):
    """evaluate_cv 와 동일 절차: StratifiedKFold OOF → micro-F1 + bootstrap CI."""
    from sklearn.model_selection import StratifiedKFold, KFold

    n = dense.shape[0]
    strat = ((y == 1).any(axis=1)).astype(int)
    n_pos_rows = int(strat.sum())
    if k <= n_pos_rows <= n - k:
        splitter = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
        split_iter = splitter.split(np.zeros(n), strat)
        strat_mode = f"StratifiedKFold(양성보유행 {n_pos_rows}/{n})"
    else:
        splitter = KFold(n_splits=k, shuffle=True, random_state=seed)
        split_iter = splitter.split(np.zeros(n))
        strat_mode = f"KFold(폴백 {n_pos_rows})"

    oof_pred = np.full((n, len(CATEGORIES)), np.nan, dtype=np.float32)
    oof_y = np.full((n, len(CATEGORIES)), -1.0, dtype=np.float32)
    for train_idx, test_idx in split_iter:
        _, _, pred_te, y_te = _fit_eval_once(
            dense, ti, si, mi, y, train_idx, test_idx,
            hidden=hidden, epochs=epochs,
        )
        oof_pred[test_idx] = pred_te
        oof_y[test_idx] = y_te

    def f1_col(idx, col):
        yt = oof_y[idx, col]; m = yt >= 0; yt = yt[m]
        yp = (oof_pred[idx, col][m] >= 0.5).astype(float)
        tp = float(((yp == 1) & (yt == 1)).sum())
        fp = float(((yp == 1) & (yt == 0)).sum())
        fn = float(((yp == 0) & (yt == 1)).sum())
        return _prf(tp, fp, fn)[2]

    def f1_total(idx):
        tp = fp = fn = 0.0
        for col in range(len(CATEGORIES)):
            yt = oof_y[idx, col]; m = yt >= 0; yt = yt[m]
            yp = (oof_pred[idx, col][m] >= 0.5).astype(float)
            tp += float(((yp == 1) & (yt == 1)).sum())
            fp += float(((yp == 1) & (yt == 0)).sum())
            fn += float(((yp == 0) & (yt == 1)).sum())
        return _prf(tp, fp, fn)[2]

    rng = np.random.default_rng(seed)
    all_idx = np.arange(n)

    def boot_ci(fn):
        stats = np.empty(n_boot)
        for b in range(n_boot):
            samp = rng.integers(0, n, size=n)
            stats[b] = fn(samp)
        lo, hi = np.percentile(stats, [2.5, 97.5])
        return float(lo), float(hi)

    per_cat = {}
    for ci, cat in enumerate(CATEGORIES):
        n_pos = int((oof_y[:, ci] == 1).sum())
        pt = f1_col(all_idx, ci)
        if n_pos < n_pos_min:
            lo = hi = float("nan")
        else:
            lo, hi = boot_ci(lambda idx, _c=ci: f1_col(idx, _c))
        per_cat[cat] = dict(n_pos=n_pos, f1=pt, ci_lo=lo, ci_hi=hi,
                            measurable=(n_pos >= n_pos_min))
    tot_pt = f1_total(all_idx)
    tot_lo, tot_hi = boot_ci(f1_total)
    total = dict(n_pos=int((oof_y == 1).sum()), f1=tot_pt, ci_lo=tot_lo, ci_hi=tot_hi)
    return dict(per_cat=per_cat, total=total, strat_mode=strat_mode, n=n)


def _fmt(d):
    if d.get("measurable", True) and not np.isnan(d.get("ci_lo", float("nan"))):
        return f"{d['f1']:.3f} [{d['ci_lo']:.3f},{d['ci_hi']:.3f}]"
    return f"{d['f1']:.3f} [측정불가 n_pos<15]"


def main():
    print("=" * 78)
    print("[V2-V4 신호통합] 측정만 — 동일 holdout(StratifiedKFold k=5 seed=42, "
          "micro-F1, bootstrap CI n_boot=1000)")
    print("=" * 78)

    ranked, meta = load_and_rank_signals()
    print(f"\n[1] 신호 후보 로드: bundles={meta['n_bundles']}, 총 {meta['n_total']}개, "
          f"effects={meta['effects']}")
    print(f"    FP_FILTER {meta['n_fp_filter']}개 → 반복 테마 빈도 상위 선별:")
    for theme, freq in ranked:
        print(f"      {freq:4d}  {theme}")
    print(f"    선별 N = {len(SIGNAL_FEATURE_NAMES)} 테마 (generic 정규식 boolean, "
          "법령명 비의존)")

    print("\n[2,3] 데이터 적재 (baseline dense + signal dense, 동일 표본)...")
    db, ds, ti, si, mi, y, sig_active = collect_with_signals()
    print(f"    N rows={db.shape[0]}, baseline dense={db.shape[1]}, "
          f"signal dense={ds.shape[1]}, total pos={int((y==1).sum())}")
    print("    신호 활성 행 수(피처별):")
    for nm in SIGNAL_FEATURE_NAMES:
        print(f"      {nm:<22} {sig_active.get(nm,0):>5} / {db.shape[0]}")

    print("\n[4] CV 평가 — (A) 기존피처 vs (B) 기존+신호피처 ...")
    print("    A: baseline dense 학습/평가 중...")
    A = _oof_eval(db, ti, si, mi, y)
    print("    B: baseline+signal dense 학습/평가 중...")
    dbs = np.concatenate([db, ds], axis=1)
    B = _oof_eval(dbs, ti, si, mi, y)

    print(f"\nstrat_mode: {A['strat_mode']}")
    print("\n[per-cat] TOTAL/카테고리 micro-F1 ± 95%CI")
    print(f"{'카테고리':<8} {'n_pos':>5}  {'(A)기존피처':<24} {'(B)기존+신호':<24}")
    print("-" * 70)
    for c in CATEGORIES:
        print(f"{c:<8} {A['per_cat'][c]['n_pos']:>5}  "
              f"{_fmt(A['per_cat'][c]):<24} {_fmt(B['per_cat'][c]):<24}")
    print("-" * 70)
    print(f"{'TOTAL':<8} {A['total']['n_pos']:>5}  "
          f"{_fmt(A['total']):<24} {_fmt(B['total']):<24}")

    # ── 동일 잣대 비교표 (팀장 확정 baseline 병기) ──
    a, b = A["total"], B["total"]
    print("\n[동일 잣대 — TOTAL micro-F1]")
    print(f"  룰단독(확정)        : 0.495 [0.457,0.530]")
    print(f"  순수MLP(확정)       : 0.508")
    print(f"  룰+SLM 앙상블(확정) : 0.537 [0.505,0.574]  ← 넘어야 할 목표")
    print(f"  (A) 기존피처 MLP    : {_fmt(a)}")
    print(f"  (B) 기존+신호 MLP   : {_fmt(b)}")

    # ── 판정 ──
    def overlap(x, yy):
        return not (x["ci_hi"] < yy["ci_lo"] or x["ci_lo"] > yy["ci_hi"])
    ens = dict(f1=0.537, ci_lo=0.505, ci_hi=0.574)
    print("\n[핵심 판정]")
    print(f"  B 점추정 {b['f1']:.3f}  vs  A 점추정 {a['f1']:.3f}  (Δ={b['f1']-a['f1']:+.3f})")
    print(f"  B CI [{b['ci_lo']:.3f},{b['ci_hi']:.3f}] vs A CI [{a['ci_lo']:.3f},{a['ci_hi']:.3f}]"
          f" → 겹침: {'예(비유의)' if overlap(a,b) else '아니오(유의)'}")
    print(f"  B CI vs 앙상블 0.537[0.505,0.574] → 겹침: "
          f"{'예(0.537 유의초과 실패)' if overlap(b,ens) else '아니오'}")
    beats_537_sig = b["ci_lo"] > ens["ci_hi"]
    print(f"  → 신호 추가가 0.537 을 *유의하게(CI 비겹침)* 넘나? "
          f"{'예' if beats_537_sig else '아니오'}")

    out = dict(
        selection=dict(ranked=ranked, meta=meta,
                       selected=SIGNAL_FEATURE_NAMES, sig_active=sig_active),
        baseline_feats=A, with_signal_feats=B,
        teamlead_baselines=dict(rule_only="0.495 [0.457,0.530]", pure_mlp="0.508",
                                rule_slm="0.537 [0.505,0.574]"),
        verdict=dict(
            A_total=a["f1"], A_ci=[a["ci_lo"], a["ci_hi"]],
            B_total=b["f1"], B_ci=[b["ci_lo"], b["ci_hi"]],
            delta=b["f1"] - a["f1"],
            B_vs_A_overlap=overlap(a, b),
            B_vs_ens537_overlap=overlap(b, ens),
            B_significantly_beats_537=bool(beats_537_sig),
        ),
        leakage_note=(
            "신호 테마 '선택'은 full-data 라벨 기반(soft leakage) → 본 측정은 "
            "일반화 상한(optimistic). test-fold 누수는 없음(scaler/모델 fit train-only, "
            "신호는 라벨무관 텍스트 정규식). 개별 신호는 generic 구조 정규식이라 "
            "law-specific 누수 아님."),
    )
    Path("outputs/signal_features_measure.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n(측정 산출물 outputs/signal_features_measure.json 기록 — 프로덕션 미수정, 커밋 안함)")


if __name__ == "__main__":
    main()
