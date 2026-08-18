"""Watch Dogs 2 .hkx collision import/export — Blender side.

Uses the pure-Python Disrupt parser in ``import_hkx`` (a faithful HavokDisrupt
port) to build one mesh object per convex collision shape, and to inject
edited vertices back into a copy of the source .hkx (vertex-displacement
only — the vertex count and order must be preserved).

Physics-critical data round-trips bit-identically: an untouched imported
shape injects back to byte-identical bytes.
"""

import os

import bpy
import bmesh

from . import import_hkx as hkx


def import_hkx_wd2(context, path):
    """Import a WD2 .hkx collision file as one mesh object per convex shape.

    Shapes are imported in their shape-local space (no child-transform bake)
    so an unmodified round trip is byte-identical.  Returns (n_shapes,
    n_verts).
    """
    f = hkx.parse_hkx(path)
    base_name = os.path.splitext(os.path.basename(path))[0]

    root = bpy.data.objects.new(base_name + "_collision", None)
    root.empty_display_type = 'CUBE'
    root.empty_display_size = 0.25
    root['wd2_hkx_src'] = path
    root['wd2_hkx_n_shapes'] = len(f.convex_shapes)
    context.collection.objects.link(root)

    n_shapes = 0
    n_verts = 0
    for i, shape in enumerate(f.convex_shapes):
        positions, tris = hkx.to_triangle_mesh(shape)
        faces = [tuple(tris[j:j + 3])
                 for j in range(0, len(tris), 3)]
        me = bpy.data.meshes.new("%s_shape%d" % (base_name, i))
        me.from_pydata(positions, [], faces)
        me.update()
        obj = bpy.data.objects.new(me.name, me)
        obj.display_type = 'WIRE'
        obj.show_wire = True
        obj['wd2_hkx_src'] = path
        obj['wd2_hkx_shape_index'] = i
        obj['wd2_hkx_shape_item'] = shape.shape_item_index
        obj['wd2_hkx_variant'] = shape.variant
        obj['wd2_hkx_vertex_count'] = len(shape.vertices)
        context.collection.objects.link(obj)
        obj.parent = root
        n_shapes += 1
        n_verts += len(shape.vertices)

    return n_shapes, n_verts


def inject_hkx_wd2(context, path, objects, out_path):
    """Inject edited vertices from imported shape objects into a copy of a
    WD2 .hkx.

    Each selected object's mesh is vertex-displacement-only re-encoded into
    its source shape.  Returns a list of (shape_index, n_verts) injected.
    """
    f = hkx.parse_hkx(path)
    data = open(path, 'rb').read()
    injected = []
    for obj in objects:
        si = obj.get('wd2_hkx_shape_index')
        if si is None:
            continue
        if si < 0 or si >= len(f.convex_shapes):
            continue
        shape = f.convex_shapes[si]
        me = obj.data
        verts = [tuple(v.co) for v in me.vertices]
        if len(verts) != len(shape.vertices):
            raise ValueError(
                "Shape %d vertex count changed: %d vs original %d. "
                "HKX injection is VERTEX-DISPLACEMENT-ONLY — move vertices, "
                "do not add/delete." % (si, len(verts), len(shape.vertices)))
        group = hkx.ObjGroup()
        group.name = obj.name
        group.vertices = verts
        group.triangles = []
        data = hkx.inject_obj_into_shape(f, si, group, data)
        injected.append((si, len(verts)))
    if not injected:
        return injected
    with open(out_path, 'wb') as fh:
        fh.write(data)
    return injected