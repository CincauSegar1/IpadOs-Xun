// SPDX-License-Identifier: BSD-2-Clause-Patent
// Register the source-built storage classes after the original IOStorageFamily loads (xun, iPadOS 27).
//
// Why this file exists
// --------------------
// NativeEmmcBlock subclasses IOBlockStorageDevice, which lives in IOStorageFamily - a kext that is not
// linked into the kernel. On the iPadOS 17 line that was handled by aliasing the six base-class symbols
// onto addresses read out of the kernelcache (script xun_storage_abi.py: read the vtable, match its
// slots against the symbol table, emit `.set <mangled>, <address>`).
//
// That cannot work on 24B156. The kernelcache is a stripped MH_FILESET: LC_SYMTAB reports nsyms = 0 in
// the fileset and in each of its 239 embedded kexts, so there are no names to match against, and the
// mangled vtable symbol occurs nowhere in the 66,715,648 bytes. Without names the 190-slot audit has
// nothing to verify a candidate vtable with, and picking one by shape alone found four candidates that
// it could not tell apart.
//
// So this follows the source-storage design instead (UniXNU-muyu package/SourceStorage.cpp, itself from
// UniXNU-uke): IOBlockStorageDevice is *compiled from the public IOStorageFamily sources*, so the six
// symbols are simply defined by our own archive rather than bound to the kernelcache. What remains is a
// naming problem, and it is solved where the real data is - at run time, through OSMetaClass.
//
// How the two IOBlockStorageDevice metaclasses coexist
// ---------------------------------------------------
// scripts/build-xun-source-storage.py replaces the registration macro in the pinned
// IOBlockStorageDevice.cpp with one that registers under the name "XunBlockStorageDevice" and passes
// native_source_storage_parent() as its superclass. That function does not answer until run time, when
// this file has loaded the original IOStorageFamily and looked its metaclass up by name and cached it.
// The source class therefore hangs *below* the original one instead of colliding with it.
//
// The layout check below is what makes that safe: if the public source we compiled disagrees with the
// running family about how large the base class is, every offset NativeEmmcBlock uses is wrong, and
// that is a panic rather than a silent misread of the eMMC window.
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/OSKextLib.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
#include <IOKit/IOLib.h>

extern kmod_info_t g_kernel_kmod_info;

// The build strips __mod_init_func from the storage objects and globalises these instead; see
// scripts/build-xun-source-storage.py for why the static initialisers cannot run on their own.
extern "C" void source_storage_base_init(void) __asm__("__GLOBAL__sub_I_IOBlockStorageDevice.cpp");
extern "C" void source_storage_emmc_init(void) __asm__("__GLOBAL__sub_I_NativeEmmc.cpp");
/*
 * Optional: drivers/RamBlock is a UniXNU submodule this board does not select, so the Data seed disk
 * may simply not be part of the build. Weak lets the call below disappear when it is absent instead
 * of leaving an undefined symbol the kernel link would refuse; [] tests for exactly that.
 */
extern "C" void source_storage_ram_init(void) __asm__("__GLOBAL__sub_I_NativeRamBlock.cpp")
    __attribute__((weak));

/*
 * No weak stand-ins: the archive that carries this launcher always carries the initialisers too
 * (IOBlockStorageDevice.cpp from the pinned public sources, drivers/XunEmmc/NativeEmmc.cpp for the
 * provider). A weak definition wins over the real one whenever the linker picks this member first,
 * which it does for the launcher symbol - the kernel would then boot with no provider and no
 * diagnostics saying why.
 */
static const OSMetaClass *storageParent;
static bool attempted;

/* Used only by the deferred source IOBlockStorageDevice metaclass constructor. */
extern "C" const OSMetaClass *
native_source_storage_parent(void)
{
	if (!storageParent) {
		panic("SourceStorage: metaclass initialized before the original storage family");
	}
	return storageParent;
}

/*
 * The Data seed the loader placed in /chosen/memory-map is a plain IOBlockStorageDevice, and
 * IOResources published long before the classes above registered, so nothing matches its personality
 * on its own: allocate and start it here, once the RAM block class is registered.
 */
static void
start_data_disk(IOService *provider)
{
	IORegistryEntry *map = IORegistryEntry::fromPath("/chosen/memory-map", gIODTPlane);
	const bool seed = map && (map->getProperty("PackedRAMDisk") || map->getProperty("RAMDisk"));
	OSSafeReleaseNULL(map);
	if (!seed) {
		return;
	}
	IOService *disk = OSDynamicCast(IOService, OSMetaClass::allocClassWithName("NativeRamBlock"));
	if (!disk) {
		panic("SourceStorage: cannot allocate the Data disk");
	}
	const char *step = !disk->init() ? "init" : !disk->attach(provider) ? "attach" :
	    !disk->start(provider) ? "start" : nullptr;
	if (step) {
		panic("SourceStorage: Data disk %s failed", step);
	}
	printf("SourceStorage: Data disk started\n");
}

/*
 * Called from bsd_init() by patches/xnu-27/xun-source-storage-start.patch, just before vfsinit().
 * Strong reference on purpose: the archive is always linked for this board, and an arm64e weak import
 * becomes a chained bind that the payload patch path rejects.
 */
extern "C" void
native_source_storage_start(void)
{
	unsigned enabled = 0;
	/* The boot argument names the 27 line explicitly so a 17-line boot cannot reach this code. */
	if (!PE_parse_boot_argn("xun-source-storage", &enabled, sizeof(enabled)) || enabled != 1 || attempted) {
		return;
	}
	attempted = true;

	printf("SourceStorage: step 1 load IOStorageFamily\n");
	OSReturn status = OSKextLoadKextWithIdentifier("com.apple.iokit.IOStorageFamily");
	if (status != kOSReturnSuccess) {
		panic("SourceStorage: IOStorageFamily load failed %x", status);
	}
	const OSSymbol *name = OSSymbol::withCString("IOBlockStorageDevice");
	storageParent = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
	if (name) {
		name->release();
	}
	/* The public source definition and the running family must agree on the base layout. */
	if (!storageParent || storageParent->getClassSize() != sizeof(IOBlockStorageDevice)) {
		panic("SourceStorage: original base layout %u differs from source %lu",
		    storageParent ? storageParent->getClassSize() : 0, sizeof(IOBlockStorageDevice));
	}

	printf("SourceStorage: step 2 class registration\n");
	void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
	if (!handle) {
		panic("SourceStorage: cannot begin class registration");
	}
	source_storage_base_init();
	source_storage_emmc_init();
	if (&source_storage_ram_init != nullptr) {
		source_storage_ram_init();
	} else {
		printf("SourceStorage: NativeRamBlock not in this build, no Data seed disk\n");
	}
	status = OSMetaClass::postModLoad(handle);
	if (status != kOSReturnSuccess) {
		panic("SourceStorage: class registration failed %x", status);
	}

	printf("SourceStorage: step 3 wait platform root\n");
	OSDictionary *matching = IOService::serviceMatching("IOPlatformExpertDevice");
	IOService *provider = matching ? IOService::waitForMatchingService(matching, 5000000000ULL) : nullptr;
	OSSafeReleaseNULL(matching);
	if (!provider) {
		panic("SourceStorage: platform root unavailable");
	}

	printf("SourceStorage: step 4 data disk\n");
	start_data_disk(provider);

	printf("SourceStorage: storage classes registered\n");
}
