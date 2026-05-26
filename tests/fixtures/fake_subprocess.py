#!/usr/bin/env python3
"""Controllable fake subprocess for run_cdp_command tests.

Invoked as a child process by tests via :data:`sys.executable`. Cross-platform
because it's pure Python.

**CDP-quirk flags.** Flags prefixed ``--cdp-<behavior>`` simulate specific
production CDP quirks (refuse-to-clobber on existing output, crash on
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
                              [--cdp-die-on-dot-path]
                              [--cdp-silent-output PATH]

Flags execute in this order, then the process exits:

1. ``--cdp-die-on-dot-path`` scan: send SIGTERM to self (kills the
   process with a negative exit code) on any absolute-path positional
   with a ``.`` in an ancestor directory. Real CDP brassage dies with
   SIGILL, but SIGTERM is used here to avoid triggering macOS
   CrashReporter (which intercepts SIGILL/SIGABRT/SIGSEGV/etc. and shows
   a "Python quit unexpectedly" dialog). Production code only inspects
   ``exit_code != 0``, so the signal number doesn't matter. No stderr
   is emitted first — matches real brassage.
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
        "--cdp-die-on-dot-path",
        dest="cdp_die_on_dot_path",
        action="store_true",
        default=False,
        help=(
            "Simulate the brassage crash-on-dotted-path bug: scan "
            "positional args for any absolute path with a '.' in an "
            "ancestor directory, and kill the process with SIGTERM if "
            "found. (Real CDP dies with SIGILL, but SIGTERM is used here "
            "to avoid triggering macOS CrashReporter — see "
            "_trigger_signal_death for context.)"
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
    parser.add_argument(
        "--cdp-grow-file",
        dest="cdp_grow_file",
        nargs=4,
        default=None,
        metavar=("PATH", "ITERATIONS", "BYTES_PER_ITER", "INTERVAL_S"),
        help=(
            "Simulate a process writing output incrementally: append "
            "BYTES_PER_ITER zero bytes to PATH, sleep INTERVAL_S, repeat "
            "ITERATIONS times. Used to test the disk watchdog mid-stream."
        ),
    )
    args, extras = parser.parse_known_args()

    # --cdp-die-on-dot-path: scan all unknown-positional args and die via
    # signal if any looks like an absolute path with '.' in ancestry.
    # Matches the real brassage bug, which emits no stderr before crashing.
    if args.cdp_die_on_dot_path:
        for extra in extras:
            if _has_dot_in_ancestry(extra):
                _trigger_signal_death()  # never returns

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

    if args.cdp_grow_file:
        # Incremental append loop; lets the disk watchdog catch a file
        # crossing the size cap mid-run without needing real CDP.
        path, iters_s, bytes_per_iter_s, interval_s = args.cdp_grow_file
        for _ in range(int(iters_s)):
            with open(path, "ab") as f:
                f.write(b"\x00" * int(bytes_per_iter_s))
                f.flush()
            time.sleep(float(interval_s))

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


def _trigger_signal_death() -> None:
    """Kill self with a signal that produces a negative exit code, without
    triggering macOS CrashReporter.

    Real CDP brassage dies with SIGILL on Apple Silicon (illegal-instruction
    from x86 binary under Rosetta). Using SIGILL here would faithfully
    reproduce that, but on macOS the kernel routes SIGILL/SIGABRT/SIGSEGV
    and friends through ReportCrash, which generates a crash log in
    ~/Library/Logs/DiagnosticReports/ and shows the "Python quit
    unexpectedly" dialog every time the test runs. SIGTERM is a "polite"
    termination signal that produces returncode = -15 without invoking
    ReportCrash.

    Production code only inspects exit_code for == 0 / != 0; no path
    examines a specific signal value. If a future Phase 1b task needs
    signal-number fidelity, introduce a separate opt-in code path rather
    than changing this default.

    Never returns.
    """
    if hasattr(signal, "SIGTERM") and sys.platform != "win32":
        os.kill(os.getpid(), signal.SIGTERM)
    else:
        os.abort()  # Windows fallback


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
