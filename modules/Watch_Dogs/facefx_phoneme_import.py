"""FaceFX phoneme data importer for Blender.

Parses the tab-separated ``.txt`` files exported by FaceFX Studio's
``FaceFX_ExportPhonemeData.py`` and creates Blender shape key animations
for lip-sync.

Format (one phoneme per line)::

    PHONEME  START_TIME  END_TIME  CONFIDENCE  VOLUME  WORD_RATE  PITCH

All fields are space-padded to 20 characters.  Phonemes use the
Sphinx/ARPAbet subset (P, B, T, D, K, G, M, N, NG, R, F, V, TH, S, Z,
SH, ZH, H, Y, L, W, CH, JH, IY, EH, AE, AA, AO, OY, UW, AH, IH, UH,
ER, EY, AW, AY, OW, *SIL).

Usage (in Blender)::

    from modules.Watch_Dogs.facefx_phoneme_import import import_phoneme_txt
    import_phoneme_txt(filepath, target_object)

Or via operator: File > Import > FaceFX Phoneme Data (.txt)
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple, Optional

try:
    import bpy
except ImportError:
    bpy = None


# ---------------------------------------------------------------------------
# Phoneme → viseme mapping (Sphinx/ARPAbet → Blender shape key names)
# ---------------------------------------------------------------------------

# Standard viseme set for lip-sync.  Multiple phonemes map to the same
# viseme (e.g. P/B/M all close the lips).
PHONEME_TO_VISEME = {
    # Silence
    '*SIL': 'viseme_sil',
    # Bilabial
    'P': 'viseme_PP', 'B': 'viseme_PP', 'M': 'viseme_PP',
    # Labiodental
    'F': 'viseme_FF', 'V': 'viseme_FF',
    # Dental
    'TH': 'viseme_TH', 'DH': 'viseme_TH',
    # Alveolar
    'T': 'viseme_DD', 'D': 'viseme_DD', 'N': 'viseme_nn',
    'L': 'viseme_nn', 'S': 'viseme_SS', 'Z': 'viseme_SS',
    # Postalveolar
    'SH': 'viseme_SH', 'ZH': 'viseme_SH', 'CH': 'viseme_CH', 'JH': 'viseme_CH',
    # Velar
    'K': 'viseme_kk', 'G': 'viseme_kk', 'NG': 'viseme_nn',
    # Glottal
    'H': 'viseme_PP', 'HH': 'viseme_PP',
    # Rhotic
    'R': 'viseme_RR', 'RA': 'viseme_RR', 'RU': 'viseme_RR', 'ER': 'viseme_RR',
    'AXR': 'viseme_RR', 'EXR': 'viseme_RR',
    # Approximant
    'Y': 'viseme_Y', 'W': 'viseme_W',
    # Vowels — open/close variants
    'IY': 'viseme_ih', 'IH': 'viseme_ih', 'UU': 'viseme_ih',
    'EH': 'viseme_E', 'E': 'viseme_E', 'EN': 'viseme_E',
    'AE': 'viseme_aa', 'A': 'viseme_aa',
    'AA': 'viseme_aa', 'AAN': 'viseme_aa',
    'AH': 'viseme_UH', 'AX': 'viseme_UH', 'UX': 'viseme_UH',
    'AO': 'viseme_oh', 'AON': 'viseme_oh',
    'OY': 'viseme_oh', 'O': 'viseme_oh', 'ON': 'viseme_oh',
    'UW': 'viseme_oh', 'UY': 'viseme_oh', 'EU': 'viseme_oh',
    'OE': 'viseme_oh', 'OEN': 'viseme_oh',
    'UH': 'viseme_UH',
    'AW': 'viseme_oh', 'AY': 'viseme_aa', 'OW': 'viseme_oh',
    'EY': 'viseme_E',
    # Flaps
    'FLAP': 'viseme_DD', 'TS': 'viseme_SS',
    'CX': 'viseme_PP', 'X': 'viseme_PP', 'GH': 'viseme_PP',
}

# All unique viseme names (for creating shape keys)
VISEME_NAMES = sorted(set(PHONEME_TO_VISEME.values()))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(
    r'^(\S+)\s+'        # phoneme
    r'(\d+\.\d{3})\s+'  # start_time
    r'(\d+\.\d{3})\s+'  # end_time
    r'(\d+\.\d{3})\s+'  # confidence
    r'(\d+\.\d{3})\s+'  # volume
    r'(\d+\.\d{3})\s+'  # word_rate
    r'(\d+\.\d{3})'     # pitch
)


def parse_phoneme_txt(filepath: str) -> List[dict]:
    """Parse a FaceFX phoneme .txt file.

    Returns a list of dicts, one per phoneme::

        [{'phoneme': str, 'start': float, 'end': float,
          'confidence': float, 'volume': float, 'word_rate': float,
          'pitch': float}, ...]
    """
    entries = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = _LINE_RE.match(line)
            if m:
                entries.append({
                    'phoneme': m.group(1),
                    'start': float(m.group(2)),
                    'end': float(m.group(3)),
                    'confidence': float(m.group(4)),
                    'volume': float(m.group(5)),
                    'word_rate': float(m.group(6)),
                    'pitch': float(m.group(7)),
                })
    return entries


# ---------------------------------------------------------------------------
# Blender builder
# ---------------------------------------------------------------------------

def _ensure_shape_keys(mesh_obj) -> Optional[object]:
    """Ensure the mesh has a basis shape key and return the key data block."""
    if bpy is None or mesh_obj is None:
        return None
    if not mesh_obj.data.shape_keys:
        mesh_obj.shape_key_add(name='Basis', from_mix=False)
    return mesh_obj.data.shape_keys


def import_phoneme_txt(
    filepath: str,
    target_object=None,
    fps: float = 30.0,
    confidence_threshold: float = 0.1,
) -> dict:
    """Import a FaceFX phoneme .txt file into Blender.

    Creates viseme shape keys on the target mesh and keys them over time
    based on phoneme timing and confidence.

    Args:
        filepath: Path to the .txt file.
        target_object: Blender mesh object to apply lip-sync to.
            If None, uses the active object.
        fps: Frame rate for time→frame conversion.
        confidence_threshold: Minimum confidence to include a phoneme.

    Returns:
        {'phonemes': int, 'shape_keys': int, 'frames': (start, end)}
    """
    if bpy is None:
        raise RuntimeError("bpy unavailable")

    entries = parse_phoneme_txt(filepath)
    if not entries:
        raise ValueError(f"No phoneme data found in {filepath}")

    # Select target
    obj = target_object or bpy.context.active_object
    if obj is None:
        raise ValueError("No target object selected")
    if obj.type != 'MESH':
        raise ValueError(f"Target must be a mesh, got {obj.type}")

    # Ensure we're in object mode
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Create shape keys
    sk_data = _ensure_shape_keys(obj)
    created_keys = set()

    for viseme in VISEME_NAMES:
        if viseme not in sk_data.key_blocks:
            obj.shape_key_add(name=viseme, from_mix=False)
            created_keys.add(viseme)

    # Frame range
    scene = bpy.context.scene
    scene.render.fps = int(fps)
    start_frame = float('inf')
    end_frame = 0.0

    # Key each viseme
    for entry in entries:
        if entry['confidence'] < confidence_threshold:
            continue
        if entry['phoneme'] == '*SIL':
            continue

        viseme = PHONEME_TO_VISEME.get(entry['phoneme'])
        if viseme is None:
            continue

        start_sec = entry['start']
        end_sec = entry['end']
        confidence = entry['confidence']

        start_f = int(start_sec * fps) + 1  # Blender 1-based
        peak_f = int((start_sec + end_sec) * 0.5 * fps) + 1
        end_f = int(end_sec * fps) + 1

        start_frame = min(start_frame, start_f)
        end_frame = max(end_frame, end_f)

        sk = sk_data.key_blocks.get(viseme)
        if sk is None:
            continue

        # Key: 0 before, confidence at peak, 0 after
        sk.value = 0.0
        sk.keyframe_insert(data_path="value", frame=start_f)
        sk.value = confidence
        sk.keyframe_insert(data_path="value", frame=peak_f)
        sk.value = 0.0
        sk.keyframe_insert(data_path="value", frame=end_f)

    # Mark shape key import metadata
    obj['facefx_src'] = filepath
    obj['facefx_phonemes'] = len(entries)

    return {
        'phonemes': len(entries),
        'shape_keys': len(created_keys),
        'frames': (start_frame if start_frame != float('inf') else 1,
                    end_frame if end_frame else 1),
    }
