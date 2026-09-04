"""Shared utilities for all Disrupt engine games (WD1/WD2/WDL).

This module provides the neutral model-dict specification, the unified
Blender builder, and common helpers used by every game's importer/exporter.

Model Dict Contract
-------------------
Every parser (WD1 binary, WD2 text GLM, WDL binary XBG) produces one
canonical dict::

    {
      'source': 'wd1' | 'wd2' | 'wdl',
      'name': str,                          # object/file base name
      'bones': [                             # skeleton (empty list = static prop)
        {
          'name': str,
          'parent': int,                     # index into this list, -1 = root
          'pos': (x, y, z),
          'quat': (w, x, y, z),             # Hamilton (w-first)
        }, ...
      ],
      'meshes': [                            # one per submesh / drawcall
        {
          'name': str,
          'verts': [(x, y, z), ...],         # per-vertex positions
          'tris': [(a, b, c), ...],          # triangle indices (Blender CCW winding)

          # UVs — prefer loop_uvs (per-corner); per-vert uvs are
          # converted to loop space by the builder.
          'uvs': [(u, v), ...] | None,       # per-vertex UV layer 0
          'loop_uvs': [(u, v), ...] | None,  # per-corner UV layer 0
          'uvs2': [(u, v), ...] | None,      # per-vertex UV layer 1 (WD1)

          # Normals — prefer loop_normals (per-corner).
          'normals': [(x, y, z), ...] | None,
          'loop_normals': [(x, y, z), ...] | None,

          # Vertex colors (RGBA floats 0..1)
          'colors': [(r, g, b, a), ...] | None,

          # Tangent / binormal frames (optional, WD1)
          'tangents': [(x, y, z), ...] | None,
          'tangents_w': [float, ...] | None,
          'binormals': [(x, y, z), ...] | None,
          'binormals_w': [float, ...] | None,

          # Skin weights: {vertex_index: [(bone_name, weight), ...]}
          'weights': {int: [(str, float), ...]},

          # Material assignment (single string or per-face list)
          'material': str | None,            # single material name
          'material_slots': [str, ...] | None,  # named slots
          'face_materials': [int, ...] | None,   # per-face slot index
        }, ...
      ],

      # Optional metadata (game-specific, consumed by importers/exporters)
      'material_paths': [str, ...],   # WD1: game-style .material.bin paths
      'src_dir': str,                  # WD1: directory of source .xbg
      '_layout': dict,                 # WD1: binary layout for injection
    }

Builder
-------
``build_blender_scene(ctx, model)`` turns the above dict into Blender objects
and returns ``(armature_object | None, [mesh_objects])``.
"""

from __future__ import annotations

import os

import numpy as np

try:
    import bpy
    import mathutils
except ImportError:
    bpy = None
    mathutils = None

try:
    from .debug import VerboseLogger as vlog
except ImportError:
    class vlog:
        enabled = False
        @staticmethod
        def log(m): pass


# ---------------------------------------------------------------------------
# Material auto-import (WD1 .material.bin)
# ---------------------------------------------------------------------------

def try_import_materials(model):
    """Auto-import .material.bin files referenced by the XBG.

    Material paths are game-style (e.g.
    ``graphics\\\\_materials\\\\foo.material.bin``).  Walk up from the XBG
    directory looking for ``graphics/_materials/`` and resolve basenames.

    Returns ``{basename: Blender material}`` for successfully imported files.
    """
    if bpy is None:
        return {}

    # Late import to avoid circular deps (material_editor_wd → Core)
    try:
        from ..Watch_Dogs.material_editor_wd import material_from_bin
    except ImportError:
        return {}

    mat_paths = model.get('material_paths') or []
    src_dir = model.get('src_dir') or ''
    imported = {}

    # Walk up from src_dir looking for graphics/_materials/
    mat_dir = None
    d = os.path.abspath(src_dir)
    for _ in range(10):
        candidate = os.path.join(d, 'graphics', '_materials')
        if os.path.isdir(candidate):
            mat_dir = candidate
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent

    if mat_dir is None:
        return imported

    for game_path in mat_paths:
        fwd = game_path.replace('\\', '/')
        basename = os.path.basename(fwd)
        cand = os.path.join(mat_dir, basename)
        if os.path.isfile(cand):
            try:
                me, shader = material_from_bin(cand)
                if me:
                    imported[os.path.splitext(basename)[0]] = me
            except Exception:
                pass
    return imported


