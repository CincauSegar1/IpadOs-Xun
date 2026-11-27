#!/usr/bin/env python3
"""Patch fileset_layout.py validate() to print which placements cause the overlap."""
import sys
from pathlib import Path

target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('kits/XnuPrelink/fileset_layout.py')
src = target.read_text()

old = ('            if any(begin < e and b < end for b, e in self.occupied + placed):\n'
       '                raise ValueError(f\'Native {segment["name"]} overlaps a retained segment\')')
new = ('            overlap = [(b,e) for b,e in self.occupied + placed if begin < e and b < end]\n'
       '            if overlap:\n'
       '                print(f\'[layout] {segment["name"]} {begin:#x}-{end:#x} overlaps: {overlap}\')\n'
       '                print(f\'[layout] placements: {self.placements}\')\n'
       '                raise ValueError(f\'Native {segment["name"]} overlaps a retained segment\')')

if old in src:
    target.write_text(src.replace(old, new))
    print(f'debug-patch-layout: patched {target}')
else:
    print(f'debug-patch-layout: target string not found in {target}; likely already patched or version changed')
    # Print context around the error line to help diagnose
    for i, line in enumerate(src.splitlines()):
        if 'overlaps a retained' in line:
            print(f'  line {i}: {line!r}')
