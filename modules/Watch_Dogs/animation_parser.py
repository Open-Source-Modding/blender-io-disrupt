"""Disrupt engine animation format parsers — MAC + Markup.

Unified module for reading/writing MAC (Mesh Animation Clip) binary
and .markup XML animation data files used by the AnimationMarkupTool.

Format reference: .opencode/docs/animation_markup_format.md
Source: AnimationMarkupTool.exe decompilation (ilspycmd 11.0.0.9375)

MAC format: Binary animation containing curves, skeleton, flags, events,
            and recursive sub-animation parts. The "source" format.
Markup:     XML overlay defining time-stamped game events on the MAC timeline.

NOTE: This is the EDITOR format. The ENGINE runtime format is .mab
      (compiled, Oodle-compressed — see import_mab_wd.py).

Usage as library:
    from animation_parser import parse_mac, parse_markup, write_markup

    af = parse_mac("path/to/file.mac")
    print(af.type_id, len(af.skeleton.bones), "bones")

    doc = parse_markup("path/to/file.markup")
    for ev in doc.events:
        print(ev.time, ev.name, ev.event_type)

CLI:
    python3 animation_parser.py FILE.mac|FILE.markup
    python3 animation_parser.py --validate DIR/     # batch scan
"""

from __future__ import annotations

import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Optional


# ─── Enums ──────────────────────────────────────────────────────────────────

class CurveDataType:
    """AnimDiscreteCurve data type identifiers."""
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

    @classmethod
    def name(cls, value: int) -> str:
        return cls.NAMES.get(value, f"Unknown({value})")


class AnimFlagName:
    """AnimFileEvent type enum."""
    Unknown, MoveMgr_Poses, GameEvents, DurationEvent = 0, 1, 2, 3
    Max, Force32Bit = 4, 5

    NAMES = {0: "Unknown", 1: "MoveMgr_Poses", 2: "GameEvents",
             3: "DurationEvent", 4: "Max", 5: "Force32Bit"}


class FlagType:
    """AnimFlag flag type enum."""
    Global, Curve, Step, Spike, Frame, Unknown = 0, 1, 2, 3, 4, 5

    NAMES = {0: "Global", 1: "Curve", 2: "Step", 3: "Spike",
             4: "Frame", 5: "Unknown"}


class PartEventType:
    """AnimPart event type enum."""
    Unused0, InPossession = 0, 1
    Unused1, Unused2, Unused3, Unused4 = 2, 3, 4, 5
    IKPath, Anchor = 6, 7
    SubPartInPossession, Unused5 = 8, 9
    NumberOf = 10

    NAMES = {0: "Unused0", 1: "InPossession", 2: "Unused1", 3: "Unused2",
             4: "Unused3", 5: "Unused4", 6: "IKPath", 7: "Anchor",
             8: "SubPartInPossession", 9: "Unused5", 10: "NumberOf"}


# ─── MAC Data Classes ───────────────────────────────────────────────────────

@dataclass
class StringID:
    """Recurring structure: u32 type_id + i32 len + char[]."""
    type_id: int = 0
    value: str = ""

    def __repr__(self) -> str:
        return f'StringID(0x{self.type_id:08X}, "{self.value}")'


@dataclass
class AnimDiscreteCurve:
    """Single animation curve (translation, rotation, scale, or quaternion)."""
    curve_type: int = 0
    values: list[float] = field(default_factory=list)

    @property
    def type_name(self) -> str:
        return CurveDataType.name(self.curve_type)


@dataclass
class AnimCurve:
    """Simple curve — just reads and discards an i32."""
    data: int = 0


@dataclass
class AnimFlag:
    """Animation flag (name + type)."""
    name: StringID = field(default_factory=StringID)
    flag_type: int = 0

    @property
    def flag_type_name(self) -> str:
        return FlagType.NAMES.get(self.flag_type, f"Unknown({self.flag_type})")


@dataclass
class AnimFileParameter:
    """Parameter within an AnimFileEvent."""
    type: StringID = field(default_factory=StringID)
    name: StringID = field(default_factory=StringID)


