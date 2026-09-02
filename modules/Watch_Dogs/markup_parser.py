"""Disrupt engine .markup XML parser/writer.

.markup files are XML documents that define animation clip ranges and
time-stamped game events (footsteps, sounds, attacks, etc.) overlaid
onto a MAC animation timeline.

Format: .opencode/docs/animation_markup_format.md
Source: Disrupt.Animation.Markup.dll decompilation

Usage:
    from markup_parser import parse_markup, write_markup

    data = parse_markup("path/to/file.markup")
    # data = {"clips": [...], "events": [...]}

    write_markup("output.markup", data)

CLI:
    python3 markup_parser.py FILE.markup
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


# ─── Public API ─────────────────────────────────────────────────────────────

def parse_markup(filepath: str | Path) -> dict:
    """Parse a .markup XML file.

    Returns a dict with:
        clips:  list[dict] — each with keys:
                    res_node_id (str), clip_start (float), clip_end (float)
        events: list[dict] — each with keys:
                    time (float), name (str), track (str),
                    event_type (str), params (dict[str, str])
    """
    filepath = Path(filepath)
    tree = ET.parse(filepath)
    root = tree.getroot()

    clips: list[dict] = []
    events: list[dict] = []

    # EditionHelper > ClipParams > ClipParam
    eh = root.find("EditionHelper")
    if eh is not None:
        cps = eh.find("ClipParams")
        if cps is not None:
            for cp in cps.findall("ClipParam"):
                clips.append({
                    "res_node_id": cp.get("ResNodeID", ""),
                    "clip_start": float(cp.get("ClipStart", "0")),
                    "clip_end": float(cp.get("ClipEnd", "0")),
                })

    # events > event
    events_elem = root.find("events")
    if events_elem is not None:
        for ev in events_elem.findall("event"):
            # First child element determines the event type + params
            event_type = ""
            params: dict[str, str] = {}
            for child in ev:
                event_type = child.tag
                params = dict(child.attrib)
                break

            events.append({
                "time": float(ev.get("time", "0")),
                "name": ev.get("name", ""),
                "track": ev.get("Track", ""),
                "event_type": event_type,
                "params": params,
            })

    return {"clips": clips, "events": events}


def write_markup(filepath: str | Path, data: dict) -> None:
    """Write a .markup XML file from a dict.

    Args:
        filepath: Output path.
        data: Dict with 'clips' and 'events' keys (as returned by parse_markup).
    """
    root = ET.Element("markup")

    # EditionHelper > ClipParams
    clips = data.get("clips", [])
    if clips:
        eh = ET.SubElement(root, "EditionHelper")
        cps = ET.SubElement(eh, "ClipParams")
        for clip in clips:
            ET.SubElement(cps, "ClipParam", {
                "ResNodeID": clip.get("res_node_id", ""),
                "ClipStart": str(clip.get("clip_start", 0)),
                "ClipEnd": str(clip.get("clip_end", 0)),
            })

    # events
    events = data.get("events", [])
    if events:
        events_elem = ET.SubElement(root, "events")
        for ev in events:
            ev_elem = ET.SubElement(events_elem, "event", {
                "time": str(ev.get("time", 0)),
                "name": ev.get("name", ""),
                "Track": ev.get("track", ""),
            })
            event_type = ev.get("event_type", "")
            params = ev.get("params", {})
            if event_type:
                ET.SubElement(ev_elem, event_type, params)

    # Write with XML declaration matching the original format
    tree = ET.ElementTree(root)
    ET.indent(tree, space="\t")
    tree.write(filepath, encoding="unicode", xml_declaration=True)


# ─── CLI ────────────────────────────────────────────────────────────────────

def _print_summary(data: dict) -> None:
    """Pretty-print a markup summary."""
    clips = data.get("clips", [])
    events = data.get("events", [])

    print(f"Clips: {len(clips)}")
    for i, c in enumerate(clips):
        print(f"  [{i}] {c['res_node_id']!r} [{c['clip_start']:.4f} — {c['clip_end']:.4f}]")

    print(f"Events: {len(events)}")
    for i, ev in enumerate(events):
        etype = ev["event_type"]
        params_str = ""
        if ev["params"]:
            params_str = "  " + " ".join(f"{k}={v!r}" for k, v in ev["params"].items())
        print(f"  [{i}] t={ev['time']:.6f} name={ev['name']!r} track={ev['track']!r} "
              f"type={etype!r}{params_str}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.markup>")
        print("  Parse and summarize a Disrupt .markup XML file.")
        sys.exit(1)

    path = sys.argv[1]
    data = parse_markup(path)
    _print_summary(data)
