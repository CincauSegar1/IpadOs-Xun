#!/usr/bin/env python3
"""Archive the stub objects the kernel links against.

Three archives come out of here:

  build/link-stubs/libLinkStubs.a          -- the no-op probe hooks, named by
                                              CONFIG_XNU_EXTRA_LD_ARCHIVES
  build/verified-root-key/libVerifiedRootKey.a -- the verified-root probe
  build/ram-block-stubs/libRamBlockStubs.a -- the RamBlock provider hooks

Why RamBlockStubs.o also goes into libLinkStubs.a
-------------------------------------------------
CONFIG_XNU_EXTRA_LD_ARCHIVES is a single value that preflight treats as one file path:

    unixnu/kernel.py
    if key.endswith('_ARCHIVE') and value.endswith('.a') and not Path(value).is_file():
        raise Error(...)

so it cannot name two archives, and the build script's own force_load blocks are per-archive
hardcoded. Rather than patch someone else's build script for a fourth archive, the RamBlock stubs
are added as a second member of libLinkStubs.a, which is already linked. One path, one archive,
nothing extra to teach the framework.

There is no build/ram-block/libRamBlock.a here
----------------------------------------------
build-xnu-4k-baseline.sh wants one when NATIVE_RAM_BLOCK=1 - but only when XNU_SOURCE_STORAGE is 0:

    if [ "$NATIVE_RAM_BLOCK" = 1 ] && [ "${XNU_SOURCE_STORAGE:-0}" != 1 ]; then
      RAM_BLOCK_ARCHIVE=$ROOT/build/ram-block/libRamBlock.a
      test -f "$RAM_BLOCK_ARCHIVE"

xun_defconfig sets CONFIG_XNU_SOURCE_STORAGE=y, so that block never runs: no existence check, no
force_load, and no -DXNU_NATIVE_RAM_BLOCK=1 on the personality object. The owner-data patch then
takes its #else arm and reads the Data seed from /dev/md0 through mdevlookup()/mdevgetrange(),
which is the path UniXNU-muyu boots with. The hooks below stay because the weak fallbacks cost
nothing and keep the archive honest if the board ever goes back to the alias path.

The separate libRamBlockStubs.a is still emitted, because it is what a build that links the
archives itself (scripts/build-macos-local.sh with XNU_EXTRA_LD_ARCHIVES) picks up, and because a
reader looking for the RamBlock stubs should find an archive with that name.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def compile_object(source_name, out_subdir, obj_name):
    kit_src = ROOT / 'kits/xun' / source_name
    pkg_src = ROOT / 'package' / source_name
    source = kit_src if kit_src.exists() else pkg_src
    out = ROOT / out_subdir
    out.mkdir(parents=True, exist_ok=True)
    obj = out / obj_name
    subprocess.run([
        'xcrun', '--sdk', 'iphoneos', 'clang', '-arch', 'arm64', '-mkernel',
        '-miphoneos-version-min=17.0', '-Os', '-Wall', '-Werror',
        '-c', source, '-o', obj,
    ], check=True)
    return obj


def archive(archive_path, objects):
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', str(archive_path), *map(str, objects)], check=True)
    print(archive_path)
    return archive_path


def main():
    link_stubs = compile_object('LinkStubs.c', 'build/link-stubs', 'LinkStubs.o')
    verified_root = compile_object('VerifiedRootKeyStub.c', 'build/verified-root-key',
                                   'VerifiedRootKey.o')
    ram_block = compile_object('RamBlockStubs.c', 'build/ram-block-stubs', 'RamBlockStubs.o')

    # Both objects in the archive the defconfig already names - see the module docstring for why.
    archive(ROOT / 'build/link-stubs/libLinkStubs.a', [link_stubs, ram_block])
    archive(ROOT / 'build/verified-root-key/libVerifiedRootKey.a', [verified_root])
    archive(ROOT / 'build/ram-block-stubs/libRamBlockStubs.a', [ram_block])


if __name__ == '__main__':
    main()