@dataclass
class AnimFileEvent:
    """Embedded animation event."""
    event_type: int = 0
    time: float = 0.0
    parameters: list[AnimFileParameter] = field(default_factory=list)


@dataclass
class AnimDirNode:
    """Root motion node or bone curve container."""
    unk1: int = 0
    unk2: int = 0
    curves: list[AnimDiscreteCurve] = field(default_factory=list)


@dataclass
class AnimBone(AnimDirNode):
    """Skeleton bone — extends AnimDirNode with name, id, parent."""
    name: StringID = field(default_factory=StringID)
    bone_id: int = 0
    parent_id: int = -1


@dataclass
class AnimMomentum:
    """Root motion momentum."""
    unk1: int = 0
    unk2: int = 0
    direction_curve: AnimCurve = field(default_factory=AnimCurve)
    speed_curve: AnimCurve = field(default_factory=AnimCurve)


@dataclass
class AnimSkeleton:
    """Skeleton with bone list."""
    unk1: int = 0
    unk2: int = 0
    bones: list[AnimBone] = field(default_factory=list)


@dataclass
class AnimPart:
    """Animation sub-part — contains a recursive nested AnimationFile."""
    version_tag: int = 0
    name: StringID = field(default_factory=StringID)
    time: float = 0.0
    part_event_type: int = 0
    parent_id: StringID = field(default_factory=StringID)
    handle: StringID = field(default_factory=StringID)
    unk1: int = 0
    unk2: int = 0
    file: AnimationFile = field(default_factory=lambda: AnimationFile())
    handle_name: str = ""
    ik_bone_name: str = ""


@dataclass
class AnimationFile:
    """Complete MAC animation file — top-level parsed structure."""
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
            for c in self.skeleton.bones[0].curves:
                if c.values:
                    return len(c.values) / self.frame_rate
        return 0.0

    @property
    def bone_count(self) -> int:
        return len(self.skeleton.bones)

    @property
    def is_v9(self) -> bool:
        return abs(self.version_legacy - 9.0) < 0.01


# ─── Markup Data Classes ────────────────────────────────────────────────────

@dataclass
class ClipParam:
    """Animation clip range within a MAC file."""
    res_node_id: str = ""
    clip_start: float = 0.0
    clip_end: float = 0.0


@dataclass
class MarkupEvent:
    """A single time-stamped game event in a .markup file."""
    time: float = 0.0
    name: str = ""
    track: str = ""
    event_type: str = ""
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class MarkupDocument:
    """Parsed .markup XML document."""
    clip_params: list[ClipParam] = field(default_factory=list)
    events: list[MarkupEvent] = field(default_factory=list)


# ─── MAC Binary Reader ──────────────────────────────────────────────────────

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
        values: list[float] = []
        if (CurveDataType.TransX <= curve_type <= CurveDataType.TransZ or
                CurveDataType.QuatX <= curve_type <= CurveDataType.QuatW or
                CurveDataType.RotX <= curve_type <= CurveDataType.RotZ):
            values = list(struct.unpack(f'<{n_values}f', f.read(4 * n_values)))
        curves.append(AnimDiscreteCurve(curve_type=curve_type, values=values))
    return curves


