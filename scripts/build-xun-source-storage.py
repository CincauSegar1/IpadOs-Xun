#!/usr/bin/env python3
"""Build the source-storage archive: IOBlockStorageDevice compiled from source, plus our driver.

Why this exists
---------------
NativeEmmcBlock (drivers/XunEmmc/NativeEmmc.cpp) subclasses IOBlockStorageDevice, which lives in
IOStorageFamily - a kext that is not linked into the kernel. The iPadOS 17 line resolved the six
base-class symbols it needs by aliasing them onto addresses read out of the kernelcache
(scripts/xun_storage_abi.py: find the 190-slot vtable, match its slots against the symbol table,
emit `.set <mangled>, <address>`).

That does not work on 24B156. The kernelcache is a stripped MH_FILESET: LC_SYMTAB reports nsyms = 0
in the fileset and in each of its 239 embedded kexts, so there is no name any slot can be matched
against, and the mangled vtable symbol occurs nowhere in the 66,715,648 bytes. Scanning for a run of
190 slots that all decode to function entries found four candidates and no way to tell them apart,
because the very thing that distinguishes them - the names - is what was stripped.

So this follows the source-storage design instead (UniXNU-muyu scripts/build-sheng-source-storage.py,
itself from uke): compile the pinned public IOBlockStorageDevice.cpp ourselves. The six symbols are
then defined by our own archive and nothing has to be read out of the kernelcache.

What the macro replacement is for
---------------------------------
Compiling the public source as-is would define `__ZTV20IOBlockStorageDevice`, `gMetaClass` and the
rest a second time, colliding with the copies the original IOStorageFamily registers at run time. The
replacement registers under a different name and hands OSMetaClass a *superclass* that is only known
at run time:

    OSDefineMetaClassWithInit(IOBlockStorageDevice, IOService, )
    IOBlockStorageDevice::MetaClass::MetaClass()
        : OSMetaClass("XunBlockStorageDevice", native_source_storage_parent(),
                      sizeof(IOBlockStorageDevice)) {}

package/SourceStorage.cpp supplies native_source_storage_parent(): it loads the original family,
looks IOBlockStorageDevice up by name with OSMetaClass::getMetaClassWithName(), and panics if the
running base class is not the same size as the one compiled here. The source class therefore hangs
below the original instead of colliding with it, and a layout disagreement is a panic at the point
where it would otherwise turn every field access in NativeEmmcBlock into a silent misread.

The initialisers
----------------
__mod_init_func cannot be kept in these objects: the kernel's own start-up does not run a static
initialiser for a class whose superclass does not exist yet. The section is removed and
__GLOBAL__sub_I_<source> is globalised instead, so package/SourceStorage.cpp can call the
initialisers itself, after the original family is loaded and inside preModLoad/postModLoad. That is
the same treatment muyu gives its storage objects.

NativeRamBlock is the exception: drivers/RamBlock is a UniXNU submodule this board does not select,
so the object is added only when that checkout happens to be present, and SourceStorage.cpp tests the
initialiser for NULL rather than calling it blind.

Where the public source comes from
----------------------------------
refer/IOStorageFamily, which feeds.toml pins. It is fetched by the framework, not vendored here.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

# The public IOStorageFamily revision feeds.toml pins for this board. prepare-storage-headers.py
# refuses any other checkout, so a moved feed is a deliberate change and not a silent drift.
STORAGE_SOURCE_REVISION = 'e45fbe30a7879e0b16e26dddb78538f1b00e0bff'

# Packaged with the framework, in the assembled tree at scripts/.
OBJECT_DIR = 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'


def helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f'xun-source-storage: cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def device_source(*relative, package_dirs):
    """First existing candidate under package/, the device tree, then the build tree."""
    for directory in package_dirs:
        candidate = Path(directory).joinpath(*relative)
        if candidate.is_file():
            return candidate
    raise SystemExit('xun-source-storage: ' + '/'.join(relative) + ' not found in ' +
                     ', '.join(str(d) for d in package_dirs))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tree', type=Path, default=ROOT, help='assembled build tree')
    parser.add_argument('--device', type=Path, help='device repository (default: the tree)')
    parser.add_argument('--storage-source', type=Path,
                        help='public IOStorageFamily checkout (default: <tree>/refer/IOStorageFamily)')
    parser.add_argument('--check-inputs', action='store_true',
                        help='validate inputs without compiling')
    args = parser.parse_args()

    tree = args.tree.resolve()
    # Framework sets UNIXNU_DEVICE env var (kernel.py build_archives); --device overrides it.
    _env_device = os.environ.get('UNIXNU_DEVICE')
    device = (args.device or (_env_device and Path(_env_device)) or tree).resolve()
    storage = (args.storage_source or tree / 'refer/IOStorageFamily').resolve()

    # The device package is linked into the assembled tree as kits/sheng, and sits beside drivers/
    # in an explicit device checkout. Both layouts have to resolve.
    package_dirs = [device / 'package']
    package_dirs += [device / 'kits/sheng', tree / 'kits/sheng']
    package_dirs += [device, tree]

    cpp_record = tree / OBJECT_DIR / 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    c_record = tree / OBJECT_DIR / 'osfmk/DEVELOPMENT/startup.o.json'
    if args.check_inputs:
        missing = [str(p) for p in (cpp_record, c_record) if not p.is_file()]
        if missing:
            raise SystemExit('xun-source-storage: missing compile records: ' + ', '.join(missing))
        storage_cpp = storage / 'IOBlockStorageDevice.cpp'
        if not storage_cpp.is_file():
            raise SystemExit(f'xun-source-storage: {storage_cpp} missing; fetch refer/IOStorageFamily')
        for relative in ('SourceStorage.cpp',):
            device_source(relative, package_dirs=package_dirs)
        print('Source storage inputs - PASS')
        return

    build = helper('source_compile', ROOT / 'scripts/build-sheng-source-drivers.py')
    headers_helper = helper('source_headers', ROOT / 'scripts/prepare-storage-headers.py')
    target = helper('source_target', ROOT / 'scripts/kernel_target.py')

    out = tree / 'build/xun-source-storage'
    out.mkdir(parents=True, exist_ok=True)

    # The public headers NativeEmmc.cpp and the base class are compiled against. Same call muyu
    # makes; it also proves the checkout is at the pinned revision and unmodified.
    header_report = headers_helper.prepare(storage, STORAGE_SOURCE_REVISION, out / 'headers')

    # ---------------------------------------------------------------------------------------------
    # 1. The base class, with its registration macro replaced.
    # ---------------------------------------------------------------------------------------------
    original = (storage / 'IOBlockStorageDevice.cpp').read_text()
    macro = 'OSDefineMetaClassAndAbstractStructors(IOBlockStorageDevice,IOService)'
    if original.count(macro) != 1:
        raise SystemExit('xun-source-storage: the pinned IOBlockStorageDevice registration macro changed; '
                         're-read the replacement below before moving the pin')
    base = out / 'IOBlockStorageDevice.cpp'
    base.write_text(original.replace(macro, '''
extern "C" const OSMetaClass *native_source_storage_parent(void);
OSDefineMetaClassWithInit(IOBlockStorageDevice, IOService, )
IOBlockStorageDevice::MetaClass::MetaClass()
    : OSMetaClass("XunBlockStorageDevice", native_source_storage_parent(), sizeof(IOBlockStorageDevice)) {}
OSDefineAbstractStructors(IOBlockStorageDevice, IOService)
OSDefineOperatorMethods(IOBlockStorageDevice)
'''))

    # ---------------------------------------------------------------------------------------------
    # 2. Everything that goes into the archive.
    # ---------------------------------------------------------------------------------------------
    sources = [
        base,
        Path(device_source('drivers/XunEmmc/NativeEmmc.cpp', package_dirs=package_dirs)),
        Path(device_source('SourceStorage.cpp', package_dirs=package_dirs)),
    ]
    # NativeRamBlock carries the Data seed disk. drivers/RamBlock is a UniXNU submodule this board
    # does not select, so it is optional: when it is absent the seed disk is simply not started, and
    # package/SourceStorage.cpp reaches that code only through allocClassWithName().
    try:
        sources.append(Path(device_source('drivers/RamBlock/NativeRamBlock.cpp', package_dirs=package_dirs)))
    except SystemExit:
        pass

    includes = ['-I', str(out / 'headers/include'), '-I', str(tree / '.cache/xnu-work/osfmk')]
    flags = ['-DNATIVE_EMMC_SOURCE_API=1']
    _ios_ver = os.environ.get('UNIXNU_IOS_VERSION', '0').split('.')[0]
    if _ios_ver.isdigit() and int(_ios_ver) >= 26:
        # The source path does not run BootProgress's process worker; the UFS/RAM providers reuse
        # its native capture code from a worker they own.
        flags.append('-DNATIVE_BOOT_PROCESS_CAPTURE=1')

    objects, inputs = [], {}
    objcopy = 'llvm-objcopy'
    for source in sources:
        record = json.loads((c_record if source.suffix == '.c' else cpp_record)
                            .read_text().strip().rstrip(','))
        output = out / (source.stem + '.o')
        command = build.compile_command(record, source, output, includes, flags)
        if source == base:
            # The public source is not ours to keep warning-clean under Xcode 27's diagnostics.
            command.append('-Wno-error')
        result = subprocess.run(command, cwd=record['directory'], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / (source.stem + '.command.json')).write_text(json.dumps(command, indent=2) + '\n')
        (out / (source.stem + '.log')).write_text(result.stdout)
        if result.returncode:
            raise SystemExit(result.stdout[-6000:])
        target.check_object(output.read_bytes(), source.name)
        if source.name in ('IOBlockStorageDevice.cpp', 'NativeEmmc.cpp', 'NativeRamBlock.cpp'):
            late = output.with_suffix('.late.o')
            subprocess.run([objcopy, '--remove-section=__DATA,__mod_init_func',
                            f'--globalize-symbol=__GLOBAL__sub_I_{source.name}', output, late],
                           check=True)
            output = late
        objects.append(output)
        inputs[str(source)] = sha(source)

    archive = out / 'libXunSourceStorage.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', archive, *map(str, objects)], check=True)

    # The framework links build/sheng-ufs/libShengUfs.a for CONFIG_XNU_NATIVE_UFS. Keeping the copy
    # means the defconfig and the board do not have to learn a second archive name.
    catalog = tree / 'build/sheng-ufs/libShengUfs.a'
    catalog.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, catalog)

    report = dict(archive=str(archive), archive_sha256=sha(archive), sources=inputs,
                  headers=header_report, target=target.TRIPLE, runtime_qualified=False)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(archive)


if __name__ == '__main__':
    main()
