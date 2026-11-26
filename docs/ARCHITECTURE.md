# How this repository is put together

One page, in the order a reader needs it: what the board declares, what the build does with
the declaration, and which parts are real today.

## The board file

`board.toml` is the only description of the device. Everything else — the ADT, the component
set, the kernel patch order, the userdata geometry — is derived from it or referenced by it.
If a value disagrees with `board.toml`, `board.toml` is right and the other file is a bug.

The parts that decide behaviour:

| Key | Why it matters |
| --- | --- |
| `schema_version = 2` | A format 2 board lists components and series explicitly. No directory globbing, so nothing silently picks up a file that was left behind. |
| `[components] include` | The build assembles only these, addressed by name. A component listed but not produced fails at assembly, which is the honest failure. |
| `[userdata] lba_bytes = 4096` | The UFS LUN on this board has a 4096-byte logical block. Using 512 here lands the root window 7/8 of the way into the partition and, worse, succeeds while doing it. |
| `[kernel] patch_series` | Four layers, each resolved into its own checkout. The order is the list order, not alphabetical. |
| `[kernel] defconfig` | Evaluated once before each build. A kernel-only config boots but the board resets after `load_init_program`; see below. |

## Why the defconfig is the userland one

Under a kernel-only configuration launchd has no writable `/private/var`. Swap reports
`EROFS 30`, nothing holds the watchdog, and the board resets some seconds after
`load_init_program`. On the glass that looks exactly like a kernel that never started — the
panel keeps the bootloader's last frame and then the tablet reboots — so it is worth saying
plainly: **the configuration is part of the display problem.**

`xun-userland_defconfig` adds the owner cache and Data mounts, the RAM block provider and the
launchd watchdog policy.

## The four kernel layers

```
arch    UniXNU/profiles/arch/arm64e/patches/xnu/series           64 patches
soc     UniXNU-sm6225-common/patches/xnu-12377/series            2 patches
os      profiles/os/ipados-27.2.1-24B156/patches/xnu/series       4 patches
device  patches/xnu-27/series                                     4 patches
                                                               ----------
                                                                 74 total
```

The counts belong to the pinned sources. They are a comment, not a constant: re-check them
with `unixnu status --json` whenever a layer is re-pinned.

The device layer, patch by patch, is described in `patches/xnu-27/series` itself, next to the
files it lists. That file is the place to read it — a copy here would drift.

## Diagnostics: the panel is the only output

There is no UART in the XNU closure for this board. Every diagnostic is a photograph of the
panel, which makes three things worth doing and one thing worth not doing.

Worth doing:

1. **`-v` and `debug=0x14e` in the boot arguments.** Without them the kernel draws nothing and
   says nothing, and a frozen bootloader frame is indistinguishable from a dead kernel.
2. **`-bravearktextconsole`.** Switches the video console to text so `kprintf` — panic dumps
   included — lands on the panel from `vcattach()` onwards instead of going to a serial port
   that does not exist.
3. **The console-clear patch.** DarwinBoot leaves handoff text on the panel in a larger font;
   without clearing once, every kernel line lands on top of it.

The thing worth not doing: writing a log to a partition from the bootloader and calling that a
diagnostic. It was tried, at length, on this board. Every failed boot then had two possible
causes — the boot, and the flush — and telling them apart cost more than the log was worth.
The panel does not have that problem: if it is on the screen, the code got there.

## What is real, and what is not

| Area | State |
| --- | --- |
| OS profile (`ipados-27.2.1-24B156`) | **Read from the image.** The volume UUIDs came out of the APFS superblocks and `os_image_sha256` from the expanded image; the OS volume is `RaveB24B156.J181J182OS`. What is still unread is `systemos_image_sha256` and the two `[kernel.prelink]` values, which need a built kernelcache. `scripts/check-board-os.py` names them. |
| `/chosen/boot-manifest-hash` and the root image | **Kept in step.** The hash is `board.toml [payload.adt] boot_manifest_hash`, forwarded to the ADT and baked into the image as `/private/preboot/<HASH>/usr/standalone/firmware` by `tools/ipados27/build-simg.sh`. Change one and you must rebuild the other; see the README. |
| SM6225 SoC layer | **Not published**, so there is no `soc:` line. The two changes such a layer would carry (`sheng_pmgr_run()` being called, and the `0xFFFF` MPIDR mask) are device patches here instead; neither is SM7675-specific. |
| Board drivers (`drivers/`, `package/`) | **Present.** `drivers/XunEmmc` is NativeEmmc (Qualcomm SDHCI MSM for eMMC 5.1); `package/` carries display, touch, boot log, boot progress and identity. What no driver does yet is attach to the GPU. |
| GPU | Deferred. `[gpu]` describes the Adreno 610 block so the ADT can name it truthfully; no driver attaches. |

Saying this in a table is not pessimism. The alternative — a README that describes a finished
port — has been written before, in other repositories, and the first person to try the build
spends an afternoon discovering otherwise.
