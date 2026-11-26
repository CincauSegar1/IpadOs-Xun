# Porting Notes: iPadOS 27.2.1 (`24B156`) on Xiaomi Redmi Pad SE 11" (`xun` / SM6225)

## Target Device & Platform
- **Device:** Xiaomi Redmi Pad SE 11" (`23073RPBFG`, codename `xun`)
- **Platform:** Qualcomm Snapdragon 680 4G (`SM6225` / `khaje` / `divar`)
- **CPU Topology:** 4× Kryo 265 Gold (Cortex-A73 @ 2.4 GHz, `MPIDR 0x100–0x103`) + 4× Kryo 265 Silver (Cortex-A53 @ 1.9 GHz, `MPIDR 0x0–0x3`)
- **Target OS:** iPadOS 27.2.1 (`24B156`), `iPad12,1` / `J181AP` `arm64e` userland (`iPad_10.2_2021_27.2.1_24B156_Restore.ipsw`)
- **Root image members:** `OS` = `141-09394-225.dmg.aea`, `Cryptex1,SystemOS` = `141-10410-235.dmg.aea` (both `AEA1`)
- **Baseline Framework:** UniXNU Format-2 Device Repository (`schema_version = 2`), seeded from `xVanTuring/UniXNU-tb128fu`

## Target OS identifiers (from `BuildManifest.plist`, identity 0)

| Field | Value |
| --- | --- |
| ProductVersion | 27.2.1 |
| ProductBuildVersion | 24B156 |
| SupportedProductTypes | `iPad12,1`, `iPad12,2` |
| DeviceClass | `j181ap` (and `j182ap`) |
| ApBoardID | `0x18` (`0x1A` for j182ap) |
| ApChipID | `0x8030` — A13 / H12 / t8030 |
| KernelCache | `kernelcache.release.ipad12p` |
| DeviceTree | `Firmware/all_flash/DeviceTree.j181ap.im4p` |
| StaticTrustCache | `Firmware/141-09394-225.dmg.aea.trustcache` |
| Cryptex1,SystemTrustCache | `Firmware/141-10410-235.dmg.aea.trustcache` |


## Current Milestone
- **Milestone:** Stage 3 & 4 Complete — Apple Device Trees Generated, Framebuffer Patched to 1200×1920, IPSW Trust Caches & Platform Seed Staged, eMMC 5.1 Storage Verified, Turnkey CI Workflow & macOS Build Scripts Deployed
- **Last Confirmed Stage:** Stage 4 (eMMC 5.1 512-byte sector unit tests passed; `xun-single.adt` and `xun-smp.adt` validated)
- **Porting Record Status:** 13/13 structured areas checked and validated (`python UniXNU/scripts/porting-record.py check --device UniXNU-xun`)
- **Active Blocker:** None for deterministic code; ready for cloud CI compilation (`.github/workflows/build.yml`) or Hackintosh execution (`scripts/build-macos-local.sh`) to produce `SILICIUM_UEFI.fd` and `kernel.macho`.

## Stage 3 & 4 Implemented Deliverables

### 1. Apple Device Tree Generation & Validation
- **Tool:** `UniXNU-xun/scripts/make-xun-adt.py`
- **Single-Core Boot ADT:** `out/xun/xun-single.adt` (11,992 bytes)
  - `cpu_regs = "0"`, Cortex-A53 Silver cluster-type `E`
  - GICv3 Distributor `0x0F200000`, Redistributors `0x0F300000` (stride `0x20000`)
  - Virtual timer frequency: `19200000` Hz (19.2 MHz, INTID 19)
  - DRAM base: `0x80000000`, DarwinBoot window: `0x80000000` (2 GiB)
  - Continuous splash framebuffer: `0x5C000000` (1200×1920 portrait scanout, stride 4800, 32 bpp ARGB)
  - Retained panic RAM: `0x5D000000` (`ramoops` 2 MiB)
  - eMMC storage: `sdhci@4744000` (`qcom,sdhci-msm-v5`)
