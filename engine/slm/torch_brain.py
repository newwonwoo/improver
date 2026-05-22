"""Phase 3 — PyTorch 본격 신경망.

Embedding (ArticleType, Subject, Modal) + Dense (정량 신호) → MLP →
Multi-task output (5 카테고리 simultaneous).

조건: torch 가용시만 작동.
"""
from __future__ import annotations

import json
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import TensorDataset, DataLoader
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False

from ..parser import parse_law
from ..structure import decompose, ArticleType, Subject, Modal
from .brain import CATEGORIES
from .features import extract_features
from .learn import RULE_CAT


# 범주 인덱싱
_AT_LIST = list(ArticleType)
_SUBJ_LIST = list(Subject)
_MODAL_LIST = list(Modal)
_AT_IDX = {t: i for i, t in enumerate(_AT_LIST)}
_SUBJ_IDX = {s: i for i, s in enumerate(_SUBJ_LIST)}
_MODAL_IDX = {m: i for i, m in enumerate(_MODAL_LIST)}


class TorchBrain(nn.Module):
    """Embedding + Dense + Multi-layer NN multi-task."""

    def __init__(
        self,
        n_dense: int,
        n_categories: int = 5,
        type_emb: int = 4,
        subj_emb: int = 3,
        modal_emb: int = 3,
        hidden: tuple[int, ...] = (32, 16),
        dropout: float = 0.2,
    ):
        super().__init__()
        self.emb_type = nn.Embedding(len(_AT_LIST), type_emb)
        self.emb_subj = nn.Embedding(len(_SUBJ_LIST), subj_emb)
        self.emb_modal = nn.Embedding(len(_MODAL_LIST), modal_emb)
        input_dim = n_dense + type_emb + subj_emb + modal_emb
        layers = []
        prev = input_dim
        for h in hidden:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout))
            prev = h
        layers.append(nn.Linear(prev, n_categories))
        self.mlp = nn.Sequential(*layers)

    def forward(self, dense, type_idx, subj_idx, modal_idx):
        e1 = self.emb_type(type_idx)
        e2 = self.emb_subj(subj_idx)
        e3 = self.emb_modal(modal_idx)
        x = torch.cat([dense, e1, e2, e3], dim=-1)
        return torch.sigmoid(self.mlp(x))


def _extract_dense_and_cat(art):
    """Article → (dense_vec, type_idx, subj_idx, modal_idx)."""
    decomp = decompose(art)
    fv = extract_features(art, decomp).to_dict()

    # dense — categorical 범주 제외
    excluded = set()
    for t in _AT_LIST:
        excluded.add(f"is_{t.value.lower()}")
    for s in _SUBJ_LIST:
        if s == Subject.UNKNOWN: continue
        excluded.add(f"subj_{s.value.lower()}")
    for m in _MODAL_LIST:
        if m == Modal.NONE: continue
        excluded.add(f"modal_{m.value.lower()}")
    # is_general 도 ArticleType 매핑
    excluded.add("is_general")
    # subj_official 등
    # extract_features 명명 규칙은 따로 — 차라리 전체 dense 로 처리 + emb 부수적
    dense = [v for k, v in fv.items() if isinstance(v, (int, float))]

    type_idx = _AT_IDX[decomp.type]
    subj_idx = _SUBJ_IDX[decomp.primary_subject]
    first_modal = Modal.NONE
    for p in decomp.paragraphs:
        if p.modal != Modal.NONE:
            first_modal = p.modal
            break
    modal_idx = _MODAL_IDX[first_modal]
    return dense, type_idx, subj_idx, modal_idx


def collect_torch_data():
    """verdict 데이터 → torch tensors (dense + cat indices + multi-task labels)."""
    if not _TORCH_OK:
        raise RuntimeError("torch not installed")
    with open("outputs/verification_dataset.jsonl") as f:
        rows = [json.loads(l) for l in f]
    fid_map = json.loads(Path("outputs/fid_article_map.json").read_text(encoding="utf-8"))

    # article 별로 grouping — 5 카테고리 multi-label 동시
    art_labels: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    art_objects: dict[tuple[str, str], Any] = {}

    law_cache: dict[str, Any] = {}

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
        cat = RULE_CAT.get(rule_id)
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
        # 둘 다 라벨 있으면 OR (TP 우선)
        label = 1 if r["verdict"] == "TP" else 0
        prev = art_labels[key].get(cat)
        if prev is None or label > prev:
            art_labels[key][cat] = label

    # tensor 화
    dense_list = []
    type_list = []
    subj_list = []
    modal_list = []
    y_list = []
    for key, art in art_objects.items():
        dense, ti, si, mi = _extract_dense_and_cat(art)
        dense_list.append(dense)
        type_list.append(ti)
        subj_list.append(si)
        modal_list.append(mi)
        # multi-task label: 5 카테고리, missing 은 -1 (loss masking)
        labels = [art_labels[key].get(c, -1) for c in CATEGORIES]
        y_list.append(labels)

    dense_arr = np.array(dense_list, dtype=np.float32)
    type_arr = np.array(type_list, dtype=np.int64)
    subj_arr = np.array(subj_list, dtype=np.int64)
    modal_arr = np.array(modal_list, dtype=np.int64)
    y_arr = np.array(y_list, dtype=np.float32)

    return dense_arr, type_arr, subj_arr, modal_arr, y_arr


