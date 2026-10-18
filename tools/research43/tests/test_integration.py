"""Integration boundaries: canonical helpers and immutable historical outputs."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.research43 import output_paths

ROOT = Path(__file__).resolve().parents[3]


def test_canonical_helpers_ignore_stale_short_module_names():
    # A previous research checkout or another pytest module can populate these
    # short names. Consumers must still bind to the original tracked package.
    code = """
import sys, types
sys.modules['diagnostic_stats'] = types.ModuleType('obsolete_diagnostics')
sys.modules['stats'] = types.ModuleType('unrelated_stats')
sys.modules['context_stats'] = types.ModuleType('obsolete_context')
sys.modules['analyze'] = types.ModuleType('unrelated_analyze')
from tools.context import context_stats
from tools.context import analyze as context_analyze
from tools.research43 import analyze, compare
from tools.diagnostics import diagnostic_stats
from tools.research43 import stats
assert context_stats.holm is diagnostic_stats.holm
assert analyze.holm is compare.holm is diagnostic_stats.holm
assert context_analyze.pearson is diagnostic_stats.pearson
assert context_analyze.calibrate is context_stats.calibrate
assert analyze.temporal is compare.temporal is stats.temporal
assert 'vendor' not in diagnostic_stats.__file__
"""
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_outputs_cannot_overwrite_historical_artifacts(tmp_path, monkeypatch):
    historical = tmp_path / 'history'
    historical.mkdir()
    monkeypatch.setattr(output_paths, 'HISTORICAL', historical)
    for path in [historical, historical / 'new-figures']:
        with pytest.raises(ValueError, match='historical'):
            output_paths.new_directory(path)
    original = historical / 'report.json'
    original.write_text('original', encoding='utf-8')
    with pytest.raises(ValueError, match='historical'):
        output_paths.save_audit(original, {'replacement': True})
    assert original.read_text(encoding='utf-8') == 'original'
    fresh = output_paths.new_directory(tmp_path / 'replay')
    target = fresh / 'audit.json'
    output_paths.save_audit(target, {'checked': True})
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        output_paths.save_audit(target, {'checked': False})
    assert target.read_bytes() == before
    with pytest.raises(FileExistsError):
        output_paths.new_directory(fresh)


@pytest.mark.parametrize('script', ['write_report.py', 'write_comparison.py'])
def test_report_generators_require_explicit_new_destination(script):
    result = subprocess.run([sys.executable, str(ROOT/'tools/research43'/script)],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert '--report-dir' in result.stderr
