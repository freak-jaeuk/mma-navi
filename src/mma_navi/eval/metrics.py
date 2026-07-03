"""P/R/F1 메트릭 (AI30 증거물용). 외부 의존 없음.

- binary_prf: 한 클래스(예: 'refuse')에 대한 precision/recall/F1 (+Wilson 95% CI).
- classification_report: 다중 클래스 per-class P/R/F1 + macro-F1 + accuracy.
- wilson_ci: 이항 비율의 Wilson score 신뢰구간 — 소표본(n=12~22)에서 점추정만
  보고하지 않고 불확실성을 함께 노출하기 위함(정직성). 정규근사보다 소표본·극단비율
  에서 안정적이라 채택.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence


def _round(x: float, n: int = 3) -> float:
    return round(x, n)


def wilson_ci(k: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    """성공 k/시행 n 비율의 Wilson score 신뢰구간 [lo, hi] (기본 95%).

    n<=0이면 표본이 없어 구간을 정의할 수 없으므로 None.
    """
    if n <= 0:
        return None
    if k < 0 or k > n:
        raise ValueError("k는 0 <= k <= n 이어야 합니다")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return [_round(max(0.0, center - half)), _round(min(1.0, center + half))]


def binary_prf(y_true: Sequence, y_pred: Sequence, positive) -> Dict:
    """positive 클래스 기준 P/R/F1 (+tp/fp/fn, 표본수, Wilson 95% CI).

    recall_ci는 실제 positive(tp+fn) 기준, precision_ci는 예측 positive(tp+fp) 기준.
    분모가 0이면 해당 CI는 None(표본 없음).
    """
    if len(y_true) != len(y_pred):
        raise ValueError("y_true/y_pred 길이 불일치")
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == positive and p == positive)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t != positive and p == positive)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == positive and p != positive)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": _round(precision), "recall": _round(recall), "f1": _round(f1),
            "tp": tp, "fp": fp, "fn": fn, "n": len(y_true),
            "recall_ci": wilson_ci(tp, tp + fn),
            "precision_ci": wilson_ci(tp, tp + fp)}


def classification_report(y_true: Sequence, y_pred: Sequence,
                          labels: List) -> Dict:
    """다중 클래스 리포트: per-class P/R/F1, macro-F1, accuracy."""
    per = {c: binary_prf(y_true, y_pred, c) for c in labels}
    macro = sum(per[c]["f1"] for c in labels) / len(labels) if labels else 0.0
    acc = (sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)) if y_true else 0.0
    # labels 밖의 라벨(예: 분류기 '미상')을 투명하게 표시
    unknown = sorted((set(y_true) | set(y_pred)) - set(labels))
    return {"per_class": per, "macro_f1": _round(macro), "accuracy": _round(acc),
            "n": len(y_true), "unknown_labels": unknown}


def macro_f1(y_true: Sequence, y_pred: Sequence, labels: List) -> float:
    return classification_report(y_true, y_pred, labels)["macro_f1"]
