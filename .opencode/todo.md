# Mission Tasks

## Task List

[x] Trace fixup resolution logic and document exact packfile layout for WD1/WD2
[x] Deep-dive into WD1/WD2 injector internals — understand packfile serialization fully
[x] Map compressed mesh section header fields (+0x4c, +0x50, +0x54) — +0x48 confirmed as firstPackedVertexIndex; +0x4c/+0x50/+0x54 remain unknown (values too large for array indices, likely bit offsets or BVH metadata)
[x] Analyze primitive files (Havok 2017.2) — idalib confirms class names at correct offsets, but TAG0 TYPE section binary format requires IDA GUI to decode member layouts
[x] Decode compressed mesh bitstream encoding scheme — BLOCKED: requires TAG0 TYPE section parsing + primitive file binary analysis (IDA GUI needed)
[x] Build full compressed mesh decoder — BLOCKED: depends on bitstream encoding scheme

## Completed

[x] WD1 HKX format decoded — all classes, offsets, transforms, connectivity
[x] WD1 HKX injector built — convex vertex displacement + box halfExtents, round-trip test passing
[x] WD2 HKX import/inject wired — operators, panels, wrapper, round-trip test
[x] Compressed mesh tree structure analyzed — sections, primitives, data runs
[x] Section header field mapping confirmed — +0x48=firstPackedVertexIndex, +0x58=numPackedVertices
[x] Legion primitive files discovered — Havok 2017.2 (SDKV 20170200@), contain compressed mesh classes
