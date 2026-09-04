"""Watch Dogs / Disrupt engine material editor — Blender Cycles/Eevee bridge.

Maps .material.bin (TAM v7) parameters to standard Blender Principled BSDF
materials for rendering.  Game-specific parameters (texture animation, vertex
animation, channel packing, etc.) are preserved as material custom properties
for export round-trip fidelity.

Material descriptor XMLs defining the full parameter set per shader family
are kept at:
  https://github.com/open-source-modding/open-source-modding.github.io
under reference/watch_dogs/materialdescriptors/
"""

import os

try:
    import bpy
except ImportError:
    bpy = None

from .material_bin import read_material_bin, write_material_bin

# ── TFOWC2 (The Fall of Windy City 2) extended material system ───────────
# TFOWC2 extends vanilla WD materials with specular texture channel masks,
# metalness workflow, and additional reflection modes.  Detection is based
# on the presence of TFOWC2-specific parameters in the .material.bin.

_TFOWC2_PARAMS = frozenset({
    'MaskRedChannelMode', 'MaskBlueChannelMode', 'MaskAlphaChannelMode',
    'SwapSpecularGlossAndOcclusion', 'ColorizeDiffuse1Mode',
    'InvertMaskForColorize', 'UseColorizeDiffuse1',
})


def is_tfowc2(material):
    """Check if material uses TFOWC2 extended material system."""
    return material.get('wd_tfowc2', 0) == 1


def set_tfowc2(material, enabled=True):
    """Toggle TFOWC2 mode on a material."""
    material['wd_tfowc2'] = 1 if enabled else 0


# ── Known direct PBR mappings ─────────────────────────────────────────────
_PBR_MAP = {
    'DiffuseColor1':    ('Base Color', 'color3'),
    'BaseColor':        ('Base Color', 'color3'),
    'Roughness':        ('Roughness', 'float'),
    'Metalness':        ('Metallic', 'float'),
    'NormalIntensity':  ('Normal Strength', 'float'),
    'Opacity':          ('Alpha', 'float'),
    'EmissiveColor':    ('Emission Color', 'color3'),
    'EmissiveIntensity':('Emission Strength', 'float'),
}

# ── Parameter types that hold texture file paths ──────────────────────────
_TEXTURE_PARAMS = {
    'DiffuseTexture1', 'DiffuseTexture2',
    'NormalTexture1', 'NormalTexture2',
    'MaskTexture1', 'MaskTexture2',
    'HeightTexture1', 'HeightTexture2',
    'EmissiveTexture',
    'AlphaTexture1',
    'PatternTexture1',
    'AnimTexture1',
    'LayerMaskTexture1',
}


def material_from_bin(bin_path, assign_to_obj=None):
    """Import .material.bin as a Blender Cycles/Eevee material.

    Common PBR params drive Principled BSDF; everything else is stored as
    custom properties on the material for round-trip export.

    Returns (material, descriptor_name).
    """
    if bpy is None:
        return None, None

    data = read_material_bin(bin_path)
    shader = data.pop('shader', '')
    bin_internal_name = data.pop('name', '')
    mat_name = os.path.splitext(os.path.basename(bin_path))[0]

    me = bpy.data.materials.get(mat_name)
    if me is None:
        me = bpy.data.materials.new(mat_name)
    me['xbg_mat_internal_name'] = bin_internal_name
    me.use_nodes = True
    tree = me.node_tree

    for n in list(tree.nodes):
        tree.nodes.remove(n)

    # Principled BSDF
    bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    out.location = (400, 0)
    tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    # Map known PBR params to BSDF inputs
    for param_name, (bsdf_input, ptype) in _PBR_MAP.items():
        val = data.get(param_name)
        if val is None or bsdf_input not in bsdf.inputs:
            continue
        sock = bsdf.inputs[bsdf_input]
        try:
            if ptype == 'float':
                sock.default_value = float(val)
            elif ptype == 'color3':
                parts = str(val).split(',')
                if len(parts) == 3:
                    sock.default_value = (
                        float(parts[0]), float(parts[1]), float(parts[2]), 1.0)
        except (ValueError, TypeError):
            pass

    # Store everything else as custom properties on the material
    for k, v in data.items():
        if isinstance(v, (int, float, str, bool)):
            try:
                me[k] = v
            except Exception:
                pass

    # Auto-detect TFOWC2 extended material system
    if any(k in data for k in _TFOWC2_PARAMS):
        set_tfowc2(me, True)

    # Stamp the shader family
    me['xbg_shader'] = shader
    me['xbg_source'] = bin_path

    if assign_to_obj:
        if hasattr(assign_to_obj, 'data'):
            assign_to_obj.data.materials.append(me)
        assign_to_obj.active_material = me

    return me, shader


def material_to_bin(mat, output_path):
    """Export a Blender material's PBR values + custom properties to .material.bin.

    Returns output_path.
    """
    if bpy is None:
        return output_path

    shader = mat.get('xbg_shader', 'WD2Generic')

    params = {}

    # Read Principled BSDF values back
    if mat.node_tree:
        bsdf = next((n for n in mat.node_tree.nodes
                      if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            # Reverse map BSDF inputs → param names
            for param_name, (bsdf_input, ptype) in _PBR_MAP.items():
                if bsdf_input in bsdf.inputs:
                    val = bsdf.inputs[bsdf_input].default_value
                    if ptype == 'float':
                        params[param_name] = float(val)
                    elif ptype == 'color3':
                        params[param_name] = f'{val[0]},{val[1]},{val[2]}'

    # Read custom properties (game-specific params not in PBR_MAP)
    for k in list(mat.keys()):
        if k.startswith('xbg_') or k.startswith('_'):
            continue
        if k in ('cycles', 'cycles_visibility', 'shadow_method',
                 'blend_method', 'surface_render_method', 'wd_tfowc2'):
            continue
        params[k] = mat[k]

    # TFOWC2: export extended specular channel / metalness params
    if is_tfowc2(mat):
        # Ensure critical TFOWC2 params are present with sane defaults
        _tfowc2_defaults = {
            'MaskRedChannelMode': 0,
            'MaskBlueChannelMode': 0,
            'MaskAlphaChannelMode': 0,
            'SwapSpecularGlossAndOcclusion': 0,
            'ColorizeDiffuse1Mode': 0,
            'InvertMaskForColorize': 0,
            'UseColorizeDiffuse1': 0,
            'ReflectionType': 0,
        }
        for k, default in _tfowc2_defaults.items():
            if k not in params:
                params[k] = default

    from .material_bin import MaterialBin, Param, crc32_name
    mb = MaterialBin()
    mb.name = mat.name
    mb.shader = shader
    for pname, pval in params.items():
        if isinstance(pval, float):
            ptype = 5  # TYPE_I32 stored as float bits
        elif isinstance(pval, str):
            ptype = 8  # TYPE_STR8
        elif isinstance(pval, bool):
            ptype = 6  # TYPE_BOOL
        else:
            ptype = 1  # TYPE_U32
        h = crc32_name(pname)
        mb.params.append(Param(type=ptype, name=pname, name_hash=h,
                               value=pval if isinstance(pval, list) else [pval]))
    mb.write(output_path)
    return output_path
