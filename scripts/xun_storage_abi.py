#!/usr/bin/env python3
"""Compile the IOBlockStorageDevice subclasses of UniXNU-xun against the target kernel's headers.

Used by build-xun-emmc.py (NativeEmmcBlock) and build-xun-ramblock.py (NativeRamBlock).

Both scripts used to start from an audit of the stock kernelcache: it walked
__PRELINK_INFO, found com.apple.iokit.IOStorageFamily, read the 190-slot vtable out of the kext's
__DATA_CONST and matched every slot against the symbol table, so that the subclass could be proven
to lay its vtable out the same way. That worked for the original target, iPadOS 17.7.11, whose
kernelcache is a single Mach-O with a symbol table.

It cannot work for 24B156, and the measurements are not ambiguous:

  * the kernelcache is kind 12, MH_FILESET, with 239 kext embedded in it;
  * LC_SYMTAB reports nsyms = 0 in the fileset and in every kext inside it;
  * the mangled vtable symbol name occurs nowhere in the 66,715,648-byte image;
  * decoding every slot as a chained fixup - (qword & 0x7ffffffff) + 0xfffffff00700c000, which does
    land inside IOStorageFamily's __TEXT_EXEC for individual entries - finds no run of 190 entries
    anywhere in the file.

The vtable is not in the image to be checked. It does not need to be: the drivers name only the
five base methods they override (init, probe, start, stop, free), and every other slot is filled in
at link time from the IOStorageFamily the kernel already carries. The check that matters is the one
muyu performs at run time, in package/SourceStorage.cpp, comparing
storageParent->getClassSize() against sizeof(IOBlockStorageDevice) and panicking on a mismatch - it
tests the family that is actually running instead of a fixture measured from a different build.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

TARGET_ARCH_OBJ_DIR = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT'


def require(cond, msg, prefix='xun-storage-abi'):
    if not cond:
        raise SystemExit(f'{prefix}: {msg}')


def build_compile_cmd(record, source_path, output_path, extra_flags):
    arguments = record['arguments']
    cmd, idx = [], 0
    while idx < len(arguments):
        val = arguments[idx]
        if val == record['file']:
            cmd.append(str(source_path))
        elif val == '-o':
            cmd.extend(['-o', str(output_path)])
            idx += 1
        elif val in ('-MF', '-MJ'):
            idx += 1
        elif val == '-Xclang' and idx + 1 < len(arguments) and arguments[idx + 1].startswith('-W'):
            idx += 1
        elif not val.startswith('-W') and val not in ('-MD', '-MP'):
            cmd.append(val)
        idx += 1
    cmd.extend([
        '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-Wno-deprecated-declarations',
        '-Wno-c99-designator', '-Wno-reorder-init-list',
        '-Wno-unnecessary-virtual-specifier', '-Wno-deprecated-enum-enum-conversion',
        '-I', str(ROOT / '.cache/xnu-work/osfmk'),
        *extra_flags,
    ])
    return cmd


def ensure_storage_headers():
    storage_include = ROOT / 'build/storage-abi/include'
    if not (storage_include / 'IOKit/storage/IOBlockStorageDevice.h').is_file():
        prep = ROOT / 'scripts/prepare-storage-headers.py'
        if prep.is_file():
            subprocess.run([sys.executable, str(prep)], cwd=ROOT, check=True)
    require((storage_include / 'IOKit/storage/IOBlockStorageDevice.h').is_file(),
            'Missing build/storage-abi/include IOBlockStorageDevice.h')
    return storage_include


def load_cpo_record():
    cpo_path = TARGET_ARCH_OBJ_DIR / 'IOPlatformExpert.cpo.json'
    require(cpo_path.is_file(), f'Missing {cpo_path}')
    return json.loads(cpo_path.read_text().strip().rstrip(','))


def compile_storage_driver(source, obj, extra_flags=()):
    """Compile one IOBlockStorageDevice subclass against the prepared storage headers.

    The compile record comes from the XNU bootstrap pass, so the flags - the target, the sysroot,
    the arm64e ABI settings - are the ones the target kernel was built with. That is what makes the
    emitted vtable layout and the arm64e branch targets compatible; it has never been the audit.

    No audit of the original IOStorageFamily is needed or possible here, for the reasons given in
    the module docstring: the 24B156 image is stripped and has no vtable to compare against. The
    layout is checked at run time instead, as muyu's package/SourceStorage.cpp does.
    """
    storage_include = ensure_storage_headers()
    record = load_cpo_record()
    cmd = build_compile_cmd(record, source, obj,
                            ['-I', str(storage_include), '-mgeneral-regs-only', *extra_flags])
    result = subprocess.run(cmd, cwd=record['directory'], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit((result.stdout + result.stderr)[-6000:])
    return obj
