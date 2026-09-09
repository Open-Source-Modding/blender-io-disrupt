"""material_bin.py — Blender addon wrapper.

Canonical implementation is vendored inside the addon at
    modules/material_bin.py
and re-exported here so the relative import in material_editor_wd.py
(from .material_bin import ...) keeps working.  A standalone zip install
of the addon is fully self-contained.
"""
import os, sys, importlib.util

# Vendored canonical lives in the addon's modules/ dir (1-up from modules/Watch_Dogs/).
# Fall back to the shared dev layout (Ubisoft/Disrupt/material_bin.py, 3-up) for
# checkouts that predate the vendored copy.
_here = os.path.dirname(os.path.abspath(__file__))
_candidates = [
    os.path.normpath(os.path.join(_here, '..', 'material_bin.py')),            # vendored: modules/material_bin.py
    os.path.normpath(os.path.join(_here, '..', '..', 'material_bin.py')),      # addon root
    os.path.normpath(os.path.join(_here, '..', '..', '..', 'material_bin.py')),# addons/ or Ubisoft/Disrupt
    os.path.normpath(os.path.join(_here, 'material_bin.py')),                   # this dir (unlikely)
]
_standalone = next((p for p in _candidates if os.path.isfile(p)), None)

if _standalone is not None:
    _name = 'material_bin_standalone'
    _spec = importlib.util.spec_from_file_location(_name, _standalone)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _mod          # register before exec (dataclasses need it)
    _spec.loader.exec_module(_mod)
    from material_bin_standalone import (
        MaterialBin, Param, crc32_name, resolve_name,
        read_material_bin, write_material_bin,
        TYPE_U32, TYPE_VEC2, TYPE_VEC3, TYPE_VEC4, TYPE_I32,
        TYPE_BOOL, TYPE_ENUM, TYPE_STR8, TYPE_STR9, TYPE_STR10,
        TYPE_U32_2, TYPE_FLOAT, TYPE_NAMES,
        MAGIC, HEADER_SIZE,
    )
else:
    raise ImportError(
        "Canonical material_bin.py not found. It should be vendored at "
        "blender-io-disrupt/modules/material_bin.py (included in the addon zip). "
        "Re-download/reinstall the addon from the repo root as a .zip. "
        "Searched: " + "; ".join(_candidates)
    )