# ---------------------------------------------------------------------------
# Blender builder (unified across WD1 / WD2 / WDL)
# ---------------------------------------------------------------------------

def build_blender_scene(context, model, import_mesh_only=False):
    """Create armature + meshes from the neutral model dict.

    Returns ``(armature_object | None, [created mesh objects])``.

    ``import_mesh_only`` skips the armature and skin binding (geometry only).
    """
    if bpy is None:
        raise RuntimeError("bpy unavailable")

    # Auto-import .material.bin files referenced by the XBG (WD1)
    imported_mats = try_import_materials(model)

    Mat = mathutils.Matrix
    Quat = mathutils.Quaternion
    Vec = mathutils.Vector

    mesh_objs = []
    bones = model['bones']
    arm_obj = None

    # ── Armature ──────────────────────────────────────────────────────────
    if bones and not import_mesh_only:
        ad = bpy.data.armatures.new(model['name'] + '_Armature')
        arm_obj = bpy.data.objects.new(ad.name, ad)
        context.collection.objects.link(arm_obj)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')

        world = [None] * len(bones)
        ebs = []
        for i, b in enumerate(bones):
            local = (Mat.Translation(Vec(b['pos'])) @
                     Quat(b['quat']).to_matrix().to_4x4())
            p = b['parent']
            world[i] = (world[p] @ local
                        if 0 <= p < i and world[p] is not None else local)
            eb = ad.edit_bones.new(b['name'])
            head = world[i].to_translation()
            eb.head = head
            eb.tail = head + world[i].to_3x3() @ Vec((0.0, 0.05, 0.0))
            ebs.append(eb)
        for i, b in enumerate(bones):
            if 0 <= b['parent'] < i:
                ebs[i].parent = ebs[b['parent']]
        bpy.ops.object.mode_set(mode='OBJECT')

    # ── Meshes ────────────────────────────────────────────────────────────
    for mesh in model['meshes']:
        me = bpy.data.meshes.new(mesh['name'])
        me.from_pydata(mesh['verts'], [], mesh['tris'])
        me.update()
        obj = bpy.data.objects.new(mesh['name'], me)
        context.collection.objects.link(obj)
        mesh_objs.append(obj)

        # ── Injection metadata (WD1 / WDL) ───────────────────────────────
        inj = mesh.get('inject')
        if inj:
            src_key = {'wd1': 'wd_src', 'wd2': 'wd2_src',
                       'wdl': 'wdl_src'}.get(model.get('source', ''), 'wd_src')
            obj[src_key] = inj['src']
            for k, v in inj.items():
                if k == 'src':
                    continue
                obj_key = f'wd_{k}' if k != 'mip_src' else 'wd_mip_src'
                # Blender custom properties use C int (32-bit signed) for
                # integers; values > INT_MAX cause "Python int too large to
                # convert to C int".  Store large unsigned values (e.g.
                # pos_off_raw) as strings instead.
                if isinstance(v, int) and v > 0x7FFFFFFF:
                    obj[obj_key] = str(v)
                else:
                    obj[obj_key] = v

        # ── UV layers ─────────────────────────────────────────────────────
        loop_uvs = mesh.get('loop_uvs')
        per_vert_uvs = mesh.get('uvs')
        loop_vi = None
        if loop_uvs or per_vert_uvs or mesh.get('uvs2'):
            loop_vi = np.empty(len(me.loops), dtype=np.intp)
            me.loops.foreach_get('vertex_index', loop_vi)

        def _set_uv(layer_name, loop_data, per_vert_data):
            uvl = me.uv_layers.new(name=layer_name)
            if loop_data:
                flat = np.asarray(loop_data, dtype=np.float64).ravel()
            else:
                flat = np.asarray(per_vert_data, dtype=np.float64)[loop_vi].ravel()
            uvl.data.foreach_set('uv', flat)

        if loop_uvs or per_vert_uvs:
            _set_uv('UVMap', loop_uvs, per_vert_uvs)
        per_vert_uvs2 = mesh.get('uvs2')
        if per_vert_uvs2:
            _set_uv('UVMap1', None, per_vert_uvs2)

        # ── Vertex colors ─────────────────────────────────────────────────
        # WD1 uses FLOAT_COLOR for round-trip fidelity (BYTE_COLOR's
        # sRGB↔linear conversion through 8-bit storage drifts ±1 byte).
        colors = mesh.get('colors')
        if colors:
            ca = me.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
            ca.data.foreach_set('color',
                                np.asarray(colors, dtype=np.float64).ravel())

        # ── Normals ───────────────────────────────────────────────────────
        # Store authored normals in xbg_normal attribute for re-export.
        # We intentionally skip normals_split_custom_set to avoid segfaults
        # in Blender 5.2 + Python 3.14 on certain mesh topologies.
        loop_normals = mesh.get('loop_normals')
        per_vert_normals = mesh.get('normals')
        for poly in me.polygons:
            poly.use_smooth = True
        if loop_normals and len(loop_normals) == len(me.loops):
            try:
                me.normals_split_custom_set(loop_normals)
            except Exception:
                pass
        if per_vert_normals:
            na = me.attributes.new('xbg_normal', 'FLOAT_VECTOR', 'POINT')
            na.data.foreach_set(
                'vector', [c for n in per_vert_normals for c in n])

        # ── Tangent / binormal frames ─────────────────────────────────────
        for vec_key, w_key, vec_attr, w_attr in (
                ('tangents', 'tangents_w', 'xbg_tangent', 'xbg_tangent_w'),
                ('binormals', 'binormals_w', 'xbg_binormal', 'xbg_binormal_w')):
            vecs = mesh.get(vec_key)
            if not vecs:
                continue
            va = me.attributes.new(vec_attr, 'FLOAT_VECTOR', 'POINT')
            va.data.foreach_set('vector', [c for v in vecs for c in v])
            ws = mesh.get(w_key)
            if ws:
                wa = me.attributes.new(w_attr, 'FLOAT', 'POINT')
                wa.data.foreach_set('value', ws)

        # ── Materials ─────────────────────────────────────────────────────
        slots = mesh.get('material_slots')
        if slots:
            for sn in slots:
                mat = (imported_mats.get(sn)
                       or bpy.data.materials.get(sn)
                       or bpy.data.materials.new(sn))
                me.materials.append(mat)
            fmats = mesh.get('face_materials') or []
            for pi, poly in enumerate(me.polygons):
                if pi < len(fmats):
                    poly.material_index = fmats[pi]
        elif mesh.get('material'):
            mat = (imported_mats.get(mesh['material'])
                   or bpy.data.materials.get(mesh['material'])
                   or bpy.data.materials.new(mesh['material']))
            me.materials.append(mat)

        # ── Skin weights ──────────────────────────────────────────────────
        if mesh['weights'] and arm_obj:
            groups = {}
            for vi, wl in mesh['weights'].items():
                for nm, w in wl:
                    g = groups.get(nm)
                    if g is None:
                        g = groups[nm] = obj.vertex_groups.new(name=nm)
                    g.add([vi], w, 'REPLACE')
            obj.parent = arm_obj
            mod = obj.modifiers.new('Armature', 'ARMATURE')
            mod.object = arm_obj

    return arm_obj, mesh_objs


# ---------------------------------------------------------------------------
# Join helper (Avatar-parity: separate_primitives OFF)
# ---------------------------------------------------------------------------

def join_submeshes(context, mesh_objs, model_name):
    """Join multiple mesh objects into one (clean view import; not injectable).

    Returns the joined object.  Sets ``wd_joined = True`` and clears
    injection keys.
    """
    if bpy is None or len(mesh_objs) <= 1:
        return mesh_objs[0] if mesh_objs else None

    bpy.ops.object.select_all(action='DESELECT')
    for o in mesh_objs:
        o.select_set(True)
    context.view_layer.objects.active = mesh_objs[0]
    victim_meshes = [o.data for o in mesh_objs[1:]]
    bpy.ops.object.join()
    joined = context.active_object
    joined.name = model_name
    joined['wd_joined'] = True
    for key in list(joined.keys()):
        if key.startswith('wd_') and key != 'wd_joined':
            del joined[key]
    for m in victim_meshes:
        if m.users == 0:
            bpy.data.meshes.remove(m)
    return joined
