# Mission Tasks

## Task List

[x] Trace fixup resolution logic and document exact packfile layout for WD1/WD2
[x] Deep-dive into WD1/WD2 injector internals — understand packfile serialization fully
[x] Map compressed mesh section header fields (+0x4c, +0x50, +0x54) — +0x48 confirmed as firstPackedVertexIndex; +0x4c/+0x50/+0x54 remain unknown (values too large for array indices, likely bit offsets or BVH metadata)
[ ] Analyze primitive files (Havok 2017.2) from Legion leak with IDA for class layouts
[ ] Decode compressed mesh triangle bitstream encoding scheme
[ ] Build full compressed mesh decoder (vertices + triangles)

## Completed

[x] WD1 HKX format decoded — all classes, offsets, transforms, connectivity
[x] WD1 HKX injector built — convex vertex displacement + box halfExtents, round-trip test passing
[x] WD2 HKX import/inject wired — operators, panels, wrapper, round-trip test
[x] Compressed mesh tree structure analyzed — sections, primitives, data runs
[x] Section header field mapping confirmed — +0x48=firstPackedVertexIndex, +0x58=numPackedVertices
[x] Legion primitive files discovered — Havok 2017.2 (SDKV 20170200@), contain compressed mesh classes
