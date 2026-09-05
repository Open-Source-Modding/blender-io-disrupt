"""Watch Dogs Animation Markup Tool — MAC + Markup parsers.

MAC (Mesh Animation Clip) is the binary animation format loaded by
AnimationMarkupTool.exe.  It contains animation curves, skeleton,
embedded flags/events, and recursive sub-animation parts.

Markup files are separate XML documents overlaying time-stamped game
events onto the MAC timeline.

Format reference: .opencode/docs/animation_markup_format.md
Decompiled from: AnimationMarkupTool.exe (14065 lines via ilspycmd)

NOTE: This is the EDITOR format (loaded by AnimationMarkupTool.exe).
      The ENGINE runtime format is .mab (magic 0x329B, see import_mab_wd.py).
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Optional


# ─── Enums ──────────────────────────────────────────────────────────────────

class CurveDataType:
    RotX, RotY, RotZ = 0, 1, 2
    TransX, TransY, TransZ = 3, 4, 5
    ScaleX, ScaleY, ScaleZ = 6, 7, 8
    QuatX, QuatY, QuatZ, QuatW = 9, 10, 11, 12
    Radius, Height, Unknown = 13, 14, 15

    NAMES = {
        0: "RotX", 1: "RotY", 2: "RotZ",
        3: "TransX", 4: "TransY", 5: "TransZ",
        6: "ScaleX", 7: "ScaleY", 8: "ScaleZ",
        9: "QuatX", 10: "QuatY", 11: "QuatZ", 12: "QuatW",
        13: "Radius", 14: "Height", 15: "Unknown",
    }


class AnimFlagName:
    Unknown, MoveMgr_Poses, GameEvents, DurationEvent = 0, 1, 2, 3
    Max, Force32Bit = 4, 5


class FlagType:
    Global, Curve, Step, Spike, Frame, Unknown = 0, 1, 2, 3, 4, 5


class PartEventType:
    Unused0, InPossession = 0, 1
    IKPath, Anchor = 6, 7
    SubPartInPossession = 8
    NumberOf = 10


# ─── Data classes ───────────────────────────────────────────────────────────

@dataclass
class StringID:
    type_id: int = 0
    value: str = ""

    def __repr__(self) -> str:
        return f'StringID(0x{self.type_id:08X}, "{self.value}")'


@dataclass
class AnimDiscreteCurve:
    curve_type: int = 0
    values: list[float] = field(default_factory=list)

    @property
    def type_name(self) -> str:
        return CurveDataType.NAMES.get(self.curve_type, f"Unknown({self.curve_type})")


@dataclass
class AnimCurve:
    """Curve that reads and discards an i32."""
    data: int = 0


@dataclass
class AnimFlag:
    name: StringID = field(default_factory=StringID)
    flag_type: int = 0


@dataclass
class AnimFileParameter:
    type: StringID = field(default_factory=StringID)
    name: StringID = field(default_factory=StringID)


@dataclass
class AnimFileEvent:
    event_type: int = 0
    time: float = 0.0
    parameters: list[AnimFileParameter] = field(default_factory=list)


@dataclass
class AnimDirNode:
    unk1: int = 0
    unk2: int = 0
    curves: list[AnimDiscreteCurve] = field(default_factory=list)


@dataclass
class AnimBone(AnimDirNode):
    name: StringID = field(default_factory=StringID)
    bone_id: int = 0
    parent_id: int = -1


@dataclass
class AnimMomentum:
    unk1: int = 0
    unk2: int = 0
    direction_curve: AnimCurve = field(default_factory=AnimCurve)
    speed_curve: AnimCurve = field(default_factory=AnimCurve)


@dataclass
class AnimSkeleton:
    unk1: int = 0
    unk2: int = 0
    bones: list[AnimBone] = field(default_factory=list)


@dataclass
class AnimPart:
    version_tag: int = 0
    name: StringID = field(default_factory=StringID)
    time: float = 0.0
    part_event_type: int = 0
    parent_id: StringID = field(default_factory=StringID)
    handle: StringID = field(default_factory=StringID)
    unk1: int = 0
    unk2: int = 0
    file: "AnimationFile" = field(default_factory=lambda: AnimationFile())
    handle_name: str = ""
    ik_bone_name: str = ""


@dataclass
class AnimationFile:
    version_legacy: float = 0.0
    file_version: int = 0
    exporter_major: int = 0
    exporter_minor: int = 0
    type_id: StringID = field(default_factory=StringID)
    frame_rate: float = 0.0
    source: str = ""
    anim_flags: list[AnimFlag] = field(default_factory=list)
    anim_events: list[AnimFileEvent] = field(default_factory=list)
    anim_parts: list[AnimPart] = field(default_factory=list)
    dir_node: AnimDirNode = field(default_factory=AnimDirNode)
    momentum: AnimMomentum = field(default_factory=AnimMomentum)
    skeleton: AnimSkeleton = field(default_factory=AnimSkeleton)
    trailing_string: str = ""

    @property
    def duration(self) -> float:
        """Duration in seconds derived from skeleton bone frame count."""
        if self.skeleton.bones and self.frame_rate > 0:
            first_bone = self.skeleton.bones[0]
            n_frames = max(c.values for c in first_bone.curves) if first_bone.curves else [0]
            # Actually values_count is the length of the values list
            for c in first_bone.curves:
                if c.values:
                    return len(c.values) / self.frame_rate
        return 0.0


# ─── Binary reader ──────────────────────────────────────────────────────────

def _read_string_id(f: BinaryIO) -> StringID:
    """Read a StringID: u32 type_id + i32 len + char[len]."""
    type_id, = struct.unpack('<I', f.read(4))
    slen, = struct.unpack('<i', f.read(4))
    if 0 < slen < 10000:
        raw = f.read(slen)
        value = raw.decode('ascii', errors='replace')
    else:
        value = ""
    return StringID(type_id=type_id, value=value)


def _read_curves(f: BinaryIO) -> list[AnimDiscreteCurve]:
    """Read AnimDirNode curves: u32 count + AnimDiscreteCurve[count]."""
    n_curves, = struct.unpack('<I', f.read(4))
    curves = []
    for _ in range(n_curves):
        n_values, = struct.unpack('<I', f.read(4))
        curve_type, = struct.unpack('<i', f.read(4))
        unk, = struct.unpack('<i', f.read(4))
        values = []
        if (CurveDataType.TransX <= curve_type <= CurveDataType.TransZ or
                CurveDataType.QuatX <= curve_type <= CurveDataType.QuatW or
                CurveDataType.RotX <= curve_type <= CurveDataType.RotZ):
            values = list(struct.unpack(f'<{n_values}f', f.read(4 * n_values)))
        curves.append(AnimDiscreteCurve(curve_type=curve_type, values=values))
    return curves


def _read_animation_file(f: BinaryIO, depth: int = 0) -> AnimationFile:
    """Parse a full AnimationFile from a BinaryReader stream.

    depth limits recursion (AnimPart contains nested AnimationFile).
    """
    if depth > 10:
        raise RecursionError("AnimationFile nesting too deep")

    af = AnimationFile()

    # Header
    af.version_legacy, = struct.unpack('<f', f.read(4))

    # Version check — v9.0 has exporter version bytes
    _is_v9 = abs(af.version_legacy - 9.0) < 0.01
    if _is_v9:
        af.file_version, = struct.unpack('<H', f.read(2))
        af.exporter_major = f.read(1)[0]
        af.exporter_minor = f.read(1)[0]

    # Type
    af.type_id = _read_string_id(f)

    # Frame rate
    af.frame_rate, = struct.unpack('<f', f.read(4))

    # Source path — different encoding per version
    if _is_v9:
        # v9.0: raw i32 len + char[] (NOT StringID)
        slen = struct.unpack('<i', f.read(4))[0]
        if slen > 0:
            af.source = f.read(slen).decode('ascii', errors='replace')
    elif 7.0 < af.version_legacy < 2.139e9:
        af.source = _read_string_id(f).value

    # AnimFlags
    n_flags, = struct.unpack('<I', f.read(4))
    for _ in range(n_flags):
        name = _read_string_id(f)
        flag_type, = struct.unpack('<i', f.read(4))
        af.anim_flags.append(AnimFlag(name=name, flag_type=flag_type))

    # AnimFileEvents
    n_events, = struct.unpack('<I', f.read(4))
    for _ in range(n_events):
        etype, = struct.unpack('<i', f.read(4))
        etime, = struct.unpack('<f', f.read(4))
        n_params, = struct.unpack('<I', f.read(4))
        params = []
        for _ in range(n_params):
            ptype = _read_string_id(f)
            pname = _read_string_id(f)
            params.append(AnimFileParameter(type=ptype, name=pname))
        af.anim_events.append(AnimFileEvent(event_type=etype, time=etime,
                                            parameters=params))

    # AnimParts (recursive!)
    n_parts, = struct.unpack('<I', f.read(4))
    for _ in range(n_parts):
        part = AnimPart()
        # Version tag
        part.version_tag, = struct.unpack('<i', f.read(4))
        _ = f.read(4)  # second int of version tag
        part.name = _read_string_id(f)
        part.time, = struct.unpack('<d', f.read(8))
        part.part_event_type, = struct.unpack('<i', f.read(4))
        part.parent_id = _read_string_id(f)
        part.handle = _read_string_id(f)
        part.unk1, = struct.unpack('<i', f.read(4))
        part.unk2, = struct.unpack('<i', f.read(4))
        # Nested AnimationFile
        part.file = _read_animation_file(f, depth + 1)
        # Handle name string
        hlen, = struct.unpack('<i', f.read(4))
        if 0 < hlen < 10000:
            part.handle_name = f.read(hlen).decode('ascii', errors='replace')
        # IK bone name string
        ilen, = struct.unpack('<i', f.read(4))
        if 0 < ilen < 10000:
            part.ik_bone_name = f.read(ilen).decode('ascii', errors='replace')
        af.anim_parts.append(part)

    # AnimDirNode (root motion)
    af.dir_node.unk1, = struct.unpack('<i', f.read(4))
    af.dir_node.unk2, = struct.unpack('<i', f.read(4))
    af.dir_node.curves = _read_curves(f)

    # AnimMomentum
    af.momentum.unk1, = struct.unpack('<i', f.read(4))
    af.momentum.unk2, = struct.unpack('<i', f.read(4))
    af.momentum.direction_curve = AnimCurve(data=struct.unpack('<i', f.read(4))[0])
    af.momentum.speed_curve = AnimCurve(data=struct.unpack('<i', f.read(4))[0])

    # AnimSkeleton
    af.skeleton.unk1, = struct.unpack('<i', f.read(4))
    af.skeleton.unk2, = struct.unpack('<i', f.read(4))
    n_bones, = struct.unpack('<I', f.read(4))
    for _ in range(n_bones):
        bone = AnimBone()
        bone.name = _read_string_id(f)
        bone.bone_id, = struct.unpack('<I', f.read(4))
        bone.parent_id, = struct.unpack('<i', f.read(4))
        bone.curves = _read_curves(f)
        af.skeleton.bones.append(bone)

    # Trailing string
    tlen, = struct.unpack('<i', f.read(4))
    if 0 < tlen < 10000:
        af.trailing_string = f.read(tlen).decode('ascii', errors='replace')

    return af


def parse_mac(filepath: str | Path) -> AnimationFile:
    """Parse a MAC (Mesh Animation Clip) binary file.

    Returns an AnimationFile dataclass with all parsed fields.
    """
    filepath = Path(filepath)
    with open(filepath, 'rb') as f:
        return _read_animation_file(f)


# ─── Markup XML parser ──────────────────────────────────────────────────────

@dataclass
class MarkupEvent:
    """A single event in a .markup XML file."""
    time: float = 0.0
    name: str = ""
    track: str = ""
    event_type: str = ""
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class ClipParam:
    res_node_id: str = ""
    clip_start: float = 0.0
    clip_end: float = 0.0


@dataclass
class MarkupDocument:
    """Parsed .markup XML document."""
    clip_params: list[ClipParam] = field(default_factory=list)
    events: list[MarkupEvent] = field(default_factory=list)


def parse_markup(filepath: str | Path) -> MarkupDocument:
    """Parse a .markup XML file.

    Returns a MarkupDocument with clip_params and events.
    """
    filepath = Path(filepath)
    tree = ET.parse(filepath)
    root = tree.getroot()
    doc = MarkupDocument()

    # EditionHelper > ClipParams
    eh = root.find('EditionHelper')
    if eh is not None:
        cps = eh.find('ClipParams')
        if cps is not None:
            for cp_elem in cps.findall('ClipParam'):
                doc.clip_params.append(ClipParam(
                    res_node_id=cp_elem.get('ResNodeID', ''),
                    clip_start=float(cp_elem.get('ClipStart', '0')),
                    clip_end=float(cp_elem.get('ClipEnd', '0')),
                ))

    # Events
    events_elem = root.find('events')
    if events_elem is not None:
        for ev_elem in events_elem.findall('event'):
            time = float(ev_elem.get('time', '0'))
            name = ev_elem.get('name', '')
            track = ev_elem.get('Track', '')

            # First child element is the event type
            event_type = ""
            params = {}
            for child in ev_elem:
                event_type = child.tag
                params = dict(child.attrib)
                break

            doc.events.append(MarkupEvent(
                time=time, name=name, track=track,
                event_type=event_type, params=params,
            ))

    return doc


# ─── CLI ────────────────────────────────────────────────────────────────────

def _dump_mac(af: AnimationFile, prefix: str = "") -> None:
    """Pretty-print an AnimationFile."""
    print(f"{prefix}MAC File:")
    print(f"{prefix}  version_legacy = {af.version_legacy}")
    if af.file_version:
        print(f"{prefix}  file_version = {af.file_version} ({af.exporter_major}.{af.exporter_minor})")
    print(f"{prefix}  type = {af.type_id!r}")
    print(f"{prefix}  frame_rate = {af.frame_rate}")
    if af.source:
        print(f"{prefix}  source = {af.source!r}")
    print(f"{prefix}  anim_flags = {len(af.anim_flags)}")
    for i, fl in enumerate(af.anim_flags):
        print(f"{prefix}    [{i}] {fl.name!r} type={fl.flag_type}")
    print(f"{prefix}  anim_events = {len(af.anim_events)}")
    for i, ev in enumerate(af.anim_events):
        print(f"{prefix}    [{i}] type={ev.event_type} time={ev.time:.4f} params={len(ev.parameters)}")
    print(f"{prefix}  anim_parts = {len(af.anim_parts)}")
    for i, p in enumerate(af.anim_parts):
        print(f"{prefix}    [{i}] {p.name!r} time={p.time:.4f} event_type={p.part_event_type}")
        print(f"{prefix}         handle={p.handle!r} handle_name={p.handle_name!r}")
        print(f"{prefix}         ik_bone={p.ik_bone_name!r}")
        _dump_mac(p.file, prefix + "         ")

    # DirNode
    dn = af.dir_node
    print(f"{prefix}  dir_node: unk=({dn.unk1}, {dn.unk2}) curves={len(dn.curves)}")
    for i, c in enumerate(dn.curves):
        print(f"{prefix}    curve[{i}] type={c.type_name} values={len(c.values)}")

    # Momentum
    m = af.momentum
    print(f"{prefix}  momentum: unk=({m.unk1}, {m.unk2})")

    # Skeleton
    sk = af.skeleton
    print(f"{prefix}  skeleton: unk=({sk.unk1}, {sk.unk2}) bones={len(sk.bones)}")
    for i, b in enumerate(sk.bones[:10]):
        n_curves = len(b.curves)
        total_vals = sum(len(c.values) for c in b.curves)
        print(f"{prefix}    bone[{i}] {b.name!r} id={b.bone_id} parent={b.parent_id} "
              f"curves={n_curves} total_values={total_vals}")
    if len(sk.bones) > 10:
        print(f"{prefix}    ... ({len(sk.bones) - 10} more bones)")

    if af.trailing_string:
        print(f"{prefix}  trailing_string = {af.trailing_string!r}")


def _dump_markup(doc: MarkupDocument) -> None:
    """Pretty-print a MarkupDocument."""
    print("Markup Document:")
    print(f"  clip_params = {len(doc.clip_params)}")
    for i, cp in enumerate(doc.clip_params):
        print(f"    [{i}] {cp.res_node_id!r} [{cp.clip_start:.4f} - {cp.clip_end:.4f}]")
    print(f"  events = {len(doc.events)}")
    for i, ev in enumerate(doc.events):
        print(f"    [{i}] time={ev.time:.6f} name={ev.name!r} track={ev.track!r} "
              f"type={ev.event_type!r}")
        if ev.params:
            for k, v in ev.params.items():
                print(f"      {k} = {v!r}")


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.mac|file.markup>")
        print(f"  Parses and dumps MAC binary or Markup XML files.")
        print(f"  Part of the blender-io-disrupt Watch Dogs addon.")
        sys.exit(1)

    path = sys.argv[1]
    if path.endswith('.markup'):
        doc = parse_markup(path)
        _dump_markup(doc)
    else:
        af = parse_mac(path)
        _dump_mac(af)
