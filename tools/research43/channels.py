"""Research-only H1/H2 channels from the approved research 4.3 protocol."""
import numpy as np


_D1_START = np.datetime64('2022-01-18T00:00:00', 'ns').astype('int64')
_D1_END = np.datetime64('2022-01-18T08:00:00', 'ns').astype('int64')
_CADENCE = 10_000_000_000
_LAG = 60_000_000_000


def _timestamps(values, length):
    raw = np.asarray(values)
    if raw.ndim != 1 or raw.shape[0] != length:
        raise ValueError('timestamps must be one-dimensional and match T')
    if np.issubdtype(raw.dtype, np.datetime64):
        ts = raw.astype('datetime64[ns]').astype(np.int64)
    elif np.issubdtype(raw.dtype, np.integer):
        ts = raw.astype(np.int64)
    else:
        raise ValueError('timestamps must be datetime64 or integer nanoseconds')
    if (ts == np.iinfo(np.int64).min).any() or np.any(np.diff(ts) <= 0):
        raise ValueError('timestamps must be strictly increasing')
    return ts


def _d1(ts):
    return (ts >= _D1_START) & (ts < _D1_END)


def _hosts(hosts, count):
    values = np.asarray(hosts)
    if values.ndim != 1 or len(values) != count:
        raise ValueError('hosts must be one-dimensional and match H')
    result = [v.item() if isinstance(v, np.generic) else v for v in values]
    if any(not isinstance(v, (str, int, float, bool)) for v in result):
        raise ValueError('hosts must contain JSON scalar labels')
    if len(set(result)) != count:
        raise ValueError('host labels must be unique')
    return result


def _matrix(values, name, width=None):
    x = np.asarray(values, dtype=float)
    if x.ndim != 2 or (width is not None and x.shape[1] != width):
        raise ValueError(f'{name} must have shape [T,H]')
    return x


def _check_profile(profile, keys):
    if not isinstance(profile, dict) or any(k not in profile for k in keys):
        raise ValueError('invalid channel profile')
    if profile['version'] != 1 or not isinstance(profile['hosts'], list):
        raise ValueError('unsupported or malformed channel profile')


def fit_h1(scores, timestamps, hosts):
    """Calibrate per-host H1 thresholds on D1 using inverted-CDF Q99."""
    x = _matrix(scores, 'scores')
    ts = _timestamps(timestamps, len(x))
    labels = _hosts(hosts, x.shape[1])
    d1 = _d1(ts)
    if not d1.all():
        raise ValueError('calibration requires D1 timestamps only')
    if not d1.any() or not np.isfinite(x[d1]).all():
        raise ValueError('D1 scores must be present and finite')
    thresholds = np.quantile(x[d1], .99, axis=0, method='inverted_cdf')
    absolute = float(np.quantile(x[d1], .99, method='inverted_cdf'))
    return {'version': 1, 'hosts': labels,
            'host_threshold': [float(v) for v in thresholds],
            'absolute_threshold': absolute}


def h1(scores, profile):
    """Return raw absolute score and separate context and diagnostic flags."""
    x = _matrix(scores, 'scores')
    _check_profile(profile, ('host_threshold', 'absolute_threshold'))
    if len(profile['hosts']) != x.shape[1]:
        raise ValueError('profile host labels do not match score hosts')
    thresholds = np.asarray(profile['host_threshold'], dtype=float)
    if thresholds.shape != (x.shape[1],) or not np.isfinite(thresholds).all():
        raise ValueError('profile thresholds do not match score hosts')
    absolute_threshold = float(profile['absolute_threshold'])
    if not np.isfinite(absolute_threshold):
        raise ValueError('absolute threshold must be finite')
    valid = np.isfinite(x)
    return {'absolute': x.copy(),
            'context': valid & (x > thresholds[None, :]),
            'margin': np.where(valid, x - thresholds[None, :], np.nan),
            'absolute_flag': valid & (x > absolute_threshold), 'valid': valid}


def deltas(power, timestamps, available=None):
    """Compute 60-second deltas only across intact seven-sample windows."""
    p = np.asarray(power, dtype=float)
    if p.ndim != 3 or p.shape[2] != 3:
        raise ValueError('power must have shape [T,H,3]')
    ts = _timestamps(timestamps, len(p))
    if available is None:
        avail = np.ones(p.shape, dtype=bool)
    else:
        avail = np.asarray(available, dtype=bool)
        if avail.shape != p.shape:
            raise ValueError('available must match power shape [T,H,3]')
    out = np.full(p.shape, np.nan, dtype=float)
    valid = np.zeros(p.shape[:2], dtype=bool)
    for t in range(6, len(ts)):
        # Every cadence edge and sample in the closed 60-second interval counts.
        if ts[t] - ts[t - 6] != _LAG or not np.all(np.diff(ts[t-6:t+1]) == _CADENCE):
            continue
        window = p[t-6:t+1]
        good = avail[t-6:t+1].all(axis=(0, 2)) & np.isfinite(window).all(axis=(0, 2))
        out[t, good, :] = p[t, good, :] - p[t-6, good, :]
        valid[t, good] = True
    return out, valid


