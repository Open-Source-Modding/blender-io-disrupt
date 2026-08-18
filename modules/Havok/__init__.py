"""Havok HKX format support — importer/exporter for WD1/WD2/WDL collision files.

This module provides a general-purpose HKX file reader and writer that can:
- Parse old packfile format (Havok 2012, used by WD1)
- Parse TAG0 format (Havok 2017+, used by WD2/WDL/Legion)
- Read all collision shape types (convex, box, compressed mesh)
- Write modified collision data back to HKX format
"""
