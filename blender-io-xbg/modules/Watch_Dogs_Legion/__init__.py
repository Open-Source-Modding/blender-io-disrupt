"""Watch Dogs Legion — self-contained import/export package.

WDL ships compiled models as binary .xbg files with a MOEG header
(version 0x95/0x46 — same format family as WD2).  The companion .skel
file holds the skeleton.

This module reuses the WD2 MOEG parser (import_wd2_xbg) and extends
it with vertex offset tracking so edits can be injected back into the
binary file.
"""
