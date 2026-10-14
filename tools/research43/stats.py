"""Stage I definitions. Small fixtures test arithmetic, never hardware events."""
import numpy as np


def temporal(mask, t, left=0, right=12):
    """Closed 10s windows; onset is a transition, not a persistent positive."""
    x = np.asarray(mask, bool)
    if x.ndim != 1 or t < 12 or t + right >= len(x) or t + left < 1:
        raise ValueError('complete pre120 and closed evaluation window required')
    a, b = t + left, t + right + 1
    post_a = max(t, a)
    onsets = np.flatnonzero(x[post_a:b] & ~x[post_a-1:b-1]) + post_a
    fresh = not x[t-6:t].any()
    first = int(onsets[0]) if len(onsets) else None
    duration = None
    if first is not None:
        end = first
        while end < len(x) and x[end]:
            end += 1
        duration = (end - first) * 10
    return dict(any=bool(x[a:b].any()), pre120=bool(x[t-12:t].any()),
                pre60=not fresh, active_before=bool(x[t-1]),
                post_onset=first is not None, fresh_onset=bool(fresh and first is not None),
                pre_only=bool(x[a:t].any() and not x[t:b].any()),
                latency_seconds=(first-t)*10 if first is not None else None,
                onset_duration_seconds=duration,
                onset_run_censored=bool(first is not None and x[-1] and first+duration//10==len(x)))


def regime_duration(power, t, pre, post, direction):
    sign = 1 if direction == 'rise' else -1
    if sign * (post-pre) <= 0:
        return dict(seconds=None, censored=False)
    remains = sign * (np.asarray(power)[t:] - (pre+post)/2) > 0
    returns = np.flatnonzero(~remains)
    bins = int(returns[0]) if len(returns) else len(remains)
    return dict(seconds=bins*10, censored=not len(returns))


def cluster_ci(differences, labels, repeats=1999, seed=4301):
    """Resample whole clusters; event-weighted paired rate difference."""
    d, labels = np.asarray(differences, float), np.asarray(labels)
    if d.ndim != 1 or labels.shape != d.shape or not np.isfinite(d).all():
        raise ValueError('paired finite differences and cluster labels required')
    unique = np.unique(labels)
    if not len(d):
        return dict(n=0, clusters=0, difference=None, interval95=None)
    sums = np.array([d[labels == k].sum() for k in unique])
    counts = np.array([(labels == k).sum() for k in unique])
    draws = np.random.default_rng(seed).integers(0, len(unique), (repeats, len(unique)))
    values = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return dict(n=len(d), clusters=len(unique), difference=float(d.mean()),
                interval95=np.quantile(values, [.025,.975]).tolist(), repeats=repeats, seed=seed)


def control_center(t, h, component, pre_power, d1_edges, coverage, used, hour_bins=360):
    """Same host/hour/D1 decile, no strong-transition coverage in pre/post."""
    n = len(coverage)
    eligible = np.arange(max(12,(t//hour_bins)*hour_bins), min(n-19,(t//hour_bins+1)*hour_bins))
    edge = np.asarray(d1_edges)
    target = pre_power[t,h,component]
    target_decile = np.searchsorted(edge, target, side='right')
    csum = np.r_[0, np.cumsum(coverage[:,h], dtype=np.int64)]
    eligible = eligible[(csum[eligible+19]-csum[eligible-12]) == 0]
    eligible = eligible[np.searchsorted(edge,pre_power[eligible,h,component],side='right')==target_decile]
    eligible = np.array([v for v in eligible if (int(v),h) not in used],dtype=int)
    if not len(eligible):
        return None
    # Lexicographic: power mismatch, time distance, earliest timestamp.
    order = np.lexsort((eligible, np.abs(eligible-t), np.abs(pre_power[eligible,h,component]-target)))
    return int(eligible[order[0]])
