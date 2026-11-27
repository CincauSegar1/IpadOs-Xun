#!/usr/bin/env python3
"""Read the pinned stock kernelcache digest from board.toml.

The storage-ABI audit and the PMGR builder both have to prove they are looking at the *same*
kernelcache the rest of the build targets, because they read class layouts out of it: a vtable slot
taken from the wrong build is worse than no slot at all. Both used to carry the digest as a literal,
and the literal survived the port to 24B156 while board.toml moved on - so the two disagreed and the
EMMC archive builder rejected the correct file with "Original decompressed iPadOS kernelcache not
found", which read like a missing download rather than a stale pin.

board.toml already records the values the framework itself checks, under [kernel.prelink]:

    kernelcache_sha256 = "..."            # the decompressed arm64 Mach-O
    kernelcache_container_sha256 = "..."  # the IM4P container it came out of

This module is the only place that knows how to get at them, so the next time the OS target moves
there is one pin to update and nothing to keep in step by hand.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _board_toml():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        import tomli as tomllib
    return tomllib.loads((ROOT / 'board.toml').read_text())


def _prelink():
    return _board_toml().get('kernel', {}).get('prelink', {})


def kernelcache_sha256():
    """Digest of the decompressed arm64 Mach-O, which is what the audit reads."""
    value = str(_prelink().get('kernelcache_sha256', '')).strip().lower()
    if len(value) != 64:
        raise SystemExit(
            'kernelcache_sha256 is not pinned in board.toml [kernel.prelink]; the storage ABI '
            'audit cannot tell the target kernelcache from any other one without it')
    return value


def kernelcache_container_sha256():
    """Digest of the IM4P container, for scripts that download rather than decode."""
    value = str(_prelink().get('kernelcache_container_sha256', '')).strip().lower()
    return value if len(value) == 64 else None