def _read_animation_file(f: BinaryIO, depth: int = 0) -> AnimationFile:
    """Parse a full AnimationFile from a BinaryReader stream.

    Handles both legacy (v8.305) and v9.0 formats.  Recursion depth
    is limited to 10 to prevent stack overflow from malformed files.
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


# ─── Public MAC API ─────────────────────────────────────────────────────────

def parse_mac(filepath: str | Path) -> AnimationFile:
    """Parse a MAC (Mesh Animation Clip) binary file.

    Returns an AnimationFile dataclass with all parsed fields.
    Raises struct.error or ValueError on malformed files.
    """
    filepath = Path(filepath)
    with open(filepath, 'rb') as f:
        return _read_animation_file(f)


# ─── MAC Binary Writer ──────────────────────────────────────────────────────

def _write_string_id(f: BinaryIO, sid: StringID) -> None:
    """Write a StringID: u32 type_id + i32 len + char[len]."""
    f.write(struct.pack('<I', sid.type_id))
    raw = sid.value.encode('ascii', errors='replace')
    f.write(struct.pack('<i', len(raw)))
    f.write(raw)


def _write_curves(f: BinaryIO, curves: list[AnimDiscreteCurve]) -> None:
    """Write AnimDirNode curves: u32 count + AnimDiscreteCurve[count]."""
    f.write(struct.pack('<I', len(curves)))
    for c in curves:
        n_vals = len(c.values)
        f.write(struct.pack('<I', n_vals))
        f.write(struct.pack('<i', c.curve_type))
        f.write(struct.pack('<i', 0))  # unk
        if c.values:
            f.write(struct.pack(f'<{n_vals}f', *c.values))


def _write_animation_file(f: BinaryIO, af: AnimationFile) -> None:
    """Write a complete AnimationFile to a BinaryWriter stream.

    Writes v9.0 format by default.  Recursive AnimParts are written
    only if they have non-empty skeletons (common for sub-animations).
    """
    # Header — always write v9.0
    f.write(struct.pack('<f', 9.0))
    f.write(struct.pack('<H', af.file_version or 9))
    f.write(struct.pack('BB', af.exporter_major or 2,
                        af.exporter_minor or 2))

    # Type
    _write_string_id(f, af.type_id)

    # Frame rate
    f.write(struct.pack('<f', af.frame_rate or 30.0))

    # Source path — v9 format: i32 len + char[]
    src_raw = af.source.encode('ascii', errors='replace') if af.source else b''
    f.write(struct.pack('<i', len(src_raw)))
    f.write(src_raw)

    # AnimFlags
    f.write(struct.pack('<I', len(af.anim_flags)))
    for fl in af.anim_flags:
        _write_string_id(f, fl.name)
        f.write(struct.pack('<i', fl.flag_type))

    # AnimFileEvents
    f.write(struct.pack('<I', len(af.anim_events)))
    for ev in af.anim_events:
        f.write(struct.pack('<i', ev.event_type))
        f.write(struct.pack('<f', ev.time))
        f.write(struct.pack('<I', len(ev.parameters)))
        for p in ev.parameters:
            _write_string_id(f, p.type)
            _write_string_id(f, p.name)

    # AnimParts — write count, then each part
    f.write(struct.pack('<I', len(af.anim_parts)))
    for part in af.anim_parts:
        f.write(struct.pack('<i', part.version_tag or 987654321))
        f.write(struct.pack('<i', 0))  # second int of version tag
        _write_string_id(f, part.name)
        f.write(struct.pack('<d', part.time))
        f.write(struct.pack('<i', part.part_event_type))
        _write_string_id(f, part.parent_id)
        _write_string_id(f, part.handle)
        f.write(struct.pack('<ii', part.unk1, part.unk2))
        # Nested AnimationFile
        _write_animation_file(f, part.file)
        # Handle name
        hn = part.handle_name.encode('ascii', errors='replace')
        f.write(struct.pack('<i', len(hn)))
        f.write(hn)
        # IK bone name
        ik = part.ik_bone_name.encode('ascii', errors='replace')
        f.write(struct.pack('<i', len(ik)))
        f.write(ik)

    # DirNode (root motion)
    dn = af.dir_node
    f.write(struct.pack('<ii', dn.unk1, dn.unk2))
    _write_curves(f, dn.curves)

    # Momentum
    m = af.momentum
    f.write(struct.pack('<ii', m.unk1, m.unk2))
    f.write(struct.pack('<i', m.direction_curve.data))
    f.write(struct.pack('<i', m.speed_curve.data))

    # Skeleton
    sk = af.skeleton
    f.write(struct.pack('<ii', sk.unk1, sk.unk2))
    f.write(struct.pack('<I', len(sk.bones)))
    for bone in sk.bones:
        _write_string_id(f, bone.name)
        f.write(struct.pack('<I', bone.bone_id))
        f.write(struct.pack('<i', bone.parent_id))
        _write_curves(f, bone.curves)

    # Trailing string
    trail = af.trailing_string.encode('ascii', errors='replace') if af.trailing_string else b''
    f.write(struct.pack('<i', len(trail)))
    f.write(trail)


def write_mac(filepath: str | Path, af: AnimationFile) -> None:
    """Write an AnimationFile to a MAC binary file.

    Writes v9.0 format.  For best compatibility with the engine,
    populate type_id, frame_rate, and skeleton bones with curves.
    """
    filepath = Path(filepath)
    with open(filepath, 'wb') as f:
        _write_animation_file(f, af)


# ─── Markup XML Parser ──────────────────────────────────────────────────────

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
            params: dict[str, str] = {}
            for child in ev_elem:
                event_type = child.tag
                params = dict(child.attrib)
                break

            doc.events.append(MarkupEvent(
                time=time, name=name, track=track,
                event_type=event_type, params=params,
            ))

    return doc


def write_markup(filepath: str | Path, doc: MarkupDocument) -> None:
    """Write a .markup XML file from a MarkupDocument.

    Preserves the original format structure (EditionHelper > ClipParams,
    events > event with child element for type + params).
    """
    root = ET.Element("markup")

    # EditionHelper > ClipParams
    if doc.clip_params:
        eh = ET.SubElement(root, "EditionHelper")
        cps = ET.SubElement(eh, "ClipParams")
        for clip in doc.clip_params:
            ET.SubElement(cps, "ClipParam", {
                "ResNodeID": clip.res_node_id,
                "ClipStart": str(clip.clip_start),
                "ClipEnd": str(clip.clip_end),
            })

    # Events
    if doc.events:
        events_elem = ET.SubElement(root, "events")
        for ev in doc.events:
            ev_elem = ET.SubElement(events_elem, "event", {
                "time": str(ev.time),
                "name": ev.name,
                "Track": ev.track,
            })
            if ev.event_type:
                ET.SubElement(ev_elem, ev.event_type, ev.params)

    # Write with XML declaration
    tree = ET.ElementTree(root)
    ET.indent(tree, space="\t")
    tree.write(filepath, encoding="unicode", xml_declaration=True)


# ─── Pretty Printers ────────────────────────────────────────────────────────

def _dump_mac(af: AnimationFile, prefix: str = "") -> None:
    """Pretty-print an AnimationFile."""
    print(f"{prefix}MAC File:")
    print(f"{prefix}  version_legacy = {af.version_legacy}")
    if af.file_version:
        print(f"{prefix}  file_version = {af.file_version} "
              f"({af.exporter_major}.{af.exporter_minor})")
    print(f"{prefix}  type = {af.type_id!r}")
    print(f"{prefix}  frame_rate = {af.frame_rate}")
    if af.source:
        print(f"{prefix}  source = {af.source!r}")
    print(f"{prefix}  anim_flags = {len(af.anim_flags)}")
    for i, fl in enumerate(af.anim_flags):
        print(f"{prefix}    [{i}] {fl.name!r} type={fl.flag_type_name}")
    print(f"{prefix}  anim_events = {len(af.anim_events)}")
    for i, ev in enumerate(af.anim_events):
        print(f"{prefix}    [{i}] type={ev.event_type} time={ev.time:.4f} "
              f"params={len(ev.parameters)}")
    print(f"{prefix}  anim_parts = {len(af.anim_parts)}")
    for i, p in enumerate(af.anim_parts):
        print(f"{prefix}    [{i}] {p.name!r} time={p.time:.4f} "
              f"event_type={PartEventType.NAMES.get(p.part_event_type, '?')}")
        print(f"{prefix}         handle={p.handle!r} "
              f"handle_name={p.handle_name!r}")
        print(f"{prefix}         ik_bone={p.ik_bone_name!r}")
        _dump_mac(p.file, prefix + "         ")

    # DirNode
    dn = af.dir_node
    print(f"{prefix}  dir_node: unk=({dn.unk1}, {dn.unk2}) "
          f"curves={len(dn.curves)}")
    for i, c in enumerate(dn.curves):
        print(f"{prefix}    curve[{i}] type={c.type_name} "
              f"values={len(c.values)}")

    # Momentum
    m = af.momentum
    print(f"{prefix}  momentum: unk=({m.unk1}, {m.unk2})")

    # Skeleton
    sk = af.skeleton
    print(f"{prefix}  skeleton: unk=({sk.unk1}, {sk.unk2}) "
          f"bones={len(sk.bones)}")
    for i, b in enumerate(sk.bones[:10]):
        n_curves = len(b.curves)
        total_vals = sum(len(c.values) for c in b.curves)
        print(f"{prefix}    bone[{i}] {b.name!r} id={b.bone_id} "
              f"parent={b.parent_id} curves={n_curves} "
              f"total_values={total_vals}")
    if len(sk.bones) > 10:
        print(f"{prefix}    ... ({len(sk.bones) - 10} more bones)")

    if af.trailing_string:
        print(f"{prefix}  trailing_string = {af.trailing_string!r}")


def _dump_markup(doc: MarkupDocument) -> None:
    """Pretty-print a MarkupDocument."""
    print("Markup Document:")
    print(f"  clip_params = {len(doc.clip_params)}")
    for i, cp in enumerate(doc.clip_params):
        print(f"    [{i}] {cp.res_node_id!r} "
              f"[{cp.clip_start:.4f} — {cp.clip_end:.4f}]")
    print(f"  events = {len(doc.events)}")
    for i, ev in enumerate(doc.events):
        print(f"    [{i}] time={ev.time:.6f} name={ev.name!r} "
              f"track={ev.track!r} type={ev.event_type!r}")
        if ev.params:
            for k, v in ev.params.items():
                print(f"      {k} = {v!r}")


# ─── CLI ────────────────────────────────────────────────────────────────────

def _validate_directory(dirpath: Path, limit: int = 0) -> None:
    """Scan a directory for .mac and .markup files, parse each, print summary."""
    mac_files = sorted(dirpath.rglob('*.mac'))
    markup_files = sorted(dirpath.rglob('*.markup'))

    if limit:
        mac_files = mac_files[:limit]
        markup_files = markup_files[:limit]

    mac_ok = mac_fail = 0
    for f in mac_files:
        try:
            af = parse_mac(f)
            mac_ok += 1
        except Exception as e:
            print(f"  MAC FAIL: {f.name}: {e}", file=sys.stderr)
            mac_fail += 1

    markup_ok = markup_fail = 0
    for f in markup_files:
        try:
            doc = parse_markup(f)
            markup_ok += 1
        except Exception as e:
            print(f"  MARKUP FAIL: {f.name}: {e}", file=sys.stderr)
            markup_fail += 1

    total = mac_ok + mac_fail + markup_ok + markup_fail
    passed = mac_ok + markup_ok
    print(f"\nValidation complete: {passed}/{total} files parsed OK")
    print(f"  MAC:    {mac_ok}/{mac_ok + mac_fail} passed")
    print(f"  Markup: {markup_ok}/{markup_ok + markup_fail} passed")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.mac|file.markup>")
        print(f"       {sys.argv[0]} --validate <directory> [--limit N]")
        print(f"\nParse and dump Disrupt engine animation files.")
        print(f"Part of the blender-io-disrupt Watch Dogs addon.")
        sys.exit(1)

    if sys.argv[1] == '--validate':
        if len(sys.argv) < 3:
            print("Error: --validate requires a directory path", file=sys.stderr)
            sys.exit(1)
        dirpath = Path(sys.argv[2])
        limit = 0
        if '--limit' in sys.argv:
            idx = sys.argv.index('--limit')
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])
        if not dirpath.is_dir():
            print(f"Error: {dirpath} is not a directory", file=sys.stderr)
            sys.exit(1)
        _validate_directory(dirpath, limit)
    else:
        path = sys.argv[1]
        if path.endswith('.markup'):
            doc = parse_markup(path)
            _dump_markup(doc)
        else:
            af = parse_mac(path)
            _dump_mac(af)


if __name__ == '__main__':
    main()
