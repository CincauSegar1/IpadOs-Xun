#!/usr/bin/env python3
"""Stop the XNU bootstrap pass at object compilation instead of at the link.

Why this exists
---------------
`unixnu build kernel` runs a bootstrap pass first (`XNU_BOOTSTRAP=1`) and deliberately tolerates
its failure, because that pass only has to leave compile records (`*.o.json`, `*.cpo.json`) and the
Kernel.framework headers behind. It raises only if `startup.o.json` or `kern/clock.h` is missing.

That assumption holds for a bare XNU. It does not hold for this board:

    scripts/build-xnu-4k-baseline.sh
    if [ "${XNU_SOURCE_CORECRYPTO14:-0}" = 1 ] && [ "$BOOTSTRAP" = 0 ]; then
        ...every KERNEL_EXTRA_ARCHIVES entry...

The kernel built here turns on CONFIG_XNU_SOURCE_CORECRYPTO14, XNU_NATIVE_RAM_BLOCK and
XNU_SHENG_PMGR, and those make the kernel *require* archives (corecrypto, RamBlock, PMGR) that are
only linked when BOOTSTRAP=0. So the bootstrap link cannot succeed by construction, and it dies
earlier than the design assumes - before iokit/Kernel/IOPlatformExpert.cpp has been compiled.

Without IOPlatformExpert.cpo.json, scripts/build-xun-emmc.py stops with "Missing ...cpo.json", no
libXunEmmc.a is produced, and the real pass then fails at the link with seven undefined symbols
(native_verified_block_*, native_ram_block_*) whose providers live in that archive. One cause, seven
symptoms, none of them pointing at the bootstrap pass.

What this changes
-----------------
Two edits, both against the UniXNU checkout:

1. `makedefs/MakeInc.kernel` - at component level the target that compiles every object and writes
   the file list is `do_all`:

       iokit/conf/Makefile.template
       $(COMPONENT).filelist: $(OBJS)
       do_all: $(COMPONENT).filelist
       do_build_all:: do_all

   and `MakeInc.kernel` adds a second prerequisite to `do_build_all` that is the actual link. With
   BOOTSTRAP=1 that prerequisite is dropped, so the pass compiles everything and links nothing.
   Every .o.json and .cpo.json lands; the link - which could not have worked - is skipped rather
   than failed.

2. `scripts/build-xnu-4k-baseline.sh` - the condition has to be visible to make. The driver exports
   XNU_BOOTSTRAP, the script copies it into BOOTSTRAP with `BOOTSTRAP=${XNU_BOOTSTRAP:-0}` and does
   not export it, and its make command line does not pass it either, so without this edit the new
   conditional would never be true. The patch adds `BOOTSTRAP="$BOOTSTRAP"` to the make command
   line, the same way the script already hands over LD_KERNEL_ARCHIVES.

Applied to the UniXNU checkout at build time, not carried here, because UniXNU is checked out fresh
by CI and a file in this repository would not reach it.

When this can go away
---------------------
When the framework makes `build_all` independent of `do_build_kernel` under XNU_BOOTSTRAP, or when
the archive blocks stop depending on BOOTSTRAP. Until then this is a patch on someone else's tree,
and it says so.
"""
from pathlib import Path
import sys

MAKE_MARKER = '# --- IpadOS-Xun: keep the bootstrap pass off the link ---'

# BOOTSTRAP, not XNU_BOOTSTRAP: see the note above about how the script passes it on. filter()
# treats an unset or empty value as a normal build, so only a literal 1 skips the link.
MAKE_OLD = """do_build_all:: do_build_kernel

.PHONY: do_build_kernel
"""

MAKE_NEW = """# --- IpadOS-Xun: keep the bootstrap pass off the link ---
# Under BOOTSTRAP=1 the pass only has to produce compile records and file lists, and its link cannot
# succeed: KERNEL_EXTRA_ARCHIVES is gated on BOOTSTRAP=0 while this board's defconfig makes the
# corecrypto/RamBlock/PMGR archives mandatory. Dropping the prerequisite compiles every object
# (including the .cpo.json the archive builders read) and skips the link instead of failing it.
ifneq ($(filter 1,$(BOOTSTRAP)),)
do_build_all:: do_build_kernel_skipped
.PHONY: do_build_kernel_skipped
do_build_kernel_skipped:
\t@echo "kernel: bootstrap pass - objects compiled, link skipped (archives are not linked here)"
else
do_build_all:: do_build_kernel
endif

.PHONY: do_build_kernel
"""

SCRIPT_MARKER = '# --- IpadOS-Xun: hand BOOTSTRAP to make ---'
SCRIPT_OLD = '  CFLAGS_EXTRA="$EXTRA_CFLAGS" "${EXTRA_MAKE_ARGS[@]}"'
SCRIPT_NEW = '  CFLAGS_EXTRA="$EXTRA_CFLAGS" "${EXTRA_MAKE_ARGS[@]}" BOOTSTRAP="$BOOTSTRAP"'


def main(argv):
    tree = Path(argv[1]) if len(argv) > 1 else Path('.')
    changed = 0

    makefile = tree / 'makedefs/MakeInc.kernel'
    script = tree / 'scripts/build-xnu-4k-baseline.sh'
    for path in (makefile, script):
        if not path.is_file():
            print(f'apply-bootstrap-link-skip: no {path}; is this the UniXNU tree?', file=sys.stderr)
            return 2

    make_text = makefile.read_text()
    if MAKE_MARKER in make_text:
        print(f'apply-bootstrap-link-skip: {makefile} already carries the change')
    else:
        if MAKE_OLD not in make_text:
            print(f'apply-bootstrap-link-skip: expected do_build_all anchor missing from {makefile}. '
                  f'UniXNU changed that rule; re-read this script before trusting the build.',
                  file=sys.stderr)
            return 1
        makefile.write_text(make_text.replace(MAKE_OLD, MAKE_NEW, 1))
        print(f'apply-bootstrap-link-skip: patched {makefile}')
        changed += 1

    script_text = script.read_text()
    if SCRIPT_MARKER in script_text:
        print(f'apply-bootstrap-link-skip: {script} already carries the change')
    else:
        if SCRIPT_OLD not in script_text:
            print(f'apply-bootstrap-link-skip: expected make invocation missing from {script}. '
                  f'UniXNU changed how it calls make; re-read this script before trusting the build.',
                  file=sys.stderr)
            return 1
        patched = script_text.replace(SCRIPT_OLD, SCRIPT_NEW, 1)
        # The note goes above the BOOTSTRAP assignment, not above the make line: that line runs
        # across several backslash continuations, so a "#" placed after its arguments would comment
        # out the rest of the command, and nothing may be prepended to the file either because line
        # 1 is the shebang.
        anchor = 'BOOTSTRAP=${XNU_BOOTSTRAP:-0}'
        assert anchor in patched, 'BOOTSTRAP assignment missing from build-xnu-4k-baseline.sh'
        patched = patched.replace(anchor, f'{SCRIPT_MARKER}\n{anchor}', 1)
        script.write_text(patched)
        print(f'apply-bootstrap-link-skip: patched {script}')
        changed += 1

    if not changed:
        print('apply-bootstrap-link-skip: nothing to do')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
