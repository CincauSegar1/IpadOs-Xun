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
Two edits, both inside the XNU source tree:

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

Where the tree is, and why this runs itself twice
--------------------------------------------------
There is no XNU source at the UniXNU root: the drivers build against a checkout at
`{tree}/.cache/xnu-work`, and that clone is made either by `unixnu/patches.py` or by
`build-xnu-4k-baseline.sh` line 34, whichever runs first. So on a cold checkout the tree does not
exist when a CI step would naturally call this script, and the first version of it did exactly that
and stopped with "no makedefs/MakeInc.kernel".

The fix is that the second edit (the one to `build-xnu-4k-baseline.sh`, which always exists) also
inserts a call to this script immediately after the `.cache/xnu-work` clone. The run from CI patches
the build script and stops; the build script then reaches the clone, finds the tree, and this script
runs again from inside it, from the UniXNU root, and patches the tree. Every step is idempotent, so
a warm checkout - where the clone already exists and patches.prepare has run - simply finishes the
makefile edit on the first pass.

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
BOOTSTRAP_ASSIGNMENT = 'BOOTSTRAP=${XNU_BOOTSTRAP:-0}'

# The clone of .cache/xnu-work: once it exists, makedefs/MakeInc.kernel can be patched. Line 34 is
# the same in this script and in unixnu/patches.py, which may create the tree first.
CLONE_OLD = 'if [ ! -d .cache/xnu-work/.git ]; then'
HOOK_MARKER = '# --- IpadOS-Xun: patch the XNU tree as soon as it exists ---'
HOOK_NEW = (
    HOOK_MARKER + '\n'
    '# Patches makedefs/MakeInc.kernel so the bootstrap pass compiles every object and skips the link\n'
    '# it cannot make, and hands BOOTSTRAP to make. Idempotent; a no-op once both edits are in place.\n'
    'if [ -n "${IPADOS_XUN_BOOTSTRAP_FIX:-}" ]; then\n'
    '  python3 "$IPADOS_XUN_BOOTSTRAP_FIX" "$ROOT" || exit 1\n'
    'fi\n'
    ''
)


def find_xnu_tree(start):
    """Return the XNU source tree that carries makedefs/MakeInc.kernel.

    The tree is `{unixnu}/.cache/xnu-work`, a clone the framework makes just before it compiles.
    Nothing is created here: if it does not exist yet the caller is simply running too early, and
    saying so is better than patching a directory that is about to be replaced by a fresh clone.
    """
    start = start.resolve()
    for candidate in (start, start / '.cache/xnu-work'):
        if (candidate / 'makedefs/MakeInc.kernel').is_file():
            return candidate
    # out/xun/tree and out/feeds/xnu-* are the other places a prepared tree can sit, depending on
    # which stage last touched it.
    for pattern in ('out/*/tree', 'out/feeds/xnu-*'):
        for candidate in sorted(start.glob(pattern)):
            if (candidate / 'makedefs/MakeInc.kernel').is_file():
                return candidate
    return None


def patch_makefile(tree):
    path = tree / 'makedefs/MakeInc.kernel'
    text = path.read_text()
    if MAKE_MARKER in text:
        print(f'apply-bootstrap-link-skip: {path} already carries the change')
        return 0
    if MAKE_OLD not in text:
        print(f'apply-bootstrap-link-skip: expected do_build_all anchor missing from {path}. '
              f'UniXNU changed that rule; re-read this script before trusting the build.',
              file=sys.stderr)
        raise SystemExit(1)
    path.write_text(text.replace(MAKE_OLD, MAKE_NEW, 1))
    print(f'apply-bootstrap-link-skip: patched {path}')
    return 1


def patch_build_script(tree):
    path = tree / 'scripts/build-xnu-4k-baseline.sh'
    if not path.is_file():
        print(f'apply-bootstrap-link-skip: no {path}', file=sys.stderr)
        raise SystemExit(1)
    text = path.read_text()
    if SCRIPT_MARKER in text:
        print(f'apply-bootstrap-link-skip: {path} already carries the change')
        return 0
    if SCRIPT_OLD not in text:
        print(f'apply-bootstrap-link-skip: expected make invocation missing from {path}. UniXNU '
              f'changed how it calls make; re-read this script before trusting the build.',
              file=sys.stderr)
        raise SystemExit(1)
    if BOOTSTRAP_ASSIGNMENT not in text:
        print(f'apply-bootstrap-link-skip: no {BOOTSTRAP_ASSIGNMENT!r} in {path}; the conditional '
              f'would never be true.', file=sys.stderr)
        raise SystemExit(1)
    text = text.replace(SCRIPT_OLD, SCRIPT_NEW, 1)
    # The note goes above the assignment, not above the make line: that line runs across several
    # backslash continuations, so a "#" after its arguments would comment out the rest of it, and
    # nothing may be prepended to the file because line 1 is the shebang.
    text = text.replace(BOOTSTRAP_ASSIGNMENT,
                        f'{SCRIPT_MARKER}\n{BOOTSTRAP_ASSIGNMENT}', 1)
    if HOOK_MARKER not in text:
        if CLONE_OLD not in text:
            print(f'apply-bootstrap-link-skip: no {CLONE_OLD!r} in {path}; cannot hook the clone.',
                  file=sys.stderr)
            raise SystemExit(1)
        text = text.replace(CLONE_OLD, HOOK_NEW + CLONE_OLD, 1)
    path.write_text(text)
    print(f'apply-bootstrap-link-skip: patched {path}')
    return 1


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else Path('.')

    # The build script is at the UniXNU root and always exists; the XNU tree may not yet.
    uni = root.resolve()
    if not (uni / 'scripts/build-xnu-4k-baseline.sh').is_file():
        candidate = uni / 'UniXNU'
        if (candidate / 'scripts/build-xnu-4k-baseline.sh').is_file():
            uni = candidate
        else:
            print(f'apply-bootstrap-link-skip: no scripts/build-xnu-4k-baseline.sh under '
                  f'{root.resolve()}; is this the UniXNU tree?', file=sys.stderr)
            return 2

    changed = patch_build_script(uni)

    tree = find_xnu_tree(uni)
    if tree is None:
        # Expected on a cold checkout: the clone does not exist yet, and the build script now calls
        # this script again right after making it.
        print('apply-bootstrap-link-skip: XNU tree not created yet; the build script will call '
              'this script again once it is (see the hook above the .cache/xnu-work clone)')
    else:
        changed += patch_makefile(tree)

    if not changed:
        print('apply-bootstrap-link-skip: nothing to do')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
