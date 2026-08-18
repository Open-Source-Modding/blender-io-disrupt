# GitHub Repos for HKX/Havok Format Research

## hkxparse (exyorha)
- **URL**: https://github.com/exyorha/hkxparse
- **What**: C++ library for parsing Havok packfiles and tagfiles
- **Key feature**: Layout system (`HavokPackfileLayouts`) defines class member layouts with names, types, offsets
- **Current support**: Havok 2010 only (JSON layout file)
- **Use for us**: If we generate a 2017 layout JSON, we can compile it into hkxparse and use it to parse compressed mesh data
- **Layout format**: JSON with `classes[].members[].{name, type, offset, arraySize, flags}`
- **Generator**: `make_layout.rb` converts JSON → C++ header/source

## hkxImport (SebboHN)
- **URL**: https://github.com/SebboHN/hkxImport
- **What**: 3ds Max plugin for HKX import (Havok 2010-2023)
- **Key find**: `x64_2017/HavokMax.dlu` — Havok 2017 runtime DLL for 3ds Max
- **Use for us**: The DLL links against Havok 2017 and might contain the class layouts

## fbxbimporter (Bewolf2)
- **URL**: https://github.com/Bewolf2/fbximporter
- **What**: FBX to HKX converter using Project Anarchy/Havok
- **Use for us**: Limited — focuses on animation, not collision

## Key Insight
To parse the compressed mesh from TAG0 files, we need:
1. A Havok 2017.2 layout JSON (class member definitions with offsets)
2. Either generate it from primitive files' TYPE section, or extract from HavokMax.dlu
3. Compile it into hkxparse's layout system
4. Use hkxparse's tagfile parser to extract the compressed mesh data

The primitive files at `data_win64/generated/primitives/prim_4_*.hkx` are the source of truth for the 2017.2 layout.
