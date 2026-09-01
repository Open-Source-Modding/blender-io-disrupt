"""Auto-detect game from file header bytes.

Reads the first ~64 bytes of a file and identifies which Ubisoft engine
game it belongs to, based on magic bytes and version markers found in
the actual importer source files.

Detection is extension-first, then magic/version within each extension:

  Extension  Magic / Signature                         Game
  ---------  ----------------------------------------  ------
  .xbg       MOEG u32 + version (97, 50)               WD1
  .xbg       MOEG u32 + version (0x89, 0x46)           WD2
  .xbg       MOEG u32 + version (0x95, 0x46)           WD3 (WDL)
  .glm       starts with b"VERSION"                     WD2
  .hkx       HAVOK_MAGIC at offset 0 or 16             WD1
  .hkx       TAG0 at offset 0x14                        WD2 / WD3
  .mab       u32 0x329B                                 WD1
  .mab       u32 0x46B4 or 0x46AF                       WDL / WD2
  .skel      b"nbCF"                                    ambiguous (WD1/2/3)

Sources (where each constant was verified in the codebase):
  - WD1 MOEG v97/50: modules/Watch_Dogs/import_wd.py:142,145
  - WD2 MOEG (0x89,0x46): modules/Watch_Dogs_2/import_wd2_xbg.py:117
  - WDL MOEG (0x95,0x46): modules/Watch_Dogs_Legion/import_wdl_xbg.py:113
  - WD1 Havok magic: modules/Havok/import_hkx_wd.py:115
  - TAG0 magic: modules/Havok/import_hkx.py:35
  - WD1 MAB magic 0x329B: modules/Watch_Dogs/import_mab_wd.py:5
  - WDL/WD2 MAB magic: modules/Watch_Dogs_Legion/import_mab_wdl.py:33-34
  - nbCF skeleton: modules/Watch_Dogs/import_skeleton_wd.py:44
"""

import os
import struct


# ── Magic constants (from importer source) ─────────────────────────────────

# MOEG xbg (Ubisoft Disrupt binary)
_MOEG = b'MOEG'

# Havok packfile magic (64-bit, old format — WD1)
_HAVOK_MAGIC = b'\x57\xe0\xe0\x57\x10\xc0\xc0\x10'

# TAG0 (Havok 2017+ tagfile — WD2/WD3)
_TAG0 = b'TAG0'

# nbCF skeleton (WD1/WD2/WD3 — ambiguous)
_NBCF = b'nbCF'

# WD1 MAB animation
_WD1_MAB_MAGIC = 0x329B

# WDL / WD2 MAB animation
_WDL_MAB_MAGIC = 0x46B4
_WD2_MAB_MAGIC = 0x46AF


def _read_head(path, n=64):
    """Read first *n* bytes of a file, return bytes or None on error."""
    try:
        with open(path, 'rb') as f:
            return f.read(n)
    except OSError:
        return None


def _ext(path):
    """Lowercase file extension without the dot."""
    return os.path.splitext(path)[1].lower().lstrip('.')


# ── Public API ──────────────────────────────────────────────────────────────

def detect_game_from_path(path):
    """Detect the game from a file's header bytes.

    Returns a game ID string (e.g. 'WD1', 'WD2', 'WD3') or None if
    the file cannot be identified.

    Detection is extension-first, then magic/version within each extension.
    For ambiguous cases (e.g. .skel which is nbCF across WD1/2/3), returns
    None — the user should select manually via the picker.
    """
    head = _read_head(path)
    if head is None or len(head) < 8:
        return None

    ext = _ext(path)

    # ── .xbg (MOEG binary) ─────────────────────────────────────────────
    if ext == 'xbg':
        return _detect_xbg(head)

    # ── .glm (WD2 text format) ─────────────────────────────────────────
    if ext == 'glm':
        if head[:7] == b'VERSION':
            return 'WD2'
        return None

    # ── .hkx (Havok collision) ─────────────────────────────────────────
    if ext == 'hkx':
        return _detect_hkx(head)

    # ── .mab (animation) ───────────────────────────────────────────────
    if ext == 'mab':
        return _detect_mab(head)

    # ── .skel (skeleton — ambiguous nbCF) ──────────────────────────────
    if ext == 'skel':
        if head[:4] == _NBCF:
            # nbCF v3 used by WD1, WD2, and WDL — cannot distinguish
            return None
        return None

    # ── Unknown extension ──────────────────────────────────────────────
    return None


def _detect_xbg(head):
    """Detect game from an .xbg file header."""
    magic = head[:4]

    if magic == _MOEG:
        return _detect_moeg(head)
    return None


def _detect_moeg(head):
    """Detect game from a MOEG-header .xbg (WD1/WD2/WDL)."""
    if len(head) < 8:
        return None

    # MOEG header: magic(4) + ver_major(u16) + ver_minor(u16)
    ver_major, ver_minor = struct.unpack_from('<HH', head, 4)

    if (ver_major, ver_minor) == (97, 50):
        return 'WD1'
    elif (ver_major, ver_minor) == (0x89, 0x46):
        return 'WD2'
    elif (ver_major, ver_minor) == (0x95, 0x46):
        # Ambiguous: WD2 static .xbg or WDL .xbg — both use 0x95/0x46.
        # WD2 static props use this version too (see import_wd2_xbg.py:117).
        # Default to WD3 (WDL) since that's the more common use case.
        return 'WD3'
    return None


def _detect_hkx(head):
    """Detect game from an .hkx collision file."""
    # WD1: old Havok 64-bit packfile — HAVOK_MAGIC at offset 0 or 16
    if head[:8] == _HAVOK_MAGIC:
        return 'WD1'
    if len(head) >= 24 and head[16:24] == _HAVOK_MAGIC:
        return 'WD1'

    # WD2/WD3: TAG0 format — TAG0 at offset 0x14
    if len(head) >= 0x18 and head[0x14:0x18] == _TAG0:
        # Both WD2 and WD3 use TAG0 — ambiguous.
        # The SDKV string at 0x20 could help, but WD2 and WDL both use
        # Havok 2017.2.0. Return None to let user pick.
        return None

    return None


def _detect_mab(head):
    """Detect game from a .mab animation file."""
    if len(head) < 4:
        return None

    magic = struct.unpack_from('<I', head, 0)[0]

    if magic == _WD1_MAB_MAGIC:
        return 'WD1'
    elif magic in (_WDL_MAB_MAGIC, _WD2_MAB_MAGIC):
        # Both WDL (0x46B4) and WD2 (0x46AF) use the same inner format.
        # Cannot distinguish — return None.
        return None

    return None
