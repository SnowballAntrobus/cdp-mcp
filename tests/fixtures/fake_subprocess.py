#!/usr/bin/env python3
"""Controllable fake subprocess for run_cdp_command tests.

Invoked as a child process by tests via :data:`sys.executable`. Cross-platform
because it's pure Python.

Usage::

    python fake_subprocess.py [--stdout TEXT] [--stderr TEXT]
                              [--stderr-lines N] [--stderr-line-prefix PREFIX]
                              [--sleep SECONDS] [--exit CODE]
                              [--raw-stdout-bytes HEX]

Flags execute in this order, then the process exits:

1. Print ``--stdout`` text (if given) to stdout, flushed.
2. Print ``--stderr`` text (if given) to stderr, flushed.
3. Emit ``--stderr-lines`` lines to stderr at 1-second intervals,
   each prefixed by ``--stderr-line-prefix`` (default ``"tick"``)
   followed by the 1-based index. Flushed.
4. ``--raw-stdout-bytes`` writes raw bytes (hex-decoded) directly to
   ``sys.stdout.buffer``. Useful for testing encoding edge cases.
5. Sleep ``--sleep`` seconds.
6. Exit with code ``--exit`` (default 0).

Every print uses ``flush=True`` so the parent process sees output in
real time, which the progress-reporting tests depend on.
"""

from __future__ import annotations

import argparse
import sys
import time


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

    if args.sleep > 0:
        time.sleep(args.sleep)

    return args.exit


if __name__ == "__main__":
    sys.exit(main())
