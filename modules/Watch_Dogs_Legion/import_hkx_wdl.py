"""Watch Dogs Legion .hkx collision import — Blender side.

Uses the pure-Python Disrupt parser in ``import_hkx`` (a faithful HavokDisrupt
port) and the TAG0 compressed mesh decoder in ``tag0_compressed_mesh`` to build
one mesh object per hkpBvCompressedMeshShape.
"""

import os

import bpy

from ..Havok.import_hkx import parse_hkx
from ..Havok.tag0_compressed_mesh import Tag0CompressedMesh


def import_hkx_wdl(context, path):
    """Import a WDL .col.hkx (TAG0 compressed mesh) as one mesh object per
    shape. Returns (n_shapes, n_verts)."""
    f = parse_hkx(path)
    base_name = os.path.splitext(os.path.basename(path))[0]
    shapes = [it for it in f.items if it.type_id == 0x94]

    root = bpy.data.objects.new(base_name + "_collision", None)
    root.empty_display_type = 'CUBE'
    root.empty_display_size = 0.25
    root['wdl_hkx_src'] = path
    root['wdl_hkx_n_shapes'] = len(shapes)
    context.collection.objects.link(root)

    n_shapes = 0
    n_verts = 0
    for i, shape_item in enumerate(shapes):
        cm = Tag0CompressedMesh(f, shape_item)
        if not cm.has_data():
            continue
        verts, faces = cm.decode()
        if not verts:
            continue
        me = bpy.data.meshes.new("%s_shape%d" % (base_name, i))
        me.from_pydata(verts, [], faces)
        me.update()
        obj = bpy.data.objects.new(me.name, me)
        obj.display_type = 'WIRE'
        obj.show_wire = True
        obj['wdl_hkx_src'] = path
        obj['wdl_hkx_shape_index'] = i
        obj['wdl_hkx_shape_item'] = shape_item.index
        obj['wdl_hkx_vertex_count'] = len(verts)
        context.collection.objects.link(obj)
        obj.parent = root
        n_shapes += 1
        n_verts += len(verts)

    return n_shapes, n_verts