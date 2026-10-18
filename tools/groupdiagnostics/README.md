# Checkpoint 1 — D1 group applicability diagnostics

Research only; does not implement or approve a group detector. Reads the existing
prepared D1 `[00:00,08:00)` on 2022-01-18 plus raw D1 annotation fields. Never
trains IF, updates B1, analyzes D2/D3, or overwrites existing outputs.

Uses existing inverted-CDF quantile from `tools.context.context_stats` and the
Welford convention of `internal/analysis/statistical.go` at d=10. Dependencies
used: NumPy 2.3.5, PyArrow 26.0.0, Python 3.12.14; no new packages installed.

From repository root in an environment containing these existing dependencies:

```powershell
python tools/groupdiagnostics/d1.py --output <NEW_DIRECTORY>
python tools/groupdiagnostics/report.py --input <NEW_DIRECTORY>
python -m pytest -p no:cacheprovider tools/groupdiagnostics/test_d1.py
```

Output includes full host/channel medians, MAD/floor diagnostics, raw/normalized
covariance, spectra, effective ranks, pseudoinverses, reconstruction checks,
training-only Q99, F18 distributions, raw schema, exact input SHA before/after,
baseline commit, diagnostic script SHA, source-spec SHA, versions and command.
`base_commit` in the original run is the pre-change main; reproduce on a new
commit and compare numerical payloads/immutable inputs, not that provenance field.

The script requires the full fixed D1 tick/host grid and verifies it rather than
silently reshaping duplicates or missing rows. Existing incomplete F18 ticks are
excluded per group. A missing row/grid aborts this pilot diagnostic; this is not
the missing-data behavior of a future production detector.

Reports: [checkpoint](../../docs/group-detection-checkpoint-1.md),
[D1 numerical report](../../docs/group-detection-d1-final/README.md).
