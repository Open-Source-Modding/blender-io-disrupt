"""material_bin.py — Blender addon wrapper.

Canonical implementation lives at the repo root: material_bin.py

This file re-exports everything so the relative import in
material_editor_wd.py (from .material_bin import ...) keeps working.
"""
import os, sys, importlib.util

_standalone = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'material_bin.py'))

if os.path.isfile(_standalone):
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
    raise ImportError(f"Canonical material_bin.py not found at {_standalone} — install it alongside the blender-io-disrupt directory")
