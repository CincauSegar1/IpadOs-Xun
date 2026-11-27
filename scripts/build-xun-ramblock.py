#!/usr/bin/env python3
"""Build NativeRamBlock (RamBlock : IOBlockStorageDevice) for UniXNU-xun CI/local builds.

Compiles drivers/RamBlock/NativeRamBlock.cpp against the prepared IOStorageFamily headers and
archives build/ram-block/libRamBlock.a.

This used to verify NativeRamBlock's 190-slot vtable against the stock kernelcache and emit the
IOBlockStorageDevice bindings that libShengUfs.a did not already define. Neither is possible on the
24B156 image - it is a stripped MH_FILESET with an empty symbol table and no surviving vtable - and
neither is needed, because the driver names only the five base methods and the linker fills the
rest from the family the kernel carries. See compile_storage_driver() in xun_storage_abi.
"""
import subprocess

from xun_storage_abi import ROOT, compile_storage_driver


def main():
    out = ROOT / 'build/ram-block'
    out.mkdir(parents=True, exist_ok=True)

    source = ROOT / 'drivers/RamBlock/NativeRamBlock.cpp'
    obj = out / 'NativeRamBlock.o'
    compile_storage_driver(source, obj)

    archive = out / 'libRamBlock.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(obj)], check=True)

    print(f'build-xun-ramblock: {archive}')


if __name__ == '__main__':
    main()
