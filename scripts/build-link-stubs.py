#!/usr/bin/env python3
"""Archive the stub objects the kernel links against.

Four archives come out of here:

  build/link-stubs/libLinkStubs.a          -- the no-op probe hooks, named by
                                              CONFIG_XNU_EXTRA_LD_ARCHIVES
  build/verified-root-key/libVerifiedRootKey.a -- the verified-root probe
  build/ram-block-stubs/libRamBlockStubs.a -- the RamBlock provider hooks
  build/ram-block/libRamBlock.a            -- the same hooks, at the path the XNU build script
                                              insists on

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

Why libRamBlock.a exists
------------------------
Independently of that, build-xnu-4k-baseline.sh hardcodes this, for NATIVE_RAM_BLOCK=1:

    RAM_BLOCK_ARCHIVE=$ROOT/build/ram-block/libRamBlock.a
    test -f "$RAM_BLOCK_ARCHIVE"
    ... -Wl,-force_load,$RAM_BLOCK_ARCHIVE

The file has to exist even though the symbols in it are already satisfied by libLinkStubs.a, and
drivers/RamBlock - a UniXNU submodule this repository does not carry - is what would normally put
it there. Leaving it absent stopped the kernel step at

    build-xnu-4k-baseline.sh: line 803: test -f "$RAM_BLOCK_ARCHIVE" failed

so the same stub object is also archived under that name. force_load then pulls in definitions that
libLinkStubs.a already provides; the linker resolves each symbol once and does not mind the second
copy, so nothing about the linked kernel changes. This is a stand-in for the provider, not a
pretence that one exists - retire it when drivers/RamBlock becomes part of this build.

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
    # And again under the name build-xnu-4k-baseline.sh hardcodes for NATIVE_RAM_BLOCK=1, which it
    # only ever tests for existence. See the module docstring.
    archive(ROOT / 'build/ram-block/libRamBlock.a', [ram_block])


if __name__ == '__main__':
    main()