def fit_h2(delta, valid, timestamps, hosts):
    """Calibrate the fixed bidirectional H2 channel exclusively on D1."""
    d = np.asarray(delta, dtype=float)
    if d.ndim != 3 or d.shape[2] != 3:
        raise ValueError('delta must have shape [T,H,3]')
    v = np.asarray(valid, dtype=bool)
    if v.shape != d.shape[:2]:
        raise ValueError('valid must have shape [T,H]')
    ts = _timestamps(timestamps, len(d))
    labels = _hosts(hosts, d.shape[1])
    if not _d1(ts).all():
        raise ValueError('calibration requires D1 timestamps only')
    mask = _d1(ts)[:, None] & v & np.isfinite(d).all(axis=2)
    if not mask.any():
        raise ValueError('D1 must contain fully valid finite deltas')
    med = np.full((d.shape[1], 3), np.nan)
    mad = np.full_like(med, np.nan)
    pool = d[mask]
    epsilon = np.maximum(1., np.quantile(np.abs(pool), .5, axis=0, method='inverted_cdf'))
    for h in range(d.shape[1]):
        values = d[mask[:, h], h, :]
        if len(values):
            med[h] = np.median(values, axis=0)
            mad[h] = np.median(np.abs(values - med[h]), axis=0)
    if not np.isfinite(med).all() or not np.isfinite(mad).all():
        raise ValueError('every host requires fully valid finite D1 deltas')
    scale = np.maximum(1.4826 * mad, epsilon[None, :])
    pooled_u = ((d - med[None, :, :]) / scale[None, :, :])[mask]
    pos = np.max(np.maximum(pooled_u, 0), axis=1)
    neg = np.max(np.maximum(-pooled_u, 0), axis=1)
    return {'version': 1, 'hosts': labels, 'median': med.tolist(), 'MAD': mad.tolist(),
            'scale': scale.tolist(), 'epsilon': epsilon.tolist(),
            'positive_threshold': float(np.quantile(pos, .995, method='inverted_cdf')),
            'negative_threshold': float(np.quantile(neg, .995, method='inverted_cdf'))}


def h2(delta, valid, profile):
    """Score H2 with separate strict positive and negative pooled flags."""
    d = np.asarray(delta, dtype=float)
    if d.ndim != 3 or d.shape[2] != 3:
        raise ValueError('delta must have shape [T,H,3]')
    v = np.asarray(valid, dtype=bool)
    if v.shape != d.shape[:2]:
        raise ValueError('valid must have shape [T,H]')
    _check_profile(profile, ('median', 'MAD', 'scale', 'epsilon',
                             'positive_threshold', 'negative_threshold'))
    med, mad, scale = (np.asarray(profile[k], dtype=float) for k in ('median', 'MAD', 'scale'))
    eps = np.asarray(profile['epsilon'], dtype=float)
    if med.shape != (d.shape[1], 3) or mad.shape != med.shape or scale.shape != med.shape or eps.shape != (3,):
        raise ValueError('profile arrays do not match delta hosts')
    if len(profile['hosts']) != d.shape[1]:
        raise ValueError('profile host labels do not match delta hosts')
    if not all(np.isfinite(a).all() for a in (med, mad, scale, eps)) or (mad < 0).any() or (eps < 1).any():
        raise ValueError('profile arrays must be finite with positive scales')
    if not np.array_equal(scale, np.maximum(1.4826 * mad, eps[None, :])):
        raise ValueError('profile scales violate fixed MAD/epsilon rule')
    pt, nt = float(profile['positive_threshold']), float(profile['negative_threshold'])
    if not np.isfinite([pt, nt]).all() or min(pt, nt) < 0:
        raise ValueError('profile thresholds must be finite')
    good = v & np.isfinite(d).all(axis=2)
    u = (d - med[None, :, :]) / scale[None, :, :]
    u[~good] = np.nan
    positive_score = np.max(np.maximum(u, 0), axis=2)
    negative_score = np.max(np.maximum(-u, 0), axis=2)
    positive = good & (positive_score > pt)
    negative = good & (negative_score > nt)
    return {'u': u, 'positive': np.where(good, positive_score, np.nan),
            'negative': np.where(good, negative_score, np.nan),
            'positive_flag': positive, 'negative_flag': negative, 'valid': good}
