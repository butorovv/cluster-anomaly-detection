"""D2-only diagnostics of immutable A/B/C/D profiles. No model fitting.

Inputs are the research export made by the existing Go models. All large
derived arrays stay in the ignored output directory; only report figures
and descriptive tables are intended for review in Git.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from diagnostic_stats import average_ranks, pearson, pr_curve, linear_runs
from diagnostic_stats import coincidence_metrics, shift_control, empirical_tail, holm

DTYPE = np.dtype([("timestamp", "<i8"), ("host", "<u4"), ("available", "<u4"),
                  ("features", "<f8", (18,)), ("score", "<f8"), ("distance", "<f8")])
CATEGORY_NAMES = ["TN", "FP", "FN", "TP"]
METRIC_NAMES = ["pair_bins", "bins_ge2", "bins_ge3", "longest_ge2_bins"]


def dump(path, value):
    with Path(path).open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def describe(values):
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if not len(x):
        return {"count": 0}
    q = np.quantile(x, [.01, .25, .5, .75, .95, .99], method="inverted_cdf")
    return dict(count=len(x), min=float(x.min()), max=float(x.max()), mean=float(x.mean()),
                std=float(x.std()), q01=float(q[0]), q25=float(q[1]), q50=float(q[2]),
                q75=float(q[3]), q95=float(q[4]), q99=float(q[5]))


def eta_host(values):
    total = float(np.var(values))
    return float(np.var(values.mean(axis=0)) / total) if total else None


def save_figure(fig, directory, name):
    fig.tight_layout()
    fig.savefig(directory / f"{name}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=Path("results/d2-diagnostics-v1"))
    parser.add_argument("--figures", type=Path, default=Path("docs/figures/d2-diagnostics"))
    parser.add_argument("--repeats", type=int, default=1999)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.repeats < 200:
        raise ValueError("at least 200 cyclic-shift controls are required")
    started = time.perf_counter()
    meta = json.loads((args.export / "metadata.json").read_text(encoding="utf-8"))
    with (args.export / "states.bin").open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == meta["binary_sha256"]
    assert DTYPE.itemsize == meta["record_bytes"] == 176
    data = np.memmap(args.export / "states.bin", dtype=DTYPE, mode="r")
    assert len(data) == meta["rows"] == 829440
    source, stat, phys = meta["source"], meta["statistical_profile"], meta["physical_profile"]
    names, hosts, groups = meta["features"], source["hosts"], source["groups"]
    ntime, nhost = 2880, 288
    assert len(hosts) == nhost and len(groups) == 16
    assert np.array_equal(data["host"], np.tile(np.arange(nhost), ntime))
    ts = data["timestamp"].reshape(ntime, nhost)
    assert (ts == ts[:, :1]).all() and (np.diff(ts[:, 0]) == 10_000_000).all()
    assert ts[0, 0] == np.datetime64("2022-01-18T08:00:00", "us").astype("int64")
    assert ts[-1, 0] == np.datetime64("2022-01-18T15:59:50", "us").astype("int64")
    available = data["available"].reshape(ntime, nhost).astype(bool)
    if not available.all():
        raise ValueError("this complete-grid diagnostic requires available D2 states")
    x = data["features"].reshape(ntime, nhost, 18)
    scores = np.array(data["score"]).reshape(ntime, nhost)
    distances = np.array(data["distance"]).reshape(ntime, nhost)
    theta = meta["calibration"]["calibration"]["theta_if"]
    theta_m = stat["mahalanobis_squared_threshold_q99"]
    firing, control = scores > theta, distances > theta_m
    categories = firing.astype(np.int8) + 2 * control
    count = np.bincount(categories.ravel(), minlength=4)
    assert count.tolist() == [809320, 10240, 7273, 2607]
    args.figures.mkdir(parents=True, exist_ok=True)
    report = {"versions": {m: importlib.metadata.version(m) for m in ["numpy", "matplotlib"]},
              "seed": args.seed, "states": len(data), "theta_if": theta, "theta_mahalanobis": theta_m,
              "source": source, "input_sha256": meta["input_sha256"],
              "confusion": dict(tp=int(count[3]), fp=int(count[1]), fn=int(count[2]), tn=int(count[0])),
              "score_distribution": describe(scores), "distance_distribution": describe(distances),
              "categories": {}}
    print("Baseline reproduced; computing score relationships", flush=True)
    score_rank, distance_rank = average_ranks(scores.ravel()), average_ranks(distances.ravel())
    report["correlations"] = {"pearson": pearson(scores.ravel(), distances.ravel()),
                              "spearman": pearson(score_rank, distance_rank),
                              "pearson_log1p_distance": pearson(scores.ravel(), np.log1p(distances.ravel()))}
    pr = pr_curve(scores.ravel(), control.ravel())
    report["ranking"] = {k: pr[k] for k in ["average_precision", "prevalence", "trapezoidal_pr_area"]}
    rng = np.random.default_rng(args.seed)
    random_ap = [pr_curve(rng.random(len(data)), control.ravel())["average_precision"] for _ in range(20)]
    report["ranking"]["random_ap_20"] = describe(random_ap)
    report["ranking"]["ap_over_prevalence"] = pr["average_precision"] / pr["prevalence"]
    for k, name in enumerate(CATEGORY_NAMES):
        selection = categories == k
        report["categories"][name] = {"score": describe(scores[selection]), "distance": describe(distances[selection])}

    # Descriptive host means on D2, not newly trained normalization/baselines.
    host_levels = np.array(x.mean(axis=0))
    max_abs = np.zeros((ntime, nhost))
    dominant = np.zeros((ntime, nhost), dtype=np.int16)
    features = []
    for j, name in enumerate(names):
        raw = x[:, :, j]
        z = (raw - stat["median"][j]) / stat["effective_scale"][j]
        greater = np.abs(z) > max_abs
        max_abs[greater], dominant[greater] = np.abs(z[greater]), j
        features.append({"name": name, "host_mean_min": float(host_levels[:, j].min()),
                         "host_mean_max": float(host_levels[:, j].max()),
                         "host_mean_std": float(host_levels[:, j].std()), "between_host_variance_share": eta_host(raw),
                         "rho_host_level_mean_if": pearson(average_ranks(host_levels[:, j]), average_ranks(scores.mean(axis=0))),
                         "rho_within_host_if": pearson((raw - host_levels[:, j]).ravel(), (scores - scores.mean(axis=0)).ravel())})
    report["features"] = features
    report["score_vs_max_abs_z"] = {"pearson": pearson(scores.ravel(), max_abs.ravel()),
                                  "spearman": pearson(score_rank, average_ranks(max_abs.ravel()))}
    covariance = np.array(stat["covariance"])
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    assert (eigenvalues > 0).all()
    low_mode_share = np.empty(len(data))
    dominant_maha = np.empty(len(data), dtype=np.int16)
    maximum_d2_difference = 0.
    inverse = np.array(stat["pseudoinverse"])
    for first in range(0, len(data), 8192):
        last = min(first + 8192, len(data))
        z = (data["features"][first:last] - stat["median"]) / stat["effective_scale"]
        centered = z - stat["normalized_mean"]
        q = centered * (centered @ inverse)
        maximum_d2_difference = max(maximum_d2_difference, float(np.max(np.abs(q.sum(axis=1) - data["distance"][first:last]))))
        modes = (centered @ eigenvectors) ** 2 / eigenvalues
        low_mode_share[first:last] = modes[:, :3].sum(axis=1) / modes.sum(axis=1)
        dominant_maha[first:last] = np.abs(q).argmax(axis=1)
    report["mahalanobis_geometry"] = {"eigenvalues": eigenvalues.tolist(), "numpy_go_max_absolute_difference": maximum_d2_difference,
        "smallest_mode_loadings": [{"eigenvalue": float(eigenvalues[k]), "coordinates": [{"name": names[j], "loading": float(eigenvectors[j, k])} for j in np.argsort(-np.abs(eigenvectors[:, k]))[:5]]} for k in range(3)]}
    for k, name in enumerate(CATEGORY_NAMES):
        selected = categories.ravel() == k
        report["categories"][name].update(max_abs_z=describe(max_abs.ravel()[selected]),
            lowest3_mode_fraction=describe(low_mode_share[selected]),
            dominant_z_counts=np.bincount(dominant.ravel()[selected], minlength=18).tolist(),
            dominant_mahalanobis_counts=np.bincount(dominant_maha[selected], minlength=18).tolist())

    host_summary = []
    for h, hostname in enumerate(hosts):
        group = hostname[:3]
        assert group == groups[h // 18]
        rates_hourly = firing[:, h].reshape(8, 360).mean(axis=1)
        host_summary.append({"hostname": hostname, "group": group, "available": int(available[:, h].sum()),
            "if_count": int(firing[:, h].sum()), "control_count": int(control[:, h].sum()),
            "if_rate": float(firing[:, h].mean()), "control_rate": float(control[:, h].mean()),
            "tp": int((categories[:, h] == 3).sum()), "fp": int((categories[:, h] == 1).sum()),
            "fn": int((categories[:, h] == 2).sum()), "tn": int((categories[:, h] == 0).sum()),
            "score_mean": float(scores[:, h].mean()), "score_std": float(scores[:, h].std()),
            "distance_mean": float(distances[:, h].mean()), "hourly_if_rates": rates_hourly.tolist(),
            "longest_if_run_seconds": 10 * max((b - a for a, b in linear_runs(firing[:, h])), default=0),
            "feature_means": host_levels[h].tolist()})
    report["hosts"] = host_summary
    order = np.argsort(-firing.sum(axis=0), kind="stable")
    report["heterogeneity"] = {"score_between_host_variance_share": eta_host(scores), "distance_between_host_variance_share": eta_host(distances),
        "hosts_with_any_if": int(firing.any(axis=0).sum()), "hosts_firing_all_d2": [hosts[h] for h in range(nhost) if firing[:, h].all()],
        "if_fraction_top3": float(firing[:, order[:3]].sum() / firing.sum()),
        "if_fraction_top4": float(firing[:, order[:4]].sum() / firing.sum()),
        "if_fraction_top10": float(firing[:, order[:10]].sum() / firing.sum()),
        "if_fraction_hosts_rate_gt_half": float(firing[:, firing.mean(axis=0) > .5].sum() / firing.sum()),
        "top4_counts": {name: int((categories[:, order[:4]] == k).sum()) for k, name in enumerate(CATEGORY_NAMES)}}
    report["hourly"] = [{"hour_utc": 8 + hour, "if_count": int(firing[hour*360:(hour+1)*360].sum()),
                         "control_count": int(control[hour*360:(hour+1)*360].sum())} for hour in range(8)]

    # Deterministic extreme and central examples, before inspecting physical residuals.
    examples = []
    discrepancy = (score_rank - distance_rank).reshape(ntime, nhost) / len(data)
    for code in [3, 1, 2]:
        candidates = np.flatnonzero(categories.ravel() == code)
        values = scores.ravel() if code != 2 else distances.ravel()
        target = np.median(values[candidates])
        criterion = discrepancy.ravel() if code == 1 else distances.ravel() if code == 3 else -scores.ravel()
        picks = [int(candidates[np.argmax(values[candidates])])]
        remaining = candidates[candidates != picks[0]]
        picks.append(int(remaining[np.argmax(criterion[remaining])]))
        remaining = candidates[~np.isin(candidates, picks)]
        picks.append(int(remaining[np.argmin(np.abs(values[remaining] - target))]))
        for purpose, index in zip(["maximum", "disagreement", "category_median"], picks):
            t, h = divmod(index, nhost)
            z = (x[t, h] - stat["median"]) / stat["effective_scale"]
            examples.append({"category": CATEGORY_NAMES[code], "purpose": purpose, "index": index,
                "timestamp": str(np.datetime64(int(ts[t, h]), "us")) + "Z", "hostname": hosts[h], "group": hosts[h][:3],
                "score": float(scores[t, h]), "distance": float(distances[t, h]), "features": x[t, h].tolist(),
                "largest_normalized": [{"name": names[j], "z": float(z[j]), "raw": float(x[t, h, j])} for j in np.argsort(-np.abs(z))[:5]]})
    report["examples"] = examples

    # Reproduce frozen physical predictions, never fit. First D2 timestamp is unavailable.
    residual = np.full((ntime, nhost, 8), np.nan)
    persistence = np.full_like(residual, np.nan)
    for component in range(8):
        model = phys["cpu"] if component < 2 else phys["gpu"]
        forecast = model["a"] * x[:-1, :, 10+component] + model["b_celsius_per_watt"] * x[:-1, :, 2+component] + model["c_celsius"]
        residual[1:, :, component] = x[1:, :, 10+component] - forecast
        persistence[1:, :, component] = x[1:, :, 10+component] - x[:-1, :, 10+component]
    psu = x[:, :, :2].sum(axis=2) - (phys["psu"]["beta_0_watt"] + phys["psu"]["beta_1"] * x[:, :, 2:10].sum(axis=2))
    report["physical"] = {"components": [], "psu": describe(psu)}
    for component in range(8):
        e, baseline = residual[1:, :, component], persistence[1:, :, component]
        report["physical"]["components"].append({"component": ("CPU" + str(component)) if component < 2 else "GPU" + str(component-2),
            "mean": float(e.mean()), "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e*e).mean())),
            "persistence_mae": float(np.abs(baseline).mean()), "between_host_bias_share": eta_host(e)})
    report["physical"]["category_residuals"] = {}
    for k, name in enumerate(CATEGORY_NAMES):
        mask = categories == k
        report["physical"]["category_residuals"][name] = {"cpu_abs_mean": float(np.nanmean(np.abs(residual[:, :, :2][mask]))),
            "gpu_abs_mean": float(np.nanmean(np.abs(residual[:, :, 2:][mask]))), "psu_abs_mean": float(np.abs(psu[mask]).mean())}
    cpu_mae = float(np.abs(residual[1:, :, :2]).mean())
    gpu_mae = float(np.abs(residual[1:, :, 2:]).mean())
    report["physical"].update(cpu_mae=cpu_mae, gpu_mae=gpu_mae, psu_mae=float(np.abs(psu).mean()))
    assert abs(cpu_mae - .11906485522312701) < 1e-12
    assert abs(gpu_mae - .29601235757354444) < 1e-12
    assert abs(np.abs(psu).mean() - 127.72703358937915) < 1e-10

    grouped = firing.reshape(ntime, 16, 18)
    group_counts = grouped.sum(axis=2)
    observed = coincidence_metrics(grouped)
    print(f"Starting {args.repeats} independent cyclic-shift controls (seed {args.seed})", flush=True)
    controls = shift_control(grouped, args.repeats, args.seed)
    np.savez_compressed(args.export / "shift_controls.npz", metrics=controls, observed=observed,
                        seed=args.seed, binary_sha256=meta["binary_sha256"])
    adjustment = holm(np.array([[empirical_tail(observed[g, j], controls[:, g, j])["p_greater_equal"] for j in range(4)] for g in range(16)]).ravel()).reshape(16, 4)
    report["groups"] = []
    for g, name in enumerate(groups):
        c = group_counts[:, g]
        runs = linear_runs(c >= 2)
        result = {"group": name, "available_per_timestamp": 18, "if_count": int(c.sum()), "if_rate": float(c.sum() / (ntime*18)),
            "control_count": int(control[:, g*18:(g+1)*18].sum()), "support": describe(c / 18),
            "simultaneous_count_histogram": np.bincount(c, minlength=19).tolist(), "exactly2_bins": int((c == 2).sum()),
            "exactly3_bins": int((c == 3).sum()), "ge2_run_durations_seconds": describe([10*(b-a) for a,b in runs]),
            "ge2_runs": len(runs), "control": {}}
        for j, metric in enumerate(METRIC_NAMES):
            result["control"][metric] = empirical_tail(observed[g, j], controls[:, g, j])
            result["control"][metric]["p_holm_64"] = float(adjustment[g, j])
        report["groups"].append(result)
    report["global_control"] = {METRIC_NAMES[j]: empirical_tail(observed[:, j].sum() if j < 3 else observed[:, j].max(),
        controls[:, :, j].sum(axis=1) if j < 3 else controls[:, :, j].max(axis=1)) for j in range(4)}
    secondary = shift_control(grouped, 499, args.seed + 1)
    report["global_control_seed43_499"] = {METRIC_NAMES[j]: empirical_tail(observed[:, j].sum() if j < 3 else observed[:, j].max(),
        secondary[:, :, j].sum(axis=1) if j < 3 else secondary[:, :, j].max(axis=1)) for j in range(4)}
    report["pair_control_seed43_499"] = [empirical_tail(observed[g,0],secondary[:,g,0]) for g in range(16)]
    probabilities = grouped.mean(axis=0)
    report["analytic_shift_expectations"] = []
    for g in range(16):
        distribution = np.array([1.])
        for probability in probabilities[g]:
            distribution = np.convolve(distribution,[1-probability,probability])
        k = np.arange(19)
        report["analytic_shift_expectations"].append({"group":groups[g],
            "pair_bins":float(ntime*np.dot(k*(k-1)/2,distribution)),
            "bins_ge2":float(ntime*distribution[2:].sum()),"bins_ge3":float(ntime*distribution[3:].sum())})
    # Quantify topology enrichment against random partitions while retaining time synchrony.
    all_counts = firing.sum(axis=1)
    expected_partition_pairs = float((all_counts*(all_counts-1)/2).sum() * 17/287)
    partition_control = np.array([coincidence_metrics(firing[:, rng.permutation(nhost)].reshape(ntime,16,18))[:,0].sum() for _ in range(499)])
    report["random_partition_control"] = empirical_tail(observed[:,0].sum(), partition_control)
    report["random_partition_control"]["analytic_expected_pairs"] = expected_partition_pairs

    print("Selecting physical intervals and rendering figures", flush=True)
    # Preserve numerical results even if plotting fails; figures never define
    # or influence the metrics or the fixed selection rules.
    dump(args.export/"summary.json",report)
    interior = np.zeros_like(firing); interior[30:-30] = True
    counts_interior = group_counts.copy(); counts_interior[:30] = -1; counts_interior[-30:] = -1
    t_joint, g_joint = np.unravel_index(np.argmax(counts_interior), counts_interior.shape)
    joint_hosts = np.flatnonzero(grouped[t_joint,g_joint]) + 18*g_joint
    h_joint = int(joint_hosts[np.argmax(scores[t_joint,joint_hosts])])
    intervals = [("joint", int(t_joint), h_joint)]
    for name, code, values in [("FP",1,scores),("FN",2,distances)]:
        indices = np.flatnonzero((categories == code) & interior)
        index = int(indices[np.argmax(values.ravel()[indices])]); t,h=divmod(index,nhost);intervals.append((name,t,h))
    host_bad = np.vstack([np.zeros((1,nhost),dtype=int),np.cumsum(categories!=0,axis=0)])
    group_bad = np.vstack([np.zeros((1,16),dtype=int),np.cumsum(group_counts>0,axis=0)])
    quiet = (host_bad[61:]-host_bad[:-61]==0) & np.repeat(group_bad[61:]-group_bad[:-61]==0,18,axis=1)
    quiet_t,quiet_h=np.unravel_index(rng.choice(np.flatnonzero(quiet)),quiet.shape)
    intervals.append(("control",int(quiet_t)+30,int(quiet_h)))
    report["intervals"] = []
    fig, axes = plt.subplots(4, 3, figsize=(16, 14))
    for row,(name,t,h) in enumerate(intervals):
        z = (x[t,h,10:] - np.array(stat["median"])[10:]) / np.array(stat["effective_scale"])[10:]
        component = int(np.argmax(np.abs(z)));first,last=t-30,t+31
        minute = (np.arange(first,last)-t)/6
        actual = x[first:last,h,10+component]
        forecast = actual-residual[first:last,h,component]
        axes[row,0].plot(minute,actual,label="actual T",lw=1.5);axes[row,0].plot(minute,forecast,label="frozen prediction",lw=1)
        power_axis=axes[row,0].twinx();power_axis.plot(minute,x[first:last,h,2+component],color="gray",alpha=.45,label="P (W)")
        axes[row,0].set_ylabel("Temperature (°C)");power_axis.set_ylabel("Power (W)")
        axes[row,0].legend(loc="upper left",fontsize=7)
        axes[row,1].plot(minute,residual[first:last,h,component],color="tab:red",label="thermal residual (°C)")
        residual_axis=axes[row,1].twinx();residual_axis.plot(minute,psu[first:last,h],color="tab:purple",alpha=.6,label="PSU residual (W)")
        axes[row,1].set_ylabel("Residual (°C)");residual_axis.set_ylabel("PSU residual (W)")
        axes[row,2].plot(minute,scores[first:last,h],label="IF score");axes[row,2].axhline(theta,color="tab:blue",ls="--",lw=.8)
        distance_axis=axes[row,2].twinx();distance_axis.plot(minute,distances[first:last,h],color="tab:orange",label="D²");distance_axis.axhline(theta_m,color="tab:orange",ls="--",lw=.8)
        axes[row,2].set_ylabel("IF score");distance_axis.set_ylabel("D²")
        for ax in axes[row]:ax.axvline(0,color="black",ls=":",lw=.8);ax.set_xlabel("Minutes from selected point");ax.grid(alpha=.2)
        component_name=("CPU"+str(component)) if component<2 else "GPU"+str(component-2)
        timestamp=str(np.datetime64(int(ts[t,h]),"us"))+"Z"
        axes[row,0].set_title(f"{name}: {hosts[h]} / {component_name}\n{timestamp}",fontsize=9)
        case = {"kind":name,"timestamp":timestamp,"hostname":hosts[h],"component":component_name,
            "index":t*nhost+h,"group":hosts[h][:3],"simultaneous_at_point":int(group_counts[t,h//18]),
            "score":float(scores[t,h]),"distance":float(distances[t,h]),"raw":x[t,h].tolist(),
            "pre_300s":{"temperature":describe(x[t-30:t,h,10+component]),"power":describe(x[t-30:t,h,2+component]),
                        "thermal_residual":describe(residual[t-30:t,h,component]),"psu_residual":describe(psu[t-30:t,h])},
            "point_and_next_300s":{"temperature":describe(x[t:t+31,h,10+component]),"power":describe(x[t:t+31,h,2+component]),
                        "thermal_residual":describe(residual[t:t+31,h,component]),"psu_residual":describe(psu[t:t+31,h])}}
        case["component_residuals"]=[{"component":("CPU"+str(c)) if c<2 else "GPU"+str(c-2),
            "pre_mean":float(residual[t-30:t,h,c].mean()),"post_mean":float(residual[t:t+31,h,c].mean()),
            "pre_mae":float(np.abs(residual[t-30:t,h,c]).mean()),"post_mae":float(np.abs(residual[t:t+31,h,c]).mean()),
            "at_point":float(residual[t,h,c])} for c in range(8)]
        report["intervals"].append(case)
    t,g=t_joint,g_joint
    pre=x[t-30:t,g*18:(g+1)*18].mean(axis=0)
    post=x[t:t+31,g*18:(g+1)*18].mean(axis=0)
    report["joint_physical_group"]={"group":groups[g],"timestamp":str(np.datetime64(int(ts[t,0]),"us"))+"Z",
        "gpu0_power_change_host_distribution":describe(post[:,4]-pre[:,4]),
        "gpu0_temperature_change_host_distribution":describe(post[:,12]-pre[:,12]),
        "gpu0_power_decreased_hosts":int((post[:,4]<pre[:,4]).sum()),
        "gpu0_temperature_decreased_hosts":int((post[:,12]<pre[:,12]).sum())}
    save_figure(fig,args.figures,"physical-intervals")

    fig,axes=plt.subplots(2,2,figsize=(12,9))
    for k,name in enumerate(CATEGORY_NAMES):
        axes[0,0].hist(scores[categories==k],bins=60,histtype="step",density=True,label=name)
        axes[0,1].hist(np.log10(distances[categories==k]),bins=60,histtype="step",density=True,label=name)
    axes[0,0].axvline(theta,color="black",ls="--");axes[0,0].set_xlabel("IF score")
    axes[0,1].axvline(np.log10(theta_m),color="black",ls="--");axes[0,1].set_xlabel("log10 D²")
    sampled=rng.choice(len(data),40000,replace=False)
    axes[1,0].scatter(scores.ravel()[sampled],distances.ravel()[sampled],s=2,c=categories.ravel()[sampled],
        cmap=ListedColormap(["tab:blue","tab:orange","tab:green","tab:red"]),vmin=0,vmax=3,alpha=.25)
    axes[1,0].set_yscale("log");axes[1,0].axvline(theta,color="black",ls="--");axes[1,0].axhline(theta_m,color="black",ls="--")
    axes[1,0].set_xlabel("IF score (40,000 uniform states, seeded)");axes[1,0].set_ylabel("D² (log scale)")
    axes[1,1].plot(pr["recall"],pr["precision"],label=f"IF AP={pr['average_precision']:.4f}")
    axes[1,1].axhline(pr["prevalence"],color="gray",ls="--",label=f"prevalence={pr['prevalence']:.4f}")
    cm=report["confusion"];axes[1,1].scatter([cm["tp"]/(cm["tp"]+cm["fn"])],[cm["tp"]/(cm["tp"]+cm["fp"])],color="red",label="frozen D2 threshold")
    axes[1,1].set_xlabel("Recall_ref");axes[1,1].set_ylabel("Precision_ref");axes[1,1].set_ylim(0,1)
    for ax in axes.ravel():
        if ax.get_legend_handles_labels()[0]: ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    save_figure(fig,args.figures,"scores-and-pr")

    fig,axes=plt.subplots(2,1,figsize=(14,9))
    axes[0].plot(np.arange(nhost),firing.mean(axis=0)*100,".",label="IF");axes[0].plot(np.arange(nhost),control.mean(axis=0)*100,".",label="Mahalanobis")
    axes[0].set_ylabel("Host firing rate (%)");axes[0].legend();axes[0].grid(alpha=.2)
    for rank,h in enumerate(order[:4]):
        axes[0].annotate(hosts[h],(h,firing[:,h].mean()*100),xytext=(h+12,85-rank*12),fontsize=8,
            arrowprops={"arrowstyle":"-","color":"gray","lw":.6})
    heat=firing.reshape(96,30,nhost).mean(axis=1).T
    im=axes[1].imshow(heat,aspect="auto",extent=[8,16,288,0],cmap="magma",vmin=0,vmax=1)
    axes[1].set_xlabel("UTC hour (5-minute bins)");axes[1].set_ylabel("Host index, grouped a01–a16");fig.colorbar(im,ax=axes[1],label="IF fraction")
    save_figure(fig,args.figures,"hosts-and-time")

    fig,axes=plt.subplots(2,2,figsize=(13,9))
    for ax,j in zip(axes.ravel()[:3],[10,12,4]):
        ax.scatter(host_levels[:,j],scores.mean(axis=0),s=12,alpha=.6)
        for rank,h in enumerate(order[:4]):
            ax.annotate(hosts[h],(host_levels[h,j],scores[:,h].mean()),fontsize=7,xytext=(8,-8-12*rank),
                textcoords="offset points",arrowprops={"arrowstyle":"-","color":"gray","lw":.6})
        ax.set_xlabel(f"D2 host mean {names[j]}");ax.set_ylabel("Host mean IF score");ax.grid(alpha=.2)
    axes[1,1].bar(np.arange(18),[f["between_host_variance_share"] for f in features]);axes[1,1].set_xticks(np.arange(18),names,rotation=90,fontsize=7);axes[1,1].set_ylabel("Between-host variance / total D2 variance")
    save_figure(fig,args.figures,"heterogeneity")

    fig,axes=plt.subplots(2,1,figsize=(13,9))
    im=axes[0].imshow((group_counts.reshape(96,30,16).mean(axis=1)/18).T,aspect="auto",extent=[8,16,16,0],cmap="viridis",vmin=0)
    axes[0].set_yticks(np.arange(16)+.5,groups);axes[0].set_xlabel("UTC hour");fig.colorbar(im,ax=axes[0],label="mean support in 5-minute bin")
    means=controls[:,:,0].mean(axis=0);bounds=np.quantile(controls[:,:,0],[.025,.975],axis=0)
    # A skewed sparse control can have its mean outside the central quantiles.
    # Draw the interval endpoints directly rather than implying a symmetric CI.
    axes[1].vlines(np.arange(16)-.12,bounds[0],bounds[1],color="tab:blue")
    axes[1].scatter(np.arange(16)-.12,means,label="independent shifts: mean and 95% control interval",s=20)
    axes[1].scatter(np.arange(16)+.12,observed[:,0],label="observed",color="tab:red")
    axes[1].set_yscale("symlog",linthresh=10);axes[1].set_xticks(np.arange(16),groups);axes[1].set_ylabel("Pair-bin coincidences");axes[1].legend(fontsize=8);axes[1].grid(alpha=.2)
    save_figure(fig,args.figures,"topology-control")
    report["elapsed_seconds"]=time.perf_counter()-started
    dump(args.export/"summary.json",report)
    with (args.export/"hosts.csv").open("w",newline="",encoding="utf-8") as stream:
        keys=["hostname","group","available","if_count","control_count","if_rate","control_rate","tp","fp","fn","tn","score_mean","score_std","distance_mean","longest_if_run_seconds"]
        writer=csv.DictWriter(stream,fieldnames=keys,extrasaction="ignore");writer.writeheader();writer.writerows(host_summary)
    print(json.dumps({"heterogeneity":report["heterogeneity"],"correlations":report["correlations"],"ranking":report["ranking"],"global_control":report["global_control"],"elapsed_seconds":report["elapsed_seconds"]},indent=2),flush=True)


if __name__=="__main__":
    main()
