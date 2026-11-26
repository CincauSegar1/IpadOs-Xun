# IpadOS-Xun

Device repository for running [UniXNU](https://github.com/UniXNU/UniXNU) on the **Xiaomi Redmi
Pad SE 11"** (codename `xun`, Qualcomm SM6225 "bengal", Adreno 610) with an **iPadOS 27.2.1**
root on `userdata`.

| | |
| --- | --- |
| Device | Xiaomi Redmi Pad SE 11" (`23073RPBFG`), codename `xun` |
| SoC | Qualcomm Snapdragon 680 4G — SM6225 / bengal / khaje |
| CPUs | 4× Cortex-A53 (`MPIDR 0x0..0x3`) + 4× Cortex-A73 (`MPIDR 0x100..0x103`) |
| RAM | DRAM base `0x40000000`; XNU window `0x80000000..0x100000000` |
| Display | 1200×1920 portrait, stride 4800, 32 bpp, framebuffer `0x5c000000` |
| Storage | eMMC 5.1 through Qualcomm SDHCI MSM (`sdhci@4744000`) |
| Target OS | **iPadOS 27.2.1 (build 24B156)** |
| Restore image | **`iPad_10.2_2021_27.2.1_24B156_Restore.ipsw`** |
| Apple product | iPad12,1 (`J181AP`), A13 / chip `0x8030` |
| Schema | UniXNU format 2 (`schema_version = 2`) |

## The OS target

`xun` runs the **iPad (9th generation)** restore image: `iPad12,1`, `J181AP`, device class
`j181ap`, `ApChipID 0x8030`, `ApBoardID 0x18`. The same image also covers `iPad12,2` / `j182ap`.

Every identifier above was read out of the restore image's own `BuildManifest.plist` — identity 0,
the `Customer Erase Install (IPSW)` variant of `j181ap` — rather than assumed from another
device's board file. The firmware and kernelcache inside are named for that product:

| Component | Member in the IPSW |
| --- | --- |
| `KernelCache` | `kernelcache.release.ipad12p` |
| `DeviceTree` | `Firmware/all_flash/DeviceTree.j181ap.im4p` |
| `LLB` / `iBoot` | `Firmware/all_flash/LLB.ipad12p.RELEASE.im4p` (one PE, static ABL) |
| `SEP` | `Firmware/all_flash/sep-firmware.j181.RELEASE.im4p` |

### The two AEA archives

The userland lives in two **Apple Encrypted Archives** (`AEA1`) inside the restore image:

| Component | Member in the IPSW |
| --- | --- |
| `OS` | **`141-09394-225.dmg.aea`** |
| `Cryptex1,SystemOS` | **`141-10410-235.dmg.aea`** |

Their content key is published by the archive's own `com.apple.wkms.fcs-key-url`, which redirects
to Apple's key CDN. [renegade-rs](https://github.com/ry-diffusion/bergamota) fetches that key and
expands the archives itself — no macOS required for this step, no `hdiutil`, no loop device, no
APFS kernel module — so the root image is buildable on the tablet. `tools/ipados27/build-simg.sh`
drives it.

The matching trust caches travel beside them:

| Component | Member |
| --- | --- |
| `StaticTrustCache` | `Firmware/141-09394-225.dmg.aea.trustcache` (`IM4P` `trst`) |
| `Cryptex1,SystemTrustCache` | `Firmware/141-10410-235.dmg.aea.trustcache` (`IM4P` `trcs`) |

Expanded, the three volumes name themselves after this image:

| Volume | Name | UUID |
| --- | --- | --- |
| `OS` | `RaveB24B156.J181J182OS` | `043A9710-08A4-44CC-BA81-29F41495EE9F` |
| `Cryptex1,SystemOS` | `RaveB24B156.J181J182SystemCryptex` (sealed) | `D2707B48-9FF0-479D-926A-64F77F442844` |
| `Cryptex1,AppOS` | `AppCryptex` (sealed) | `3A8063C9-676F-44A3-B140-FE3C61DD90AE` |

Those UUIDs are what the owner policy pins. `renegade-rs apfs <ipsw> os|sysos` prints them out of
the APFS volume superblock, which is the only place they exist — not the `.aea` container and not
the `BuildManifest`. The container digests and the trust-cache payload digests are recorded in
`scripts/data/owner-os-policy-27.2.1.json`.

## Where the kernel comes from

The kernel is **built from source**, not lifted out of the restore image. The image's
`kernelcache.release.ipad12p` is a signed Apple artefact for A13; it is not what runs here. What
runs here is `xnu-12377.121.6` with three patch layers applied:

| Layer | Source | Patches |
| --- | --- | --- |
| `arch` | `UniXNU/profiles/arch/arm64e/patches/xnu/series` | 64 |
| `os` | `profiles/os/ipados-27.2.1-24B156/patches/xnu/series` | 4 |
| `device` | `patches/xnu-27/series` — this repository | 7 |

A schema_version 2 board never globs a directory: `board.toml` names each series file and the
framework resolves it into its own checkout. `unixnu status --json` prints the resolved order. The
counts above belong to the pinned sources and are a comment, not a constant.

There is no `soc` layer. The reference board on this line reaches two SoC patches through
`UniXNU-sm7675-common`; the SM6225 equivalent has no published repository (the URL returns 404).
Rather than name a layer that cannot resolve, those two changes were read from the reference and
carried here as device patches — `xun-pmgr-bringup` and `xun-clustered-mpidr`. Neither names an
SM7675 register and both apply to `xnu-12377.121.6` unchanged, so a future SM6225 layer can take
them back by adding the series line and dropping the two files.

### The seven device patches

`patches/xnu-27/series` lists them in application order and explains each one next to the file it
names. In short:

| Patch | Why it exists on this board |
| --- | --- |
| `xun-console-clear` | No UART in the XNU closure: the panel is the only output. DarwinBoot hands over with its text on the glass in a larger font, and the kernel console would draw over it. |
| `xun-source-storage-start` | NativeEmmc and NativeRamBlock are built in and their class registration lives in `native_source_storage_start()`; without the call IOKit matches the personality but not the class and no volume is published. |
| `native-stack-shift` | A 4 KiB kernel on 32 KiB-aligned stacks. AMFI's `PAGE_SHIFT_CONST` reader bounds-checks against the stack and fails at fixed call depths without the shift being published. |
| `offline-no-iortc-wait` | There is no IORTC device on SM6225 and the wait never matches; the resource-matching path faults inside `IOKitInitializeTime`. |
| `darwin27-missing-syscalls` | The 24B156 userland calls syscalls **556** and **557**, which xnu-12377 does not declare. Found with `tools/ipados27/abi-census.py`; they fail with `ENOTSUP` instead of killing the caller with `SIGSYS`. |
| `xun-pmgr-bringup` | `build-platform-power.py` links `sheng_pmgr_run()` into the kernel and nothing called it: the PMGR nub was present and unreachable, so the power and clock domains the userland asks for never appeared. The call is placed after `bsd_bufferinit()` under `XNU_SHENG_PMGR`. |
| `xun-clustered-mpidr` | The four Cortex-A73 cores report MPIDR `0x100..0x103`. `start.s` turns MPIDR into a CPU number with a `0xFF` mask unless `HAS_CLUSTER`, which folds those four onto the A53 numbers, so no secondary start ever selects a distinct entry for them. |

That last one is worth spelling out, because it is a real measurement rather than a guess.
`tools/ipados27/abi-census.py` reads every `svc #0x80` in the shipped dyld shared cache — 81
subcaches, 1425 sites, 689 with a statically materialised `x16` — and reports the numbers
the userland actually calls. Against xnu-12377 plus the Darwin 26 patches it names exactly two the
kernel is missing, 556 and 557, and they sit in the same `0x2c`-byte-stride stub run as every
other syscall in that dylib. 555 (`ungraftdmg`) is the last number xnu-12377 declares, so they are
the next two slots and 24B156 added them as a pair.

## What is in here

| Path | Contents |
| --- | --- |
| `board.toml` | Board, OS profile, IPSW members, userdata geometry, kernel layers and archives, payload, ADT |
| `porting.toml` | Per-area porting record: inputs, configuration, findings, limits |
| `feeds.toml` | The SoC layer this board pins, plus the Apple source references |
| `configs/xun_defconfig` | Kernel configuration of the first image |
| `patches/xnu-27/` | This board's own XNU patches; `series` lists them in order |
| `drivers/XunEmmc/` | NativeEmmc: Qualcomm SDHCI MSM for eMMC 5.1 |
| `package/` | Board package: display, touch, boot log, boot progress, identity |
| `scripts/` | ADT generation, userdata, boot image, board checks, log readers |
| `scripts/make-xun-adt.py` | Generates the ADT, including `/chosen/boot-manifest-hash`, `kernel-ctrr-to-be-enabled` and the root-matching UUID |
| `scripts/data/owner-os-policy-27.2.1.json` | The two `.aea` containers, their volume UUIDs and the trust-cache digests |
| `tools/ipados27/` | IPSW → sparse root image (with the `/private/preboot/<hash>` boot-set directory baked in), kernel build helper, ABI census |
| `uefi/` | The `xunPkg` firmware package and the device tree it embeds |
| `dts/xun.dts` | The board device tree |
| `docs/FLASHING_GUIDE.md` | How to flash, and what each partition is for |

`uefi/` carries the `xunPkg` sources and a prebuilt `xun.dtb`; the firmware *build* still happens
in a Mu-Silicium checkout, selected with `UNIXNU_UEFI` (see `board.toml` `[firmware]`).

## Build

### macOS

The kernel build needs Xcode. `scripts/build-macos-local.sh` is the local driver for it:

```sh
# newest Xcode 26 or later on the machine; Clang 20+ is the actual requirement
sudo xcode-select -s /Applications/Xcode.app

git clone https://github.com/UniXNU/UniXNU ../UniXNU
cd ../UniXNU && git submodule update --init --recursive && cd -

export UNIXNU_UEFI=/path/to/uefi-xun        # Mu-Silicium checkout with xunPkg
scripts/build-macos-local.sh
```

`git submodule update --init` is not optional. The display and keystore halves of this port live
in `UniXNU/drivers/GopFramebuffer` and `UniXNU/drivers/AppleKeyStoreState`, which are submodules
of the framework; without them the directories exist and are empty, and
`scripts/build-gop-legacy-display.py` fails looking for `drivers/GopFramebuffer/NativeLegacyDisplay.cpp`.
Nothing in this repository vendors them — `board.toml` `[components] include` names them and the
framework's `components.toml` resolves each to a pinned commit.

**Framework requirement.** `scripts/unixnu/payload.py` in the UniXNU framework builds the ADT
command from a fixed list of `[payload.adt]` keys. This board needs `boot_manifest_hash` on that
list (forwarded as `--boot-manifest-hash`) and `filesystems = false` (forwarded as
`--no-filesystems`); a framework without them builds an ADT with no `/chosen/boot-manifest-hash`,
and the boot then stops at `mount -P 1` without saying why. Check before building:

```sh
grep -n 'boot_manifest_hash' ../UniXNU/scripts/unixnu/payload.py
```

### Linux / Termux

Everything except the kernel itself:

```sh
python3 scripts/check-board-os.py           # reports which board values are still unread
python3 scripts/make-xun-adt.py --dram-size 0x200000000 --owned-memory-size 0x1B8000000 \
  --ipad-identity --root-match-volume-uuid 043A9710-08A4-44CC-BA81-29F41495EE9F \
  --cpu-regs 0,1,2,3,0x100,0x101,0x102,0x103 --output out/xun/xun-smp.adt

tools/ipados27/build-simg.sh /path/to/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw
# PREBOOT_HASH defaults to board.toml [payload.adt] boot_manifest_hash; override only together with it
tools/ipados27/abi-census.py out/cache/dyld_shared_cache_arm64e* --json out/abi.json
```

### CI

`.github/workflows/build.yml` runs three jobs: the UEFI firmware on `ubuntu-latest`, the XNU
kernel and ADT on `macos-latest` (it selects the newest Xcode on the image and needs Clang 20+ for
`-Wno-unnecessary-virtual-specifier`), and the root image on `ubuntu-latest`. `bisect.yml` is the
patch-driver variant for narrowing a boot stall.

These run on push to `main` and on `workflow_dispatch`. A run is not a boot test: it produces
`boot.img`, `payload.img` and the two ADTs, and the tablet still has to be flashed by hand.

Three jobs, in order:

| Job | Runner | What it does |
| --- | --- | --- |
| `build-uefi` | `ubuntu-latest` | Scaffolds `xunPkg` into Mu-Silicium, runs `scripts/check-xun.py`, builds `SILICIUM_UEFI.fd`. |
| `build-xnu` | `macos-latest` | Generates both ADTs, fetches the touch firmware blobs, builds the kernel twice (the second pass links the real `ShengPlatformPower.cpp` against pass 1's `mach.macho`), stages the trust-cache bundle — the pinned digest is asserted, not printed — and builds `payload.img`. |
| `package-bootimg` | `ubuntu-latest` | Assembles `boot.img` from the UEFI FD, `xun.dtb` and the payload, and fails if it exceeds 64 MiB. |

The `build-xnu` job needs `UNIXNU_UNIQUE_CHIP_ID` as a repository secret, because the platform
seed is deliberately not stored in this repository. Without it that job fails at the payload step.

Local builds do not depend on any of this: `scripts/build-macos-local.sh` is the same pipeline
driven from your own machine, and it is what the flashing guide uses.

## Flash

Two partitions are written:

1. `boot_a` (or the active slot) — the unified UEFI + XNU boot image
2. `userdata` — the OS and SystemOS windows

```sh
fastboot flash boot_a out/xun/boot.img
fastboot flash userdata out/xun/userdata.img
fastboot reboot
```

`fastboot boot` does not work on this board. The ABL download buffer is smaller than a full image
and every attempt returns `Failed to load/authenticate boot image: Load Error`, including for the
stock boot image — it is a property of the bootloader, not of the image. Write `boot_a` and reboot.

## State

| Area | State |
| --- | --- |
| OS profile, IPSW members, volume UUIDs, trust-cache digest | Read from the 24B156 image itself |
| `/chosen/boot-manifest-hash` | **Set**, and the root image is built to match it — see below |
| `/chosen/kernel-ctrr-to-be-enabled` | **Set to 0.** SM6225 has no CTRR, so kernel text is writable; without the property `ml_unsafe_kernel_text()` asserts and `dtrace_early_init()` panics. |
| `[root] systemos_image_sha256` | **Measured.** 6,174,015,488 bytes expanded from `141-10410-235.dmg.aea`, digest `19b656d4…`. |
| `[kernel.prelink] kernelcache_sha256` | **Measured.** The stock `kernelcache.release.ipad12p` (21,687,452 bytes), which is what the prelink is cut against. |
| `[kernel.prelink] early_security_init` | **Still empty, deliberately.** It is an address inside *our* built kernelcache; the stock one cannot supply it and a copied value fails in AMFI on hardware. `scripts/inspect-prelink-callsite.py` reads it by symbol once a kernel exists. |
| The `native-stack-shift` prelink binding | **Not yet made.** The patch defines `unixnu_kernel_stack_shift`; what makes it take effect is a prelink fixture entry binding AMFI's one `PAGE_SHIFT_CONST` GOT slot to it, and that fixture is cut from a built kernelcache — so it is an after-the-first-build step, like `kernelcache_sha256`. Defining the symbol alone changes nothing. |
| `scripts/check-board-os.py` | Reports every empty value above as `pending` and fails only on an inconsistency. |
| GPU | Deferred. SM6225 is an Adreno 610 (a6xx, no GMU); the ADT describes the block so it can be named truthfully, and no driver attaches to it. |

### Why `boot-manifest-hash` decides whether it boots at all

The first thing the iPadOS 27 userland does is run `mount -P 1`. It runs with env 0, because no
user-device-tree fstab exists, and in that mode a missing Data volume and a missing
`/private/preboot` bindfs source are only warnings. The one input that is not a warning is
`/chosen/boot-manifest-hash`: a failed read there makes `mount` exit 66 and launchd fails the
`mount-phase-1` boot task, so the boot stops before SpringBoard.

`mount(8)` uses that hash as a path. It binds `/private/preboot/<UPPERCASE HEX>/usr/standalone/firmware`
over `/usr/standalone/firmware`, so the hash, the ADT and the root image are a single decision, and
the root volume is mounted read-only at runtime — the directory cannot be created on the tablet.

This repository keeps them in step in two places:

- `board.toml [payload.adt] boot_manifest_hash` is forwarded by the framework as
  `--boot-manifest-hash`, and `scripts/make-xun-adt.py` writes it into `/chosen`.
- `tools/ipados27/build-simg.sh` passes the same value as `--preboot-hash`, and `renegade-rs`
  writes `/private/preboot/<HASH>/usr/standalone/firmware` into the image as it builds it, filled
  from the `usr/standalone/firmware` the OS already ships.

The value itself is this port's own bring-up boot-set identity — SHA-384 of `XunBringup.BootSet.v1`
plus a NUL. It is not an Apple personalization manifest and nothing derives it; it only has to be
the same 96 hex characters in all three places. Changing it means rebuilding the root image.

`board.toml [payload.adt] filesystems = false` ships no `/filesystems` node, because that node
raises `mount`'s env to 1 and makes those two warnings fatal.

## Credits

This project uses UniXNU.

UniXNU is licensed under the BSD-2-Clause-Patent license.
Copyright (c) 2026 UniXNU contributors.

Original project:
https://github.com/UniXNU/UniXNU

The board layout, the OS line, the kernel patch layering and the device-layer patches
follow [UniXNU-muyu](https://github.com/yehua123-oos/UniXNU-muyu), which runs the same iPadOS 27 line on
an SM8635 tablet; this repository keeps its shape and replaces the SoC, the storage controller and
the panel.

The IPSW-in / sparse-userdata-out path — decrypting the `.aea` archives, expanding the APFS
volumes, writing the sparse `userdata` image — and the ABI census tool are
[renegade-rs](https://github.com/ry-diffusion/bergamota).

Earlier bring-up work on SM6225 storage, on the `xunPkg` firmware and on reading the boot log off
the tablet is from [UniXNU-xun](https://github.com/losthappines/UniXNU-xun) and
[UniXNU-muyu#1](https://github.com/yehua123-oos/UniXNU-muyu#1).

## License

BSD-2-Clause-Patent, as UniXNU. See [`LICENSE`](LICENSE).

```
Copyright (c) 2026, UniXNU contributors. All rights reserved.
SPDX-License-Identifier: BSD-2-Clause-Patent
```
