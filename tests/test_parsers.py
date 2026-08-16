"""Smoke tests: addon enables and parses real game files without raising."""
import glob
import os
import sys

import pytest

REPO_ROOT = os.environ.get("XBG_REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


def _import_modules():
    """Add repo root to sys.path so `from modules...` works (lazy)."""
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)


def _first_xbg(directory, pattern="**/*.xbg"):
    files = sorted(glob.glob(os.path.join(directory, pattern), recursive=True))
    assert files, f"no .xbg files found under {directory}"
    return files[0]


def test_bpy_available():
    import bpy

    assert bpy.app.version_string


def test_wdl_parser_smoke(wdl_dir):
    _import_modules()
    from modules.Watch_Dogs_Legion.import_wdl_xbg import parse_wdl_xbg

    path = _first_xbg(wdl_dir)
    model = parse_wdl_xbg(path)
    assert model["name"]
    assert isinstance(model["meshes"], list)


def test_wd1_parser_smoke(wd1_dir):
    _import_modules()
    from modules.Watch_Dogs.import_wd import parse_wd1_xbg

    path = _first_xbg(wd1_dir)
    model = parse_wd1_xbg(path)
    assert model["name"]
    assert isinstance(model["meshes"], list)
