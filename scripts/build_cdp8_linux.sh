#!/usr/bin/env bash
# Build the CDP binaries from source on Linux.
#
# Checks out the CDP8 commit the knowledge entries were verified against and
# builds ~211 binaries into <target_dir>/NewRelease. A few optional externals
# (reverb/rmresp and friends) hardcode clang's -stdlib=libc++ and fail under
# gcc; `make -k` skips them, and nothing here needs them.
#
# Usage: scripts/build_cdp8_linux.sh [target_dir]   (default: /tmp/CDP8)
# Then:  export CDP_PATH=<target_dir>/NewRelease
set -euo pipefail

TARGET="${1:-/tmp/CDP8}"
CDP8_COMMIT=28bc42c72c1a7cb0fab933acd1c433be958a787b  # 2026-06-08

if ! command -v cmake >/dev/null 2>&1; then
    echo "cmake not found; installing via pip --user" >&2
    pip install --break-system-packages -q cmake
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d "$TARGET/.git" ]; then
    git init -q "$TARGET"
    git -C "$TARGET" fetch -q --depth 1 https://github.com/ComposersDesktop/CDP8 "$CDP8_COMMIT"
    git -C "$TARGET" checkout -q FETCH_HEAD
fi

# -fsigned-char: mandatory on aarch64 (unsigned-char default), harmless on
# x86. CDP's text parsers compare (char)fgetc() != EOF (cdparse.c and
# friends) — with unsigned char the loop never terminates and EVERY
# textfile input (mixfiles, breakpoints, notedata) refuses "is not a valid
# CDP file". Per-subdir CMakeLists clobber C_FLAGS, so the flag must be
# injected into those files, not just the top-level invocation.
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
        echo "  core: $p MISSING" >&2
    fi
done
echo "export CDP_PATH=$TARGET/NewRelease"
