#!/usr/bin/env python3
"""Controllable fake subprocess for run_cdp_command tests.

Invoked as a child process by tests via :data:`sys.executable`. Cross-platform
because it's pure Python.

**CDP-quirk flags.** Flags prefixed ``--cdp-<behavior>`` simulate specific
production CDP quirks (refuse-to-clobber on existing output, SIGILL on
dotted absolute paths, silent-output despite exit 0). They are distinct
from the generic ``--write-*`` / ``--stdout`` / ``--stderr`` flags, which
are agnostic test utilities. New CDP-quirk flags follow the same
``--cdp-<behavior>`` naming convention.

Usage::

    python fake_subprocess.py [--stdout TEXT] [--stderr TEXT]
                              [--stderr-lines N] [--stderr-line-prefix PREFIX]
                              [--sleep SECONDS] [--exit CODE]
                              [--raw-stdout-bytes HEX]
                              [--write-wav PATH] [--write-wav-silent PATH]
                              [--write-ana PATH]
                              [--cdp-refuse-clobber PATH]
                              [--cdp-sigill-on-dot-path]
                              [--cdp-silent-output PATH]

Flags execute in this order, then the process exits:

1. ``--cdp-sigill-on-dot-path`` scan: SIGILL (POSIX) / ``os.abort()``
   (Windows) on any absolute-path positional with a ``.`` in an ancestor
   directory. No stderr is emitted first — matches real brassage.
2. ``--cdp-refuse-clobber PATH``: if ``PATH`` exists, emit the canonical
   ``"ERROR: cannot create output file ..."`` to stderr and exit 255,
   ignoring all other flags.
3. Print ``--stdout`` text (if given) to stdout, flushed.
4. Print ``--stderr`` text (if given) to stderr, flushed.
5. Emit ``--stderr-lines`` lines to stderr at 1-second intervals,
   each prefixed by ``--stderr-line-prefix`` (default ``"tick"``)
   followed by the 1-based index. Flushed.
6. ``--raw-stdout-bytes`` writes raw bytes (hex-decoded) directly to
   ``sys.stdout.buffer``. Useful for testing encoding edge cases.
7. ``--write-wav`` writes a 200-sample int16 mono wav (44.1 kHz,
   ±8000 amplitude) — non-silent, RMS ~-12 dBFS.
8. ``--write-wav-silent`` writes a 200-sample int16 mono wav of zeros —
   fails verify_output's silence check.
9. ``--cdp-silent-output PATH`` writes a silent wav (same code path as
   ``--write-wav-silent``; the alias exists so tests can name the CDP
   anti-pattern they're simulating).
10. ``--write-ana`` writes ~2 KB of arbitrary bytes at the given path —
    passes verify_output's size check (no RMS check for .ana).
11. Sleep ``--sleep`` seconds.
12. Exit with code ``--exit`` (default 0).

Every print uses ``flush=True`` so the parent process sees output in
real time. **Uses only Python stdlib** — the system Python that exec-runs
this file via shebang may not have ``soundfile`` installed.
"""

from __future__ import annotations

