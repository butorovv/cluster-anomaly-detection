"""Protect original research documents; regenerated artifacts require new paths."""
from pathlib import Path

HISTORICAL = Path(__file__).resolve().parents[2] / 'docs/research-4.3'


def new_directory(path):
    path = Path(path).resolve()
    if path == HISTORICAL or path.is_relative_to(HISTORICAL):
        raise ValueError('historical research documents/figures must not be overwritten')
    path.mkdir(parents=True, exist_ok=False)
    return path


def save_audit(path, value):
    if path is not None:
        import json
        path = Path(path).resolve()
        if path == HISTORICAL or path.is_relative_to(HISTORICAL):
            raise ValueError('historical research documents must not be overwritten')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