- **8-Core SMP ADT:** `out/xun/xun-smp.adt` (14,292 bytes)
  - All 8 cores: 4× Silver `0x0..0x3` (`E`) + 4× Gold `0x100..0x103` (`P`)
  - `/psci`: method `smc`, compatible `arm,psci-1.0`
- **Validation:** `UniXNU-xun/scripts/inspect-adt.py` parses binary format, 4-byte padding alignment, node hierarchy, and asserts all hardware registers.

### 2. Resolution & Framebuffer Constants (1200×2000 -> 1200×1920)
- `UniXNU-xun/package/LegacyDisplayProbe.cpp`: updated comments and display parameters to `1200x1920`.
- `UniXNU-xun/package/TouchProbe.cpp`: updated panel bounds to `1200x1920`.
- `UniXNU-xun/package/HimaxProtocol.h`: updated `#define HX_Y_MAX 1919` (from 1999) and resolution comments.
- `UniXNU-xun/package/BootLog.c`: updated log format string to `1200x1920`.
- `UniXNU-xun/drivers/AdrenoMetal/shaders/scale_bgra.ll`: updated scanout presentation target to `1200x1920`.
- `UniXNU-xun/drivers/GopFramebuffer/NativeLegacyDisplay.cpp`: updated render server scaling to `900x1440` on `1200x1920`.
- `UniXNU-xun/README.md`: updated GOP framebuffer and panel entries to `1200×1920`.

### 3. IPSW Trust Caches & Platform Seed
- **Script:** `scripts/stage-ipsw-trust.py`
- On the retired 17.7.11 line this staged `StaticTrustCache` from
  `iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw` (`Firmware/044-76040-038.dmg.trustcache`).
- On the 27.2.1 line the pair to stage is `Firmware/141-09394-225.dmg.aea.trustcache` and
  `Firmware/141-10410-235.dmg.aea.trustcache` from
  `iPad_10.2_2021_27.2.1_24B156_Restore.ipsw`. Both are DER-wrapped `IM4P` — `trst` for the static
  one (84576-byte payload) and `trcs` for the System one (3168 bytes). Combined the way the payload
  builder expects (12-byte header of version 2, static offset 12 and total length, then the two
  payloads) they make 87756 bytes with digest `8f4b06b0…`, which `board.toml`
  `[payload] trust_cache_sha256` now pins. The container and payload digests are recorded in
  `scripts/data/owner-os-policy-27.2.1.json`.

### 3b. The boot-set directory (`/chosen/boot-manifest-hash`)
- The iPadOS 27 userland's first act is `mount -P 1`, run with env 0 because no user-device-tree
  fstab exists. In that mode a missing Data volume and a missing `/private/preboot` bindfs source
  are warnings; the one input that is fatal is `/chosen/boot-manifest-hash`. A failed read there is
  `mount` exit 66, and launchd fails the `mount-phase-1` boot task, so the boot stops before
  SpringBoard.
- `mount(8)` turns the hash into a path: it bind-mounts
  `/private/preboot/<UPPERCASE HEX>/usr/standalone/firmware` over `/usr/standalone/firmware`. The
  root volume is mounted read-only at runtime, so the directory cannot be created on the tablet —
  it has to be in the image as it is written.
- Three places must agree: `board.toml` `[payload.adt] boot_manifest_hash`, the ADT's
  `/chosen/boot-manifest-hash` (written by `scripts/make-xun-adt.py --boot-manifest-hash`), and the
  root image (`tools/ipados27/build-simg.sh` `--preboot-hash`, which `renegade-rs root-ipsw`
  writes in at build time).