import argparse
import os
import signal
import struct
import sys
import time
import wave
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", default=None)
    parser.add_argument("--stderr", default=None)
    parser.add_argument("--stderr-lines", type=int, default=0)
    parser.add_argument("--stderr-line-prefix", default="tick")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--exit", type=int, default=0)
    parser.add_argument("--raw-stdout-bytes", default=None,
                        help="Hex string of raw bytes to write to stdout.")
    parser.add_argument("--write-wav", default=None,
                        help="Write a non-silent 200-sample int16 mono wav at this path.")
    parser.add_argument("--write-wav-silent", default=None,
                        help="Write a silent (all-zero) 200-sample wav at this path.")
    parser.add_argument("--write-ana", default=None,
                        help="Write a ~2 KB stub .ana file at this path.")
    parser.add_argument(
        "--cdp-refuse-clobber",
        dest="cdp_refuse_clobber",
        default=None,
        help=(
            "Simulate CDP r8 pvoc synth's refuse-to-clobber behavior: if "
            "the given path exists, print an error to stderr and exit 255 "
            "before running any other flag."
        ),
    )
    parser.add_argument(
        "--cdp-sigill-on-dot-path",
        dest="cdp_sigill_on_dot_path",
        action="store_true",
        default=False,
        help=(
            "Simulate the brassage SIGILL bug: scan positional args for "
            "any absolute path with a '.' in an ancestor directory, and "
            "kill the process with SIGILL if found. No stderr is emitted "
            "first."
        ),
    )
    parser.add_argument(
        "--cdp-silent-output",
        dest="cdp_silent_output",
        default=None,
        help=(
            "Simulate the 'CDP exits 0 with silent output' anti-pattern. "
            "Writes a silent wav at the given path; same code path as "
            "--write-wav-silent but named for what it simulates."
        ),
    )
    args, extras = parser.parse_known_args()

    # --cdp-sigill-on-dot-path: scan all unknown-positional args and SIGILL
    # if any looks like an absolute path with '.' in ancestry. Matches the
    # real brassage bug, which emits no stderr before crashing.
    if args.cdp_sigill_on_dot_path:
        for extra in extras:
            if _has_dot_in_ancestry(extra):
                _trigger_sigill_like()  # never returns

    # --cdp-refuse-clobber PATH: if PATH already exists, emit the canonical
    # "cannot create output" stderr and exit 255. Real CDP r8 pvoc synth.
    if args.cdp_refuse_clobber is not None and os.path.exists(
        args.cdp_refuse_clobber
    ):
        print(
            f"ERROR: cannot create output file {args.cdp_refuse_clobber}",
            file=sys.stderr,
            flush=True,
        )
        return 255

    if args.stdout is not None:
        print(args.stdout, flush=True)
    if args.stderr is not None:
        print(args.stderr, file=sys.stderr, flush=True)

    for i in range(1, args.stderr_lines + 1):
        print(f"{args.stderr_line_prefix} {i}", file=sys.stderr, flush=True)
        time.sleep(1.0)

    if args.raw_stdout_bytes:
        sys.stdout.buffer.write(bytes.fromhex(args.raw_stdout_bytes))
        sys.stdout.buffer.flush()

    if args.write_wav:
        _write_wav(args.write_wav, silent=False)

    if args.write_wav_silent:
        _write_wav(args.write_wav_silent, silent=True)

    if args.cdp_silent_output:
        _write_wav(args.cdp_silent_output, silent=True)

    if args.write_ana:
        # 2 KB of arbitrary bytes — the verifier doesn't decode .ana, just
        # checks that the file exists and is bigger than 100 bytes.
        with open(args.write_ana, "wb") as f:
            f.write(b"\xff\x00" * 1024)

    if args.sleep > 0:
        time.sleep(args.sleep)

    return args.exit


def _has_dot_in_ancestry(path: str) -> bool:
    """True if ``path`` is absolute AND any ancestor directory name (not
    the basename) contains a literal ``.``.

    The basename's ``.`` (file extension) is intentionally NOT a trigger —
    the bug being simulated is about dots in *directory* names like
    ``frog_v0.1``.
    """
    if not path.startswith("/"):
        return False
    parent = Path(path).parent
    for part in parent.parts:
        if part in ("/", ""):
            continue
        if "." in part:
            return True
    return False


def _trigger_sigill_like() -> None:
    """SIGILL on POSIX, ``os.abort()`` elsewhere. Never returns."""
    if hasattr(signal, "SIGILL") and sys.platform != "win32":
        os.kill(os.getpid(), signal.SIGILL)
    else:
        os.abort()


def _write_wav(path: str, *, silent: bool) -> None:
    """Write a 200-sample int16 mono wav at 44.1 kHz.

    Non-silent variant alternates ±8000 (RMS ~-12 dBFS, well above the
    verifier's -60 dBFS threshold). Silent variant is all zeros.
    """
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = bytearray()
        for i in range(200):
            v = 0 if silent else (8000 if i % 2 else -8000)
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


if __name__ == "__main__":
    sys.exit(main())
