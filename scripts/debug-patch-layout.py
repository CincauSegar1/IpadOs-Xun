#!/usr/bin/env python3
"""Patch fileset_layout.py to diagnose native segment placements and overlaps."""
import sys
from pathlib import Path

targets = []
if len(sys.argv) > 1:
    targets.append(Path(sys.argv[1]))
else:
    for p in Path('.').glob('**/fileset_layout.py'):
        targets.append(p)

if not targets:
    targets = [Path('kits/XnuPrelink/fileset_layout.py')]

OLD_BLOCK = """            if any(begin < e and b < end for b, e in self.occupied + placed):
                raise ValueError(f'Native {segment["name"]} overlaps a retained segment')"""

NEW_BLOCK = """            overlap = [(b, e) for b, e in self.occupied + placed if begin < e and b < end]
            if overlap:
                import sys
                sys.stderr.write(f'\\n[layout-DIAGNOSTIC] === OVERLAP DETECTED FOR {segment["name"]} ===\\n')
                sys.stderr.write(f'[layout] Segment {segment["name"]}: begin={begin:#x}, end={end:#x}, size={segment["size"]:#x}\\n')
                sys.stderr.write(f'[layout] Placements so far: {[(s["name"], hex(self.placements.get(s["name"], 0)), hex(self.span(s["name"]))) for s in self.native.segments if s["name"] in self.placements]}\\n')
                sys.stderr.write(f'[layout] Overlapping ranges: {[(hex(b), hex(e)) for b, e in overlap]}\\n')
                # Identify which occupied entries match
                for b, e in overlap:
                    for kname, (_, koffset) in self.cache.entries.items():
                        from kc_image import Image as _Img
                        for kseg in _Img(self.cache.data, koffset).segments:
                            if kseg['va'] == b and kseg['va'] + kseg['size'] == e:
                                sys.stderr.write(f'[layout]   -> Matches kext {kname} segment {kseg["name"]} [{hex(b)}-{hex(e)}]\\n')
                    for p_begin, p_end in placed:
                        if p_begin == b and p_end == e:
                            sys.stderr.write(f'[layout]   -> Matches previously placed native segment [{hex(b)}-{hex(e)}]\\n')
                sys.stderr.flush()
                raise ValueError(f'Native {segment["name"]} overlaps a retained segment: {overlap}')"""

for target in targets:
    if not target.is_file():
        continue
    src = target.read_text()
    if OLD_BLOCK in src:
        target.write_text(src.replace(OLD_BLOCK, NEW_BLOCK))
        print(f'debug-patch-layout: successfully patched {target}')
    elif 'OVERLAP DETECTED' in src:
        print(f'debug-patch-layout: {target} already patched')
    else:
        print(f'debug-patch-layout: could not find exact match in {target}')
        for i, line in enumerate(src.splitlines()):
            if 'overlaps a retained' in line:
                print(f'  near line {i}: {line}')
