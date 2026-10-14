"""Research statistics only; no detector, threshold tuning or model fitting."""
import numpy as np


def average_ranks(values):
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ValueError("ranks require a nonempty finite vector")
    order = np.argsort(x, kind="stable")
    ordered = x[order]
    starts = np.r_[0, np.flatnonzero(ordered[1:] != ordered[:-1]) + 1]
    ends = np.r_[starts[1:], len(x)]
    ranks = np.empty(len(x))
    ranks[order] = np.repeat((starts + ends + 1) / 2, ends - starts)
    return ranks


def pearson(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or not len(x) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("correlation requires paired finite vectors")
    x, y = x - x.mean(), y - y.mean()
    denominator = np.sqrt(np.dot(x, x) * np.dot(y, y))
    return float(np.dot(x, y) / denominator) if denominator else None


def pr_curve(scores, labels):
    scores, labels = np.asarray(scores, dtype=float), np.asarray(labels, dtype=bool)
    if scores.ndim != 1 or scores.shape != labels.shape or not len(scores) or not np.isfinite(scores).all():
        raise ValueError("PR requires paired finite scores and labels")
    order = np.argsort(-scores, kind="stable")
    ordered, positive = scores[order], labels[order]
    ends = np.r_[np.flatnonzero(ordered[:-1] != ordered[1:]), len(scores) - 1]
    tp = np.cumsum(positive, dtype=np.int64)[ends]
    precision = np.r_[1., tp / (ends + 1)]
    total = int(labels.sum())
    recall = np.r_[0., tp / total] if total else np.zeros(len(ends) + 1)
    ap = float(np.dot(np.diff(recall), precision[1:])) if total else None
    return {"thresholds": ordered[ends], "precision": precision, "recall": recall,
            "average_precision": ap, "prevalence": total / len(scores),
            "trapezoidal_pr_area": float(np.trapezoid(precision, recall)) if total else None}


def linear_runs(mask):
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 1:
        raise ValueError("runs require a vector")
    transitions = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(transitions == 1).tolist(), np.flatnonzero(transitions == -1).tolist()))


def coincidence_metrics(binary):
    x = np.asarray(binary, dtype=bool)
    if x.ndim != 3 or not all(x.shape):
        raise ValueError("coincidence requires time x groups x hosts")
    counts = x.sum(axis=2, dtype=np.int64)
    result = np.zeros((x.shape[1], 4), dtype=np.int64)
    result[:, 0] = (counts * (counts - 1) // 2).sum(axis=0)
    result[:, 1] = (counts >= 2).sum(axis=0)
    result[:, 2] = (counts >= 3).sum(axis=0)
    for g in range(x.shape[1]):
        result[g, 3] = max((end - start for start, end in linear_runs(counts[:, g] >= 2)), default=0)
    return result


def circular_shift(binary, offsets):
    x = np.asarray(binary, dtype=bool)
    offsets = np.asarray(offsets)
    if x.ndim != 3 or not all(x.shape) or offsets.shape != x.shape[1:] or not np.issubdtype(offsets.dtype, np.integer):
        raise ValueError("offsets must match group x host integer shape")
    indices = (np.arange(x.shape[0])[:, None, None] - offsets[None, :, :]) % x.shape[0]
    return np.take_along_axis(x, indices, axis=0)


def shift_control(binary, repeats, seed):
    x = np.asarray(binary, dtype=bool)
    if x.ndim != 3 or not all(x.shape) or repeats < 1:
        raise ValueError("control requires nonempty series and positive repeats")
    rng = np.random.default_rng(seed)
    controls = np.empty((repeats, x.shape[1], 4), dtype=np.int64)
    for i in range(repeats):
        shifted = circular_shift(x, rng.integers(0, x.shape[0], size=x.shape[1:]))
        controls[i] = coincidence_metrics(shifted)
    return controls


def empirical_tail(actual, controls):
    values = np.asarray(controls, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or not np.isfinite(actual):
        raise ValueError("empirical test requires finite controls")
    mean = float(values.mean())
    return {"actual": float(actual), "control_mean": mean,
            "control_interval_95": np.quantile(values, [.025, .975]).tolist(),
            "effect_difference": float(actual - mean),
            "effect_ratio": float(actual / mean) if mean else None,
            "p_greater_equal": (1 + int(np.count_nonzero(values >= actual))) / (len(values) + 1),
            "repeats": len(values)}


def holm(pvalues):
    p = np.asarray(pvalues, dtype=float)
    if p.ndim != 1 or not len(p) or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise ValueError("Holm requires p-values in [0,1]")
    order = np.argsort(p)
    adjusted = np.empty(len(p))
    adjusted[order] = np.minimum(1, np.maximum.accumulate(p[order] * np.arange(len(p), 0, -1)))
    return adjusted
