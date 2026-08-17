"""WD1 .hkx collision import + injection round-trip test.

Imports a real WD1 (64-bit Havok 2012) collision file through the Blender-
facing module, verifies the shape objects, then injects the *unmodified* mesh
back and checks the output is byte-identical to the source (physics-critical
data round-trips).
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


HKX = "buildings/facade/07_antique_hardware_base.hkx"


def test_wd1_hkx_import_and_roundtrip(wd1_dir, tmp_path):
    import bpy

    _import_modules()
    from modules.Watch_Dogs.import_hkx_wd import import_hkx_wd
    from modules.Watch_Dogs.inject_hkx_wd import inject_hkx_wd

    src = os.path.join(wd1_dir, HKX)
    if not os.path.isfile(src):
        pytest.skip(f"WD1 unpack not available: {src}")
    orig = open(src, "rb").read()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    n_hulls, n_verts, n_meshes = import_hkx_wd(bpy.context, src)
    # This file: 1 convex hull (16 verts) + no compressed meshes.  Boxes are
    # part of the static compound and are NOT imported as objects (the
    # importer only surfaces convex-hull and compressed-mesh shapes).
    assert n_hulls == 1
    assert n_verts == 16
    assert n_meshes == 0

    shape_objs = [o for o in bpy.context.scene.objects
                  if o.get("wd_hkx_shape_off") is not None
                  and not o.get("wd_hkx_is_hull_reconstruction")]
    assert len(shape_objs) == 1
    o = shape_objs[0]
    assert o.get("wd_hkx_src") == src
    assert len(o.data.vertices) == 16

    out = str(tmp_path / "07_antique_hardware_base_edited.hkx")
    injected = inject_hkx_wd(bpy.context, src, shape_objs, out)
    assert len(injected) == 1
    assert os.path.exists(out)
    assert open(out, "rb").read() == orig
