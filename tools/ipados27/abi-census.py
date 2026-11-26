#!/usr/bin/env python3
"""Census of the syscall/trap numbers an arm64(e) Darwin userland actually calls.

On arm64 Darwin the syscall code travels in x16 and the instruction is `svc #0x80`; the
code is `(class << 24) | number` (class 1 = Mach trap, 2 = BSD syscall, 3 = machine-dependent,
4 = diagnostic). This tool finds every `svc #0x80` in a Mach-O or a dyld shared cache, reads the
x16 value the compiler materialised in front of it (MOVZ/MOVK/MOVN sequences), and reports the
set per class. That is the input to the ABI work for a userland newer than the kernel source:
a number the kernel does not implement is a missing syscall, not a rendering bug.

  tools/ipados27/abi-census.py FILE|DIR... [--json OUT] [--min-count N] [--top N]
  tools/ipados27/abi-census.py research/ipados27/cache/dyld_shared_cache_arm64e*

For the root image built by tools/ipados27/build-simg.sh, take the cache out of it first:

  renegade-rs hfs research/ipados27/ipados27-root-full.simg getdir \
      System/Library/Caches/com.apple.dyld research/ipados27/cache

No file of Apple's is needed at run time and nothing is written except --json.
"""
import json
import os
import struct
import sys
from collections import Counter

SVC = b"\x01\x10\x00\xd4"  # svc #0x80
CLASS = {0: "none", 1: "mach", 2: "unix", 3: "mdep", 4: "diag"}


def x16_value(data, pos):
    """The value the instructions before `pos` put in x16, or None.

    Scans back up to six instructions; MOVZ (base), MOVK (16-bit chunks) and MOVN (base) only,
    which is what clang emits for a syscall number. Anything else writing x16 stops the scan.
    """
    base = None
    chunks = 0
    for j in range(1, 7):
        off = pos - 4 * j
        if off < 0:
            return None
        insn = struct.unpack_from("<I", data, off)[0]
        if (insn & 0x1F) != 16:
            continue
        op = insn & 0x7F800000
        hw = (insn >> 21) & 3
        imm = (insn >> 5) & 0xFFFF
        sf = (insn >> 31) & 1
        if op in (0x52800000, 0xD2800000):  # MOVZ Wd / Xd
            base = (imm << (16 * hw)) & (0xFFFFFFFFFFFFFFFF if sf else 0xFFFFFFFF)
            break
        if op in (0x12800000, 0x92800000):  # MOVN Wd / Xd
            v = (~(imm << (16 * hw))) & (0xFFFFFFFFFFFFFFFF if sf else 0xFFFFFFFF)
            base = v
            break
        if op in (0x72800000, 0xF2800000):  # MOVK Wd / Xd
            chunks |= imm << (16 * hw)
            continue
        # another instruction writes x16 (mov x16, x0; ldr x16, ...): no static number
        return None
    if base is None:
        return None
    if chunks:
        keep = 0xFFFFFFFFFFFFFFFF
        for hw in range(4):
            if (chunks >> (16 * hw)) & 0xFFFF:
                keep &= ~(0xFFFF << (16 * hw))
        base = (base & keep) | chunks
    return base


def census_file(path, counts, sites):
    with open(path, "rb") as f:
        data = f.read()
    n = 0
    i = data.find(SVC)
    while i >= 0:
        n += 1
        if i % 4 == 0:
            v = x16_value(data, i)
            if v is not None:
                sites.append((path, i, v))
                counts[v] += 1
        i = data.find(SVC, i + 4)
    return n


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    out_json = None
    min_count = 1
    top = 40
    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            i += 1
            out_json = args[i]
        elif a == "--min-count":
            i += 1
            min_count = int(args[i])
        elif a == "--top":
            i += 1
            top = int(args[i])
        else:
            files.append(a)
        i += 1
    expanded = []
    for p in files:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                expanded += [os.path.join(root, n) for n in names if not n.startswith(".")]
        else:
            expanded.append(p)

    counts = Counter()
    sites = []
    total = 0
    for p in expanded:
        try:
            total += census_file(p, counts, sites)
        except OSError as e:
            print(f"{p}: {e}", file=sys.stderr)

    if not counts:
        print(f"no resolved svc #0x80 sites in {len(expanded)} file(s) ({total} sites)")
        return 1

    print(f"files: {len(expanded)}   svc #0x80 sites: {total}   resolved with a static x16: {sum(counts.values())}")
    per_class = Counter()
    for code in counts:
        per_class[(code >> 24) & 0xFF] += 1
    print()
    for cls in sorted(per_class):
        nums = sorted(c & 0xFFFFFF for c in counts if (c >> 24) & 0xFF == cls)
        print(f"class {cls} ({CLASS.get(cls, '?')}): {len(nums)} numbers, "
              f"{min(nums)}..{max(nums)}, {sum(counts[c] for c in counts if (c >> 24) & 0xFF == cls)} sites")
        print("  " + " ".join(str(n) for n in nums[:top]) + (" ..." if len(nums) > top else ""))
    print()
    print("most called:")
    for code, c in counts.most_common(15):
        cls, num = (code >> 24) & 0xFF, code & 0xFFFFFF
        print(f"  {c:8d}  {CLASS.get(cls, '?'):5s} {num}  (x16=0x{code:x})")

    if out_json:
        doc = {
            "files": expanded,
            "sites": total,
            "calls": {f"0x{code:x}": {"class": (code >> 24) & 0xFF,
                                      "number": code & 0xFFFFFF,
                                      "count": c} for code, c in sorted(counts.items())},
        }
        with open(out_json, "w") as f:
            json.dump(doc, f, indent=1)
        print(f"\nwrote {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
