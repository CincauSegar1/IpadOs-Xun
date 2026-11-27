#!/usr/bin/env python3
"""Build XunEmmc (NativeUfs + NativeEmmcBlock : IOBlockStorageDevice) for UniXNU-xun.

Compiles drivers/XunEmmc/NativeEmmc.cpp against the prepared IOStorageFamily headers and archives
both:
  - build/xun-emmc/libXunEmmc.a
  - build/sheng-ufs/libShengUfs.a  (for upstream XNU_NATIVE_UFS=1 linkage)

This used to verify NativeEmmcBlock's 190-slot vtable against the stock kernelcache first. That
step cannot run on the 24B156 image - it is a stripped MH_FILESET with an empty symbol table and no
surviving vtable - and is not needed, because the driver names only the five base methods and the
linker fills the rest from the family the kernel carries. The layout is checked at run time
instead; see compile_storage_driver() in xun_storage_abi for the full reasoning.
"""
import shutil
import subprocess

from xun_storage_abi import ROOT, compile_storage_driver


def main():
    out = ROOT / 'build/xun-emmc'
    out.mkdir(parents=True, exist_ok=True)

    source = ROOT / 'drivers/XunEmmc/NativeEmmc.cpp'
    obj = out / 'NativeEmmc.o'
    compile_storage_driver(source, obj)

    archive = out / 'libXunEmmc.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(obj)], check=True)

    ufs_archive = ROOT / 'build/sheng-ufs/libShengUfs.a'
    ufs_archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, ufs_archive)

    print(f'build-xun-emmc: {archive} + {ufs_archive}')


if __name__ == '__main__':
    main()
