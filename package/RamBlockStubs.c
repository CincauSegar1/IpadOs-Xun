// SPDX-License-Identifier: BSD-2-Clause-Patent
// Weak fallbacks for the RamBlock provider hooks that offline-owner-systemos-mount.patch calls when
// CONFIG_XNU_NATIVE_RAM_BLOCK is on.
//
// drivers/RamBlock is a submodule of UniXNU, not of this repository, and build-xun-ramblock.py (which
// archives it) is not part of this build. The patch still declares and calls these unconditionally
// inside its XNU_NATIVE_RAM_BLOCK block, so with the config on and no provider the kernel links
// against undefined symbols and stops there.
//
// Returning 0 (failure) is the honest answer: there is no RamBlock device behind these, so the
// owner-data and GPU-addon paths fall through to the same "no seed" handling they already have for
// a device that offers none. That is a degraded Data volume, not a wrong one - nothing here invents
// a volume, a digest or a size that the hardware did not report.
//
// Signatures are copied verbatim from the patch. If they drift, the build fails loudly on a type
// mismatch instead of linking a stub that silently never matches the call.
#include <stdint.h>
#include <stddef.h>

// <sys/types.h> is not available to a freestanding kernel stub; dev_t is __darwin_dev_t, int32_t.
typedef int32_t xun_dev_t;

int native_ram_block_volume_seed(const char *uuid, xun_dev_t *device, char *path,
                                 size_t path_size, uint64_t *base, uint64_t *size,
                                 uint8_t digest[32]);
__attribute__((weak)) int native_ram_block_volume_seed(const char *uuid, xun_dev_t *device,
                                                       char *path, size_t path_size,
                                                       uint64_t *base, uint64_t *size,
                                                       uint8_t digest[32])
{
	(void)uuid;
	(void)device;
	(void)path;
	(void)path_size;
	(void)base;
	(void)size;
	(void)digest;
	return 0;
}

int native_ram_block_gpu_addon(const uint8_t **addon, uint64_t *bytes);
__attribute__((weak)) int native_ram_block_gpu_addon(const uint8_t **addon, uint64_t *bytes)
{
	(void)addon;
	(void)bytes;
	return 0;
}