- The value is this port's own bring-up boot-set identity, SHA-384 of `XunBringup.BootSet.v1\0`:
  `033991f9751b0c3e5225fe66c3d7b773c4228fcccbe3805209b74ca187b1b37bf7f870cc96cd106ae9415ef0e7f30b2f`.
  It is not an Apple personalization manifest and nothing derives it; it only has to be the same
  96 hex characters in all three places.
- `board.toml` `[payload.adt] filesystems = false` ships no `/filesystems` node, because that node
  raises `mount`'s env to 1 and makes those two warnings fatal.
- Related: `/chosen/kernel-ctrr-to-be-enabled = 0`. SM6225 has no CTRR, so kernel text is writable
  and 0 is the truthful value; without the property `ml_unsafe_kernel_text()` asserts and
  `dtrace_early_init()` panics on `machine_routines.c:3379`.

### 4. eMMC 5.1 Storage Driver & 512-Byte Sector Unit Tests
- **Driver:** `drivers/XunEmmc`
  - `Info.plist`, `RootLayout.h`, `NativeEmmc.cpp`
  - Qualcomm SDHCI MSM at `0x04744000`
  - 512-byte sector size
  - Userdata start LBA: `20129584` (`0x1332730`), byte offset: `0x2664e6000` (10,306,347,008 bytes)
  - Userdata last LBA: `244244958` (`0xe8f5fde`) — the span is exactly 114,763,587,072 bytes.
    0xe8fffff came from the sheng line and is 20,988,416 bytes larger than the partition xun
    actually has, so an image built for it does not fit and fastboot rejects the write.
- **Unit Test:** `drivers/XunEmmc/tests/check_xun_emmc_root.py`
  - Validates LBA 1 GPT Header, LBA 2..33 Partition Entries array (128 entries)
  - Validates `userdata` partition resolution and 512-byte byte offset translation
  - Validates `SHNGROOT` manifest header (magic, 3 slices: OS, SystemOS, Data) and `SHNGPOL1` policy locator block at offset 4096.

### 5. Turnkey CI & macOS Local Build Pipelines
- **GitHub Actions Workflow:** `UniXNU-xun/.github/workflows/build.yml`
  - `build-uefi` (`ubuntu-latest`): builds `SILICIUM_UEFI.fd` using Clang + EDK2 BaseTools
  - `build-xnu` (`macos-latest`): compiles `kernel.macho` and `.adt` with Xcode `iphoneos` SDK and `MACHINE_CONFIGS=BCM2837`; selects the newest Xcode 26+ on the image and needs Clang 20+
  - `package-bootimg` (`ubuntu-latest`): assembles `boot.img` and fails above 64 MiB
- **macOS Build Script:** `scripts/build-macos-local.sh`
  - Automates toolchain checks, ADT generation, trust cache staging, eMMC unit tests, and kernel compilation on local Hackintosh.
- **Panic & Retained Log Diagnostic Reader:** `UniXNU-xun/scripts/read-xun-log.py`

### 3c. Where the `[kernel.prelink]` values come from
- `kernelcache_sha256` is the digest of the **decompressed arm64 Mach-O** that
  `unixnu.ipsw.kernelcache()` writes to `out/ipsw/24B156/kernelcache.decompressed`: 66,715,648
  bytes, `19a5fc8c7eed62377995fda89b2f620760e99613aa00c27427240c83df555912`. Getting there means
  unwrapping the IM4P, LZFSE-decoding the payload, and taking the arm64 slice out of the fat file.
- The IM4P **container** hash of `kernelcache.release.ipad12p` as it sits in the IPSW is a
  different number — 21,687,452 bytes,
  `e9f46648e9a4840de016e6dd90e3ea3f9980811fb6e51efd97812572456a9633`. It is kept as
  `kernelcache_container_sha256` because it identifies the artefact, but putting it in the pin slot
  makes the build stop with "does not match the pin" for a value that looks right. That happened,
  and `scripts/check-board-os.py` now reports an error if the two are ever equal.
