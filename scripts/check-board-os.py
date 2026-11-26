#!/usr/bin/env python3
"""Which inputs of this board are still missing, before the build is started.

`scripts/check-xun.py` checks the firmware tree. This one checks the board's OS side: the
values in `board.toml` that cannot be known before the restore image has been expanded and
the first kernel has been built. It reports them and exits non-zero - it does not guess.

Run it whenever the target OS line changes, and once after the first successful build:

    python3 scripts/check-board-os.py
    python3 scripts/check-board-os.py --json build/xun/board-os.json

Every check below is a value that, if wrong, fails on the tablet instead of here. An empty
string is not a value; it is a marker that says "not read yet".
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_OS = {
    'os_profile': 'ipados-27.2.1-24B156',
    'product': 'iPad12,1',
    'version': '27.2.1',
    'build': '24B156',
    'device_class': 'j181ap',
    'chip_id': 0x8030,
    'board_id': 0x18,
}


def toml_value(text, section, key):
    body = re.search(r'^\[%s\]\s*$(.*?)(?=^\[|\Z)' % re.escape(section), text, re.M | re.S)
    if not body:
        return None
    m = re.search(r'^%s\s*=\s*(.+?)\s*$' % re.escape(key), body.group(1), re.M)
    if not m:
        return None
    value = m.group(1).strip()
    # A multi-line array: keep collecting until the brackets balance. Single-line keys never
    # enter this branch, so nothing else changes.
    if value.startswith('[') and value.count('[') > value.count(']'):
        rest = body.group(1)[m.end():]
        depth = value.count('[') - value.count(']')
        for line in rest.splitlines():
            value += ' ' + line.strip()
            depth += line.count('[') - line.count(']')
            if depth <= 0:
                break
    return value


def unquote(value):
    if value is None:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    args = ap.parse_args()

    board = (ROOT / 'board.toml').read_text()
    blocking, pending, ok = [], [], []

    profile = unquote(toml_value(board, 'board', 'os_profile'))
    if profile != EXPECTED_OS['os_profile']:
        blocking.append(f"board.toml [board] os_profile is {profile!r}, expected "
                        f"{EXPECTED_OS['os_profile']!r}: the rest of this file describes that image")
    else:
        ok.append(f'os_profile {profile}')

    for key in ('product', 'version', 'build', 'device_class'):
        got = unquote(toml_value(board, 'ipsw', key))
        if got != EXPECTED_OS[key]:
            blocking.append(f'board.toml [ipsw] {key} is {got!r}, expected {EXPECTED_OS[key]!r}')
        else:
            ok.append(f'ipsw.{key} {got}')

    for key in ('chip_id', 'board_id'):
        raw = unquote(toml_value(board, 'ipsw', key))
        try:
            got = int(raw, 0)
        except (TypeError, ValueError):
            blocking.append(f'board.toml [ipsw] {key} is not an integer: {raw!r}')
            continue
        if got != EXPECTED_OS[key]:
            blocking.append(f'board.toml [ipsw] {key} is {got:#x}, expected {EXPECTED_OS[key]:#x}')
        else:
            ok.append(f'ipsw.{key} {got:#x}')

    members = toml_value(board, 'ipsw.member', 'KernelCache')
    if unquote(members) != 'kernelcache.release.ipad12p':
        blocking.append('[ipsw.member] KernelCache must name the member of THIS image; '
                        f'got {members!r}')
    else:
        ok.append('member names')

    # These four are the root policy: volume UUIDs and image digests of the two AEA archives.
    for section, keys, why in (
        ('root', ('os_volume_uuid', 'systemos_volume_uuid', 'os_image_sha256', 'systemos_image_sha256'),
         'read off the expanded OS / Cryptex1,SystemOS volumes (tools/ipados27/build-simg.sh)'),
        ('payload', ('trust_cache_sha256',), 'digest of the static+System trust bundle this images boots with'),
        ('kernel.prelink', ('kernelcache_sha256',),
         'digest of the kernelcache.release.ipad12p this prelink was cut against'),
    ):
        for key in keys:
            raw = toml_value(board, section, key)
            empty = raw is None or unquote(raw) in ('', '[]') or raw == '[]'
            if empty:
                pending.append(f'[{section}] {key} is empty: {why}')
            else:
                ok.append(f'[{section}] {key}')

    prelink_esi = toml_value(board, 'kernel.prelink', 'early_security_init')
    if prelink_esi is None or unquote(prelink_esi) == '':
        pending.append('[kernel.prelink] early_security_init is empty: the KEXT address inside '
                       'the kernelcache this build emits (not the stock 24B156 one), which only '
                       'a built kernel can supply')
    adt_uuid = toml_value(board, 'payload.adt', 'root_match_volume_uuid')
    if adt_uuid is None or unquote(adt_uuid) == '':
        pending.append('[payload.adt] root_match_volume_uuid is empty: same value as [root] '
                       'os_volume_uuid')

    # /chosen/boot-manifest-hash: mount(8) derives /private/preboot/<UPPERCASE HEX> from it and a
    # failed read is fatal to the first mount, so it must be present and the root image must carry
    # that directory. The image side cannot be checked here (there is no image in the checkout), so
    # what is checked is that the value is well-formed and that build-simg.sh defaults to the same
    # string - the two ways it goes wrong are a malformed hash and a drift between the ADT and the
    # image builder.
    bmh = toml_value(board, 'payload.adt', 'boot_manifest_hash')
    bmh = unquote(bmh) if bmh else ''
    if not bmh:
        blocking.append('[payload.adt] boot_manifest_hash is empty: /chosen/boot-manifest-hash is '
                        'the one input the iPadOS 27 first mount treats as fatal')
    elif len(bmh) != 96 or any(c not in '0123456789abcdefABCDEF' for c in bmh):
        blocking.append(f'[payload.adt] boot_manifest_hash is not 96 hex characters: {bmh!r}')
    else:
        simg = ROOT / 'tools/ipados27/build-simg.sh'
        default = ''
        if simg.is_file():
            for line in simg.read_text().splitlines():
                if line.startswith('PREBOOT_HASH='):
                    default = line.split('=', 1)[1].strip().strip('"').strip()
                    # Written as ${PREBOOT_HASH:-<default>} so a caller can override it.
                    if default.startswith('${') and ':-' in default:
                        default = default[2:].split(':-', 1)[1].rstrip('}')
                    break
        if default.lower() != bmh.lower():
            blocking.append('tools/ipados27/build-simg.sh PREBOOT_HASH defaults to '
                            f'{default or "(nothing)"} but board.toml boot_manifest_hash is {bmh}; '
                            'the image and the ADT would disagree and mount -P 1 exits 66')
        else:
            ok.append('[payload.adt] boot_manifest_hash matches the image builder')

    series = ROOT / 'patches/xnu-27/series'
    listed = [l.strip() for l in series.read_text().splitlines()
              if l.strip() and not l.startswith('#')]
    present = sorted(p.name for p in (ROOT / 'patches/xnu-27').glob('*.patch'))
    missing = [n for n in listed if not (ROOT / 'patches/xnu-27' / n).is_file()]
    unlisted = [n for n in present if n not in listed]
    if missing:
        blocking.append(f'patches/xnu-27/series lists files that are not there: {missing}')
    if unlisted:
        blocking.append(f'patches/xnu-27/ has patches the series does not list: {unlisted}')
    if not missing and not unlisted:
        ok.append(f'device patch series: {len(listed)} patches, listing and directory agree')

    # A series line whose layer has no source is a build that fails late, in patch application,
    # with a message about a missing file. The soc: layer is the one that had this problem.
    layers = []
    ps = toml_value(board, 'kernel', 'patch_series')
    if ps:
        layers = [l.strip().strip('"').strip("'") for l in
                  ps.strip('[]').split(',') if l.strip()]
    soc_line = [l for l in layers if l.startswith('soc:')]
    if soc_line:
        feeds = (ROOT / 'feeds.toml').read_text()
        # Walk the [[source]] blocks and find the one whose kind is "soc".
        soc_src, in_soc, cur = None, False, {}
        for raw in feeds.splitlines():
            line = raw.strip()
            if line == '[[source]]':
                if in_soc:
                    soc_src = cur
                in_soc, cur = False, {}
                continue
            if '=' not in line or line.startswith('#'):
                continue
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip().strip('"')
            if k == 'kind':
                in_soc = v == 'soc'
            if in_soc:
                cur[k] = v
        if in_soc:
            soc_src = cur
        soc_src = soc_src or {}
        has_soc_source = bool(soc_src)
        has_commit = bool(soc_src.get('commit', ''))
        if not has_soc_source:
            blocking.append(f'board.toml patch_series names {soc_line} but feeds.toml has no '
                            'kind = "soc" source to resolve it into')
        elif not has_commit:
            blocking.append(f'board.toml patch_series names {soc_line} but the soc source in '
                            'feeds.toml has an empty commit, so the layer cannot be fetched')
        else:
            ok.append('soc layer referenced and pinned in feeds.toml')
    else:
        ok.append('no soc: layer named; the SoC changes are device patches')

    for line in ok:
        print(f'  ok      {line}')
    for line in pending:
        print(f'  pending {line}')
    for line in blocking:
        print(f'  ERROR   {line}')

    if blocking:
        print(f'\n{len(blocking)} error(s), {len(pending)} value(s) still to be read')
    elif pending:
        print(f'\nno errors; {len(pending)} value(s) still to be read from the expanded image')
    else:
        print('\nall board inputs present')

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({'ok': ok, 'pending': pending, 'blocking': blocking}, indent=2) + '\n')

    # Pending values are not a build failure: they are reported, and the build that needs them
    # refuses on its own. An inconsistency here is a failure now.
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
