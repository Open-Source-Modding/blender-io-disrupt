"""Watch Dogs 2 .glm importer (self-contained WD2-owned module).

Split out of the combined Watch_Dogs importer.  WD2 ships its model as a raw
text GEOM source (.glm, "unconverted xbg"): VERSION header, SKELETON (named
bones, parents, axis-angle rotations), GEOMETRY/TRIMESH (indexed verts, faces,
TVERT UVs, BLEND skin links).

Contains the WD2 text parser (parse_wd2_glm) and a WD2-OWNED copy of the
neutral-dict -> Blender builder (build_wd_model), so editing WD2 behaviour can
never affect Watch Dogs 1.  WD2 is import-only (no MAB / inject / skeleton /
HKX — those are WD1 binary-GEOM features).
"""

import os
import re
import math

import numpy as np

try:
    import bpy
    import mathutils
except ImportError:
    bpy = None
    mathutils = None

from ..Core.debug import VerboseLogger as vlog


def parse_wd2_glm(path):
    """Parse a Watch Dogs 2 .glm (text GEOM source) into the model dict."""
    txt = open(path, 'rb').read().decode('latin-1')
    model = {
        'source': 'wd2',
        'name': os.path.splitext(os.path.basename(path))[0],
        'bones': [],
        'meshes': [],
    }
    m = re.search(r'OBJECT_NAME\t"([^"]*)"', txt)
    if m:
        model['name'] = m.group(1)

    # ---- skeleton ----
    skel_m = re.search(r'SKELETON\t\{', txt)
    if skel_m:
        name2idx = {}
        # BONE blocks inside the skeleton are flat (no nested braces)
        for bm in re.finditer(
                r'BONE\t\{\s*'
                r'NAME\t"([^"]*)"\s*'
                r'PARENT\t"([^"]*)"\s*'
                r'POSITION\t(\S+)\t(\S+)\t(\S+)\s*'
                r'ROTATION\t(\S+)\t(\S+)\t(\S+)\t(\S+)\s*'
                r'SCALE\t\S+\t\S+\t\S+\s*\}', txt):
            name, parent = bm.group(1), bm.group(2)
            pos = tuple(float(bm.group(i)) for i in (3, 4, 5))
            ax, ay, az, ang = (float(bm.group(i)) for i in (6, 7, 8, 9))
            n = math.sqrt(ax * ax + ay * ay + az * az)
            if n > 1e-9 and abs(ang) > 1e-9:
                s = math.sin(ang / 2.0)
                quat = (math.cos(ang / 2.0), ax / n * s, ay / n * s, az / n * s)
            else:
                quat = (1.0, 0.0, 0.0, 0.0)
            if parent and parent not in name2idx:
                # referenced-but-undeclared parent (e.g. "Root") — synthesize
                name2idx[parent] = len(model['bones'])
                model['bones'].append({'name': parent, 'parent': -1,
                                       'pos': (0, 0, 0),
                                       'quat': (1.0, 0.0, 0.0, 0.0)})
            name2idx[name] = len(model['bones'])
            model['bones'].append({
                'name': name,
                'parent': name2idx.get(parent, -1),
                'pos': pos, 'quat': quat,
            })

    # ---- material slot names (per-face material ids index this list) ----
    slot_names = re.findall(r'SLOTNAME\t"([^"]*)"', txt)

    # ---- TRIMESH blocks ----
    for tm in re.finditer(r'\tTRIMESH\t\{', txt):
        block = _glm_block(txt, tm.end() - 1)
        mesh = _parse_glm_trimesh(block, slot_names)
        if mesh:
            model['meshes'].append(mesh)
    return model