- `early_security_init` is an address **inside our built kernelcache**, so no stock artefact can
  supply it. Copying `0xfffffff005ab4ae0` from the 21H461 line, or the reference board's value,
  produces a kernel that links and boots until AMFI — the least debuggable place a wrong number
  can land. It stays empty until there is a
  `build/xnu/ios-obj/.../mach.development.*.unstripped.noctf` to read it from, by symbol:
  `scripts/inspect-prelink-callsite.py --symbol early_security_init <our-kernel>`.
- Same rule for the `native-stack-shift` binding: the patch defines
  `unixnu_kernel_stack_shift`, but what makes it take effect is a prelink fixture entry for the one
  GOT slot AMFI reads `PAGE_SHIFT_CONST` from, and that fixture is generated from the built
  kernelcache too.

### 3d. The SoC layer, and the two patches that replaced it
- `UniXNU-muyu` gets two patches through `soc:patches/xnu-12377/series` in
  `UniXNU-sm7675-common`: `sheng-platform-power` and `native-smp-secondary`. The SM6225
  equivalent (`github.com/UniXNU/UniXNU-sm6225-common`) returns 404, checked twice.
- Both of those patches turn out to be generic — neither names an SM7675 register — so they are
  carried here as device patches instead of a series line that cannot resolve:
  - `xun-pmgr-bringup` — `build-platform-power.py` archives `sheng_pmgr_run()` (a no-op stub when
    there is no reference kernel) and **nothing called it**. The PMGR nub was linked and
    unreachable, so the power and clock domains the iPadOS 27 userland asks for never appeared.
  - `xun-clustered-mpidr` — the A73 cores report MPIDR `0x100..0x103`. `start.s` masks MPIDR with
    `0xFF` unless `HAS_CLUSTER`, which folds all four onto the A53 numbers, so the secondary start
    never selects a distinct entry for them. The patch uses `0xFFFF` under a new
    `CONFIG_XNU_QCOM_CLUSTERED_MPIDR`.
- `scripts/check-board-os.py` now fails if `patch_series` names a `soc:` layer that `feeds.toml`
  cannot resolve, so the two cannot drift apart again.

## Verified Hardware Parameters
- **SoC:** Qualcomm Snapdragon 680 4G (`SM6225`, `soc_id = 518`, `khaje` / `divar`)
- **CPU:** 4× Silver (Cortex-A53, `0x0–0x3`) + 4× Gold (Cortex-A73, `0x100–0x103`)
- **DRAM:** Base `0x40000000`, DarwinBoot window at `0x80000000..0x100000000` (2 GiB)
- **Continuous Splash:** `0x5C000000` (15 MiB inside 16 MiB Display Reserved), `1200×1920`, 32 bpp
- **PStore / Ramoops:** `0x5D000000` (2 MiB)
- **Storage:** eMMC 5.1 on Qualcomm SDHCI MSM `0x04744000`, 512-byte sector size, userdata start LBA `20129584` (`0x1332730`)
- **Interrupts & Timer:** GICv3 Dist `0x0F200000`, Redist `0x0F300000` (stride `0x20000`), Virtual Timer `INTID 19` @ 19.2 MHz
- **Touch & Buttons:** FocalTech / Novatek (`0x62`), IRQ GPIO 80, Reset GPIO 86; PM6125 SPMI PON resin/kpdpwr
- **GPU:** Adreno 610 (`0x05900000`, SMMU `0x059A0000`, no GMU)

## Safety Guardrails Reminder
- **NEVER** flash or modify critical boot partitions: `xbl`, `xbl_config`, `abl`, `tz`, `hyp`, `devcfg`, `persist`, `modem`, `modemst1`, `modemst2`, `fsg`, `fsc`.
- **ABL Download Buffer Limit:** Keep boot payload image under 57 MiB.
- Keep TWRP / OrangeFox intact on `recovery` partition for log extraction via `pstore` / `ramoops`.
