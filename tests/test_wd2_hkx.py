"""WD2 .hkx collision import + injection round-trip test.

Imports a real WD2 collision file through the Blender-facing module, verifies
the shape objects, then injects the *unmodified* mesh back and checks the
output is byte-identical to the source (physics-critical data round-trips).
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


HKX = "_geometries/locations/galilei/galilei_glass_breakable02.hkx"


def test_wd2_hkx_import_and_roundtrip(wd2_dir, tmp_path):
    import bpy

    _import_modules()
    from modules.Havok.import_hkx_wd2 import (
        import_hkx_wd2,
        inject_hkx_wd2,
    )

    src = os.path.join(wd2_dir, HKX)
    if not os.path.isfile(src):
        pytest.skip(f"WD2 unpack not available: {src}")
    orig = open(src, "rb").read()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    n_shapes, n_verts = import_hkx_wd2(bpy.context, src)
    assert n_shapes == 2
    assert n_verts == 16  # two 8-vertex boxes

    shape_objs = [o for o in bpy.context.scene.objects
                  if o.get("wd2_hkx_shape_index") is not None]
    assert len(shape_objs) == 2
    for o in shape_objs:
        assert o.get("wd2_hkx_src") == src
        assert o.get("wd2_hkx_vertex_count") == 8
        assert len(o.data.vertices) == 8

    out = str(tmp_path / "galilei_edited.hkx")
    injected = inject_hkx_wd2(bpy.context, src, shape_objs, out)
    assert len(injected) == 2
    assert os.path.exists(out)
    assert open(out, "rb").read() == orig