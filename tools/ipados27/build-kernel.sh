#!/usr/bin/env bash
# Helper script to trigger or test the iPadOS 27 Heartwood kernel build.
#
# This script can either trigger the GitHub Actions workflow using the GitHub CLI (gh),
# or prepare the local dxb build directory if running on a macOS builder machine.
#
# Usage:
#   tools/ipados27/build-kernel.sh [gh | local]
#
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT"

MODE=${1:-gh}

if [ "$MODE" = "gh" ]; then
    echo "== Checking GitHub CLI (gh)"
    if ! command -v gh >/dev/null 2>&1; then
        echo "gh CLI not found. Install it via 'pkg install gh' (Termux) or trigger '.github/workflows/xnu-ipados27.yml' in your browser." >&2
        exit 1
    fi
    echo "== Triggering .github/workflows/xnu-ipados27.yml on GitHub Actions"
    gh workflow run xnu-ipados27.yml -f kernel_config=DEVELOPMENT -f machine_config=SWEET
    echo "== Workflow dispatched successfully!"
    echo "To monitor progress: gh run list --workflow=xnu-ipados27.yml"
elif [ "$MODE" = "local" ]; then
    echo "== Staging patches for local build (requires macOS with Xcode)"
    mkdir -p dxb/patches/26.0
    for f in xnu/patches-12377/*.patch xnu/patches-12377/*.sh; do
        [ -e "$f" ] || continue
        cp "$f" "dxb/patches/26.0/sweet-$(basename "$f")"
    done
    for f in xnu/patches-ipados27/*.patch xnu/patches-ipados27/*.sh; do
        [ -e "$f" ] || continue
        cp "$f" "dxb/patches/26.0/sweet-27-$(basename "$f")"
    done
    echo "== Patches staged in dxb/patches/26.0/"
else
    echo "Usage: $0 [gh | local]" >&2
    exit 1
fi
