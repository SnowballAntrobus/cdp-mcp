#!/usr/bin/env python3
"""Controllable fake subprocess for run_cdp_command tests.

Invoked as a child process by tests via :data:`sys.executable`. Cross-platform
because it's pure Python.

Usage::

    python fake_subprocess.py [--stdout TEXT] [--stderr TEXT]
                              [--stderr-lines N] [--stderr-line-prefix PREFIX]
                              [--sleep SECONDS] [--exit CODE]
                              [--raw-stdout-bytes HEX]
                              [--write-wav PATH] [--write-wav-silent PATH]
                              [--write-ana PATH]

Flags execute in this order, then the process exits:

1. Print ``--stdout`` text (if given) to stdout, flushed.
2. Print ``--stderr`` text (if given) to stderr, flushed.
3. Emit ``--stderr-lines`` lines to stderr at 1-second intervals,
   each prefixed by ``--stderr-line-prefix`` (default ``"tick"``)
   followed by the 1-based index. Flushed.
4. ``--raw-stdout-bytes`` writes raw bytes (hex-decoded) directly to
   ``sys.stdout.buffer``. Useful for testing encoding edge cases.
5. ``--write-wav`` writes a 200-sample int16 mono wav (44.1 kHz,
   ±8000 amplitude) — non-silent, RMS ~-12 dBFS.
6. ``--write-wav-silent`` writes a 200-sample int16 mono wav of zeros —
   fails verify_output's silence check.
7. ``--write-ana`` writes ~2 KB of arbitrary bytes at the given path —
   passes verify_output's size check (no RMS check for .ana).
8. Sleep ``--sleep`` seconds.
9. Exit with code ``--exit`` (default 0).

Every print uses ``flush=True`` so the parent process sees output in
real time. **Uses only Python stdlib** — the system Python that exec-runs
this file via shebang may not have ``soundfile`` installed.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import wave


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
    args = parser.parse_args()

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

    if args.write_ana:
        # 2 KB of arbitrary bytes — the verifier doesn't decode .ana, just
        # checks that the file exists and is bigger than 100 bytes.
        with open(args.write_ana, "wb") as f:
            f.write(b"\xff\x00" * 1024)

    if args.sleep > 0:
        time.sleep(args.sleep)

    return args.exit


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