def train_torch(
    hidden: tuple[int, ...] = (32, 16),
    dropout: float = 0.2,
    epochs: int = 100,
    lr: float = 1e-3,
    batch_size: int = 32,
    test_size: float = 0.2,
):
    """PyTorch multi-task NN 학습."""
    if not _TORCH_OK:
        raise RuntimeError("torch not installed")
    dense, ti, si, mi, y = collect_torch_data()
    n = dense.shape[0]
    # train/test split
    rng = np.random.default_rng(42)
    perm = rng.permutation(n)
    n_test = int(n * test_size)
    test_idx = perm[:n_test]
    train_idx = perm[n_test:]

    # 표준화 (dense)
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler().fit(dense[train_idx])
    dense_n = scaler.transform(dense)

    device = torch.device("cpu")
    model = TorchBrain(
        n_dense=dense_n.shape[1],
        n_categories=len(CATEGORIES),
        hidden=hidden,
        dropout=dropout,
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-3)

    # 데이터셋
    X_dense_tr = torch.tensor(dense_n[train_idx], dtype=torch.float32)
    X_ti_tr = torch.tensor(ti[train_idx], dtype=torch.long)
    X_si_tr = torch.tensor(si[train_idx], dtype=torch.long)
    X_mi_tr = torch.tensor(mi[train_idx], dtype=torch.long)
    y_tr = torch.tensor(y[train_idx], dtype=torch.float32)

    X_dense_te = torch.tensor(dense_n[test_idx], dtype=torch.float32)
    X_ti_te = torch.tensor(ti[test_idx], dtype=torch.long)
    X_si_te = torch.tensor(si[test_idx], dtype=torch.long)
    X_mi_te = torch.tensor(mi[test_idx], dtype=torch.long)
    y_te = torch.tensor(y[test_idx], dtype=torch.float32)

    ds = TensorDataset(X_dense_tr, X_ti_tr, X_si_tr, X_mi_tr, y_tr)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=True)

    # Loss: BCE (masking -1)
    bce = nn.BCELoss(reduction="none")

    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch in dl:
            d, t, s, m, yb = batch
            opt.zero_grad()
            pred = model(d, t, s, m)
            mask = (yb >= 0).float()
            yb_masked = torch.clamp(yb, 0.0, 1.0)
            loss = (bce(pred, yb_masked) * mask).sum() / max(mask.sum().item(), 1)
            loss.backward()
            opt.step()
            total_loss += loss.item()
        if epoch % 20 == 0 or epoch == epochs - 1:
            print(f"  epoch {epoch}: loss={total_loss/len(dl):.4f}")

    # 평가
    model.eval()
    with torch.no_grad():
        pred_te = model(X_dense_te, X_ti_te, X_si_te, X_mi_te).numpy()
    y_te_np = y_te.numpy()

    print(f"\n{'카테고리':<10} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4} {'P':>6} {'R':>6} {'F1':>6}")
    print("-" * 60)
    per_cat = {}
    for i, cat in enumerate(CATEGORIES):
        y_true = y_te_np[:, i]
        y_pred = (pred_te[:, i] >= 0.5).astype(float)
        mask = (y_true >= 0)
        yt = y_true[mask]; yp = y_pred[mask]
        tp = int(((yp == 1) & (yt == 1)).sum())
        fp = int(((yp == 1) & (yt == 0)).sum())
        fn = int(((yp == 0) & (yt == 1)).sum())
        tn = int(((yp == 0) & (yt == 0)).sum())
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        per_cat[cat] = dict(tp=tp, fp=fp, fn=fn, tn=tn, p=p, r=r, f1=f1)
        print(f"{cat:<10} {tp:>4} {fp:>4} {fn:>4} {tn:>4} {p:>6.3f} {r:>6.3f} {f1:>6.3f}")

    total = {k: sum(d[k] for d in per_cat.values()) for k in ("tp", "fp", "fn", "tn")}
    p = total["tp"] / max(total["tp"] + total["fp"], 1)
    r = total["tp"] / max(total["tp"] + total["fn"], 1)
    f1 = 2 * p * r / max(p + r, 1e-9)
    print("-" * 60)
    print(f"{'TOTAL':<10} {total['tp']:>4} {total['fp']:>4} {total['fn']:>4} {total['tn']:>4} "
          f"{p:>6.3f} {r:>6.3f} {f1:>6.3f}")

    # 모델 저장
    torch.save({
        "model_state": model.state_dict(),
        "n_dense": dense_n.shape[1],
        "hidden": list(hidden),
        "dropout": dropout,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
    }, "outputs/slm_torch_model.pt")
    return per_cat, total
