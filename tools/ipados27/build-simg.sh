#!/usr/bin/env bash
# Build the iPadOS 27 userland root image (simg) for the iPad 9 (iPad12,1, J181AP).
#
# This is the Renegade "IPSW in, sparse userdata out" path, in Rust (tools/renegade-rs):
# no root, no loop device, no hfsplus module and no apfs-fuse, so it runs in Termux and in
# WSL2 as it does on a Mac. The Python pipeline (tools/renegade) is the reference but needs
# all four of those; see tools/renegade/README.md, "Platforms".
#
#   tools/ipados27/build-simg.sh [/path/to/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw]
#
# Environment:
#   OUT=...          output .simg (default: research/ipados27/ipados27-root-full.simg)
#   SIZE=24g         HFS+ volume size passed to root-ipsw
#   NO_TOOLS=1       skip berga-tools.zip (no SSH / first-boot job / wallpaper in the image)
#   TOOLS=...        an already downloaded berga-tools.zip
#   SSH_KEY=...      public key installed for root SSH (default: research/ipados27/id_ed25519.pub)
#   CARGO_TARGET_DIR=...  where cargo builds (default: tools/renegade-rs/target)
#
# The AEA key is fetched by renegade-rs itself from the archive's com.apple.wkms.fcs-key-url
# (it 301-redirects to fcs-keys-pub-prod.cdn-apple.com); ipsw(1) is not needed.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

IPSW=${1:-${IPSW:-}}
if [ -z "$IPSW" ]; then
	for p in \
		"$ROOT/research/ipados27/ipsw/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw" \
		"$HOME/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw" \
		"$HOME/Downloads/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw"
	do
		[ -f "$p" ] && IPSW=$p && break
	done
fi
[ -n "$IPSW" ] && [ -f "$IPSW" ] || {
	cat >&2 <<EOF
usage: $0 <iPad_10.2_2021_27.2.1_24B156_Restore.ipsw>

That IPSW is the only input this script needs besides cargo and curl. It is the
iPadOS 27.2.1 restore image for the iPad (9th generation), model iPad12,1 / J181AP:

    iPad_10.2_2021_27.2.1_24B156_Restore.ipsw

Download it from Apple (or any IPSW mirror), then either pass its path as the first
argument, set IPSW=/path/to/it, or drop it in one of the default locations:

    research/ipados27/ipsw/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw
    ~/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw
    ~/Downloads/iPad_10.2_2021_27.2.1_24B156_Restore.ipsw

No other build works: the dyld shared cache and the system services inside are keyed to
this device and this build. The archive is AEA-encrypted, which is fine - renegade-rs
fetches the content key from the archive's own com.apple.wkms.fcs-key-url, so it does not
need to be decrypted first.
EOF
	exit 2
}
case "$IPSW" in
	*_27.2.1_24B156_Restore.ipsw) ;;
	*) echo "warning: $IPSW does not look like the iPadOS 27.2.1 (24B156) IPSW" >&2 ;;
esac

OUT=${OUT:-$ROOT/research/ipados27/ipados27-root-full.simg}
SIZE=${SIZE:-24g}
mkdir -p "$(dirname "$OUT")"
WORK=$(dirname "$OUT")

# --- the Rust build -------------------------------------------------------------------------
BIN=${BIN:-$ROOT/tools/renegade-rs/target/release/renegade-rs}
if [ ! -x "$BIN" ]; then
	echo "== building renegade-rs"
	command -v cargo >/dev/null || {
		echo "cargo is missing: 'pkg install rust' (Termux) or https://rustup.rs (WSL/Linux)" >&2
		exit 2
	}
	( cd tools/renegade-rs && cargo build --release )
fi

# --- the on-device tools (optional but needed for SSH on the phone) --------------------------
TOOLS=${TOOLS:-}
if [ -z "$TOOLS" ] && [ "${NO_TOOLS:-0}" != 1 ]; then
	TOOLS=$WORK/berga-tools.zip
	if [ ! -f "$TOOLS" ]; then
		echo "== downloading berga-tools.zip"
		curl -fsSL -o "$TOOLS" \
			https://github.com/ry-diffusion/Bergamota/releases/download/berga-tools-v3/berga-tools.zip
		curl -fsSL -o "$TOOLS.sha256" \
			https://github.com/ry-diffusion/Bergamota/releases/download/berga-tools-v3/berga-tools.zip.sha256
	fi
	if [ -f "$TOOLS.sha256" ]; then
		( cd "$(dirname "$TOOLS")" && sha256sum -c "$(basename "$TOOLS").sha256" )
	fi
fi

# --- an SSH key for the root's dropbear -------------------------------------------------------
SSH_KEY=${SSH_KEY:-$WORK/id_ed25519.pub}
if [ -z "${NO_TOOLS:-0}" ] && [ ! -f "$SSH_KEY" ]; then
	command -v ssh-keygen >/dev/null && ssh-keygen -t ed25519 -N '' -C ipados27 -f "${SSH_KEY%.pub}"
fi

# --- the image -------------------------------------------------------------------------------
ARGS=(root-ipsw "$IPSW" "$OUT" --size "$SIZE" --now "$(date +%s)")
[ -n "$TOOLS" ] && ARGS+=(--tools "$TOOLS")
[ -n "${SSH_KEY:-}" ] && [ -f "$SSH_KEY" ] && ARGS+=(--ssh-key "$SSH_KEY")

echo "== renegade-rs ${ARGS[*]}"
"$BIN" "${ARGS[@]}"

echo
echo "== done"
ls -l "$OUT"
"$BIN" hfs "$OUT" ls / | head -20 || true
echo
echo "flash it as the userdata partition (Bergamota fastboot or tools/bergamota-flash.py),"
echo "then boot Enxerto with the J181 ADT and a Heartwood kernel built for the iPadOS 27 userland:"
echo "  .github/workflows/xnu-ipados27.yml  ->  xnu-kernel-ipados27"
