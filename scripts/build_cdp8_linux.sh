#!/usr/bin/env bash
# Build CDP8 from source on Linux — the Phase 3 empirical-curation substrate.
#
# Produces ~211 real CDP binaries so the curation loop (banner extraction,
# duration measurement, breakpoint probes, determinism checks) runs on any
# Linux box (sandbox, CI) without a macOS machine in the loop. Findings
# derived from these binaries are ALWAYS re-verified against the user's
# macOS r8 install via the CDP-gated pytest suite — this build is the
# exploration substrate, not the source of truth.
#
# Known-skipped targets (make -k): a handful of optional externals
# (reverb/rmresp and friends) hardcode clang's -stdlib=libc++ and fail
# under gcc — none are needed for curation. First verified 2026-07-14:
# 211/~228 binaries built; filter/blur/modify/extend/morph/combine/pvoc/
# sfprops/housekeep all present and behaviorally consistent with macOS r8
# on the filter-sweeping tail check.
#
# Usage: scripts/build_cdp8_linux.sh [target_dir]   (default: /tmp/CDP8)
# After: export CDP_PATH=<target_dir>/NewRelease
set -euo pipefail

TARGET="${1:-/tmp/CDP8}"

if ! command -v cmake >/dev/null 2>&1; then
    echo "cmake not found; installing via pip --user" >&2
    pip install --break-system-packages -q cmake
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d "$TARGET/.git" ]; then
    git clone --depth 1 https://github.com/ComposersDesktop/CDP8 "$TARGET"
fi

# -fsigned-char: mandatory on aarch64 (unsigned-char default), harmless on
# x86. CDP's text parsers compare (char)fgetc() != EOF (cdparse.c and
# friends) — with unsigned char the loop never terminates and EVERY
# textfile input (mixfiles, breakpoints, notedata) refuses "is not a valid
# CDP file". Forensics P6-1. Per-subdir CMakeLists clobber C_FLAGS, so the
# flag must be injected into those files, not just the top-level invocation.
find "$TARGET/dev" "$TARGET" -maxdepth 3 -name CMakeLists.txt \
    -exec grep -l 'set(CMAKE_C_FLAGS' {} + 2>/dev/null | while read -r f; do
    grep -q 'fsigned-char' "$f" || \
        sed -i 's/set(CMAKE_C_FLAGS "/set(CMAKE_C_FLAGS "-fsigned-char /' "$f"
done

mkdir -p "$TARGET/build"
cd "$TARGET/build"
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS="-fsigned-char"
# -k: keep going past the clang-only externals (see header).
make -k -j"$(nproc)" || true

BUILT=$(ls "$TARGET/NewRelease" 2>/dev/null | wc -l)
echo "----------------------------------------------------------------"
echo "Built $BUILT binaries into $TARGET/NewRelease"
for p in blur filter modify extend morph combine pvoc sfprops housekeep; do
    if [ -x "$TARGET/NewRelease/$p" ]; then
        echo "  core: $p OK"
    else
        echo "  core: $p MISSING — curation harness will be degraded" >&2
    fi
done
echo "export CDP_PATH=$TARGET/NewRelease"
