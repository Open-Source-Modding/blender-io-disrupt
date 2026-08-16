"""WD1 native exporter round-trip test.

Builds a cube in Blender, exports it to a fresh .xbg via export_wd1, then
re-imports with parse_wd1_xbg and checks the decoded geometry matches the
original cube.  Requires running under Blender (bpy) — see pytest.ini.
"""
import os
import sys

import pytest

REPO_ROOT = os.environ.get("XBG_REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


def _import_modules():
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)


def test_wd1_export_roundtrip(tmp_path):
    import bpy
    import mathutils

    _import_modules()
    from modules.Watch_Dogs.export_wd1 import export_wd1
    from modules.Watch_Dogs.import_wd import parse_wd1_xbg

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = bpy.context.active_object
    cube.matrix_world = mathutils.Matrix.Translation((1.0, 2.0, 3.0))
    cube.data.materials.append(bpy.data.materials.new("test_mat"))

    out = str(tmp_path / "cube.xbg")
    n = export_wd1(out, [cube])
    assert n == 1
    assert os.path.exists(out)

    model = parse_wd1_xbg(out)
    assert len(model["meshes"]) == 1
    mesh = model["meshes"][0]
    assert len(mesh["verts"]) == 8
    assert len(mesh["tris"]) == 12

    # cube translated to (1,2,3) -> min (0,1,2), max (2,3,4), i16 quantised
    lo = [min(v[i] for v in mesh["verts"]) for i in range(3)]
    hi = [max(v[i] for v in mesh["verts"]) for i in range(3)]
    for i in range(3):
        assert abs(lo[i] - i) < 0.01, f"min[{i}]={lo[i]}"
        assert abs(hi[i] - (i + 2)) < 0.01, f"max[{i}]={hi[i]}"