def _glm_block(txt, open_brace):
    """Return the text of a {...} block given the index of its '{'."""
    depth = 0
    for i in range(open_brace, len(txt)):
        c = txt[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return txt[open_brace:i + 1]
    return txt[open_brace:]


def _parse_glm_trimesh(block, slot_names):
    name_m = re.search(r'MESH_NAME\t"([^"]*)"', block)
    name = name_m.group(1) if name_m else 'mesh'

    verts = [tuple(float(x) for x in m.groups())
             for m in re.finditer(
                 r'VERTEX\t\d+\t(\S+)\t(\S+)\t(\S+)', block)]
    if not verts:
        return None
    normals = [tuple(float(x) for x in m.groups())
               for m in re.finditer(
                   r'NORMAL\t\d+\t(\S+)\t(\S+)\t(\S+)', block)]
    # first TVERT channel only
    tverts = []
    tv_m = re.search(r'TVERT_LIST\t\{', block)
    if tv_m:
        tv_block = _glm_block(block, tv_m.end() - 1)
        tverts = [(float(m.group(1)), float(m.group(2)))
                  for m in re.finditer(
                      r'TVERT\t\d+\t(\S+)\t(\S+)', tv_block)]

    nb_uv = 1
    uv_m = re.search(r'NB_UV_CHANNELS\t(\d+)', block)
    if uv_m:
        nb_uv = int(uv_m.group(1))

    tris, loop_normals, loop_uvs, face_mats = [], [], [], []
    for fm in re.finditer(r'FACE\t([\d\t \-]+)', block):
        f = [int(x) for x in fm.group(1).split()]
        # f = idx, v0,v1,v2, n0,n1,n2, nb_uv*3 tvert ids, SMOOTHING_GROUP,
        # MATERIAL.  The LAST field is the material slot (its values range
        # exactly 0..NB_MATERIAL-1 across the file); the second-to-last is
        # the smoothing group (values up to 60+ — reading THAT as the
        # material, as this parser originally did, mis-assigned most faces
        # to slot 0 via the out-of-range fallback).
        if len(f) < 7 + nb_uv * 3 + 2:
            continue
        v = f[1:4]
        n = f[4:7]
        t = f[7:10]                       # channel 0
        mat = f[7 + nb_uv * 3 + 1]
        tris.append(tuple(v))
        for j in range(3):
            loop_normals.append(normals[n[j]] if n[j] < len(normals)
                                else (0.0, 0.0, 1.0))
            if 0 <= t[j] < len(tverts):
                u, vv = tverts[t[j]]
                loop_uvs.append((u, vv))
            else:
                loop_uvs.append((0.0, 0.0))
        face_mats.append(mat if 0 <= mat < len(slot_names) else 0)

    weights = {}
    bl_m = re.search(r'BLEND_LIST\t\{', block)
    if bl_m:
        bl_block = _glm_block(block, bl_m.end() - 1)
        for bv in re.finditer(
                r'BLEND_VERTEX\t\{\s*VERTEX\t(\d+)\s*NB_BONE\t\d+\s*'
                r'((?:BONE_LINK\t"[^"]*"\t\S+\s*)+)\}', bl_block):
            vi = int(bv.group(1))
            wl = [(m.group(1), float(m.group(2)))
                  for m in re.finditer(r'BONE_LINK\t"([^"]*)"\t(\S+)',
                                       bv.group(2))]
            if wl:
                weights[vi] = wl

    return {
        'name': name, 'verts': verts, 'tris': tris,
        'uvs': None, 'loop_uvs': loop_uvs or None,
        'normals': None, 'loop_normals': loop_normals or None,
        'weights': weights, 'material': None,
        'face_materials': face_mats, 'material_slots': slot_names,
    }


def build_wd_model(context, model, import_mesh_only=False):
    """Create armature + meshes from the neutral model dict.

    Delegates to the shared ``disrupt_common.build_blender_scene`` for the
    actual Blender object construction.  This wrapper exists for backward
    compatibility — callers within ``Watch_Dogs_2/`` import it directly.
    """
    from ..Core.disrupt_common import build_blender_scene
    return build_blender_scene(context, model,
                               import_mesh_only=import_mesh_only)


def load_wd2_model(context, filepath, separate_primitives=True):
    """Parse a WD2 .glm and build it in Blender.  Returns (model, armature)."""
    head = open(filepath, 'rb').read(8)
    if head[:7] != b'VERSION':
        raise ValueError(
            "not a Watch Dogs 2 .glm text GEOM file (header %r)" % head[:7])
    model = parse_wd2_glm(filepath)
    arm, mesh_objs = (build_wd_model(context, model) if bpy else (None, []))

    # Export metadata: which source .glm and which TRIMESH (file order) each
    # object came from — export_wd2.export_wd2_glm reads these back.
    for mi, obj in enumerate(mesh_objs):
        obj['wd2_src'] = filepath
        obj['wd2_mesh_index'] = mi

    # Avatar-parity: join submeshes into one object when separate prims is OFF.
    if bpy is not None and not separate_primitives and len(mesh_objs) > 1:
        from ..Core.disrupt_common import join_submeshes
        join_submeshes(context, mesh_objs, model['name'])
    return model, arm
