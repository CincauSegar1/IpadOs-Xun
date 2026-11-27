#!/usr/bin/env python3
"""Patch fileset_layout.py to dynamically allocate native __DATA past __LINKEDIT when it exceeds room before retained kexts."""
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

OLD_DATA_CODE = """        self.reserve('__DATA', self.roots['__DATA']['va'])
        link = self.roots['__LINKEDIT']
        for name in ('__LINKINFO', '__LINKEDIT'):
            self.reserve(name, self.allocate(self.segment(name)['size']))
        link['size'] = link['filesize'] = self.cursor - link['fileoff']
        # Reserve enough root-linkedit space for new starts/fixups tables. This
        # is derived from site counts, not a bound tied to one release.
        fixup_count = len(cache.fixups()) + len(native.fixups())
        self.table_begin = self.cursor
        self.allocate(align(fixup_count * 2 + len(native.function_starts()) * 10 + 0x10000))
        self.table_end = self.cursor
        link['size'] = link['filesize'] = self.cursor - link['fileoff']
        info = self.roots['__PRELINK_INFO']
        info['va'] = self.allocate(info['size'])
        info['fileoff'] = info['va'] - cache.base
        for name in ('__KLDDATA', '__BOOTDATA'):
            segment = self.segment(name)
            address = self.allocate(segment['size'])
            self.reserve(name, address)
            self.roots[name] = dict(segment, va=address, fileoff=address-cache.base,
                                    filesize=segment['size'])
        # Zero-sized markers have distinct semantics even when their old
        # addresses alias a real segment. Relocate them by section ordinal.
        for segment in native.segments:
            if segment['name'] in self.placements:
                continue
            if segment['size']:
                raise ValueError(f'Unclassified native segment {segment["name"]}')
            address = self.end('__DATA') if segment['name'] == '__PRELINK_DATA' else self.end('__KLD')
            self.reserve(segment['name'], address)"""

NEW_DATA_CODE = """        link = self.roots['__LINKEDIT']
        for name in ('__LINKINFO', '__LINKEDIT'):
            self.reserve(name, self.allocate(self.segment(name)['size']))
        link['size'] = link['filesize'] = self.cursor - link['fileoff']
        # Reserve enough root-linkedit space for new starts/fixups tables. This
        # is derived from site counts, not a bound tied to one release.
        fixup_count = len(cache.fixups()) + len(native.fixups())
        self.table_begin = self.cursor
        self.allocate(align(fixup_count * 2 + len(native.function_starts()) * 10 + 0x10000))
        self.table_end = self.cursor
        link['size'] = link['filesize'] = self.cursor - link['fileoff']
        info = self.roots['__PRELINK_INFO']
        info['va'] = self.allocate(info['size'])
        info['fileoff'] = info['va'] - cache.base

        # Check if native __DATA fits in roots['__DATA'] before the first retained kext
        data_seg = self.segment('__DATA')
        data_occupied = [b for b, e in self.occupied if self.roots['__DATA']['va'] <= b < self.roots['__DATA']['va'] + self.roots['__DATA']['size']]
        data_room = (min(data_occupied) - self.roots['__DATA']['va']) if data_occupied else self.roots['__DATA']['size']

        alloc_segs = ['__KLDDATA', '__BOOTDATA']
        if data_seg['size'] <= data_room:
            self.reserve('__DATA', self.roots['__DATA']['va'])
        else:
            alloc_segs.append('__DATA')

        for name in alloc_segs:
            segment = self.segment(name)
            address = self.allocate(segment['size'])
            self.reserve(name, address)
            root_key = '__NDATA' if name == '__DATA' else name
            self.roots[root_key] = dict(segment, va=address, fileoff=address-cache.base,
                                        filesize=segment['size'])

        # Zero-sized markers have distinct semantics even when their old
        # addresses alias a real segment. Relocate them by section ordinal.
        for segment in native.segments:
            if segment['name'] in self.placements:
                continue
            if segment['size']:
                raise ValueError(f'Unclassified native segment {segment["name"]}')
            if segment['name'] == '__PRELINK_DATA':
                address = min(data_occupied) if (data_occupied and data_seg['size'] > data_room) else self.end('__DATA')
            else:
                address = self.end('__KLD')
            self.reserve(segment['name'], address)"""

OLD_SEGMENT_DEF = """    def segment(self, name):
        return next(s for s in self.native.segments if s['name'] == name)"""

NEW_SEGMENT_DEF = """    def segment(self, name):
        native_name = '__DATA' if name == '__NDATA' else name
        return next(s for s in self.native.segments if s['name'] == native_name)"""

OLD_CONST_CHECK = """        if self.end('__LASTDATA_CONST') > min(b for b, e in self.occupied
                                            if self.roots['__DATA_CONST']['va'] <= b < self.roots['__DATA_CONST']['va'] + self.roots['__DATA_CONST']['size']):
            raise ValueError('Native constants follow retained kext constants')"""

NEW_CONST_CHECK = """        data_const_occupied = [b for b, e in self.occupied
                               if self.roots['__DATA_CONST']['va'] <= b < self.roots['__DATA_CONST']['va'] + self.roots['__DATA_CONST']['size']]
        if data_const_occupied and self.end('__LASTDATA_CONST') > min(data_const_occupied):
            raise ValueError('Native constants follow retained kext constants')"""

OLD_OVERLAP_BLOCK = """            if any(begin < e and b < end for b, e in self.occupied + placed):
                raise ValueError(f'Native {segment["name"]} overlaps a retained segment')"""

NEW_OVERLAP_BLOCK = """            overlap = [(b, e) for b, e in self.occupied + placed if begin < e and b < end]
            if overlap:
                import sys
                sys.stderr.write(f'\\n[layout-DIAGNOSTIC] === OVERLAP DETECTED FOR {segment["name"]} ===\\n')
                sys.stderr.write(f'[layout] Segment {segment["name"]}: begin={begin:#x}, end={end:#x}, size={segment["size"]:#x}\\n')
                sys.stderr.write(f'[layout] Placements so far: {[(s["name"], hex(self.placements.get(s["name"], 0)), hex(self.span(s["name"]))) for s in self.native.segments if s["name"] in self.placements]}\\n')
                sys.stderr.write(f'[layout] Overlapping ranges: {[(hex(b), hex(e)) for b, e in overlap]}\\n')
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
    changed = False

    if OLD_DATA_CODE in src:
        src = src.replace(OLD_DATA_CODE, NEW_DATA_CODE)
        changed = True
        print(f'debug-patch-layout: dynamic __DATA placement patched in {target}')
    elif '__NDATA' in src:
        print(f'debug-patch-layout: dynamic __DATA already patched in {target}')

    if OLD_SEGMENT_DEF in src:
        src = src.replace(OLD_SEGMENT_DEF, NEW_SEGMENT_DEF)
        changed = True
        print(f'debug-patch-layout: segment() patched in {target}')

    if OLD_CONST_CHECK in src:
        src = src.replace(OLD_CONST_CHECK, NEW_CONST_CHECK)
        changed = True
        print(f'debug-patch-layout: __LASTDATA_CONST check patched in {target}')

    if OLD_OVERLAP_BLOCK in src:
        src = src.replace(OLD_OVERLAP_BLOCK, NEW_OVERLAP_BLOCK)
        changed = True
        print(f'debug-patch-layout: overlap diagnostics patched in {target}')

    if changed:
        target.write_text(src)
        print(f'debug-patch-layout: saved changes to {target}')
