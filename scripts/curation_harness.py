#!/usr/bin/env python3
"""Phase 3 curation harness — empirical program inventory from real CDP.

Runs every binary in a CDP install bare (and once per discovered mode) to
capture usage banners, then cross-references SoundThread's curated
``process_help.json``. The output report is the raw material for entry
drafting: what exists, what the banner claims, which programs the most
successful CDP wrapper considered worth curating, and where banners
diverge from the HTML manual (the filter-sweeping-tail bug class).

Usage:
    python3 scripts/curation_harness.py CDP_BIN_DIR [SOUNDTHREAD_DIR] [OUT.json]

Defaults: SOUNDTHREAD_DIR=/tmp/SoundThread, OUT=docs/curation/harness_report.json

Banner capture never trusts exit codes (CDP exits nonzero for usage) and
caps each run at 10 s (a bare invocation should never block; a handful of
programs try to read stdin — stdin is closed to prevent hangs).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_MODE_TOKEN = re.compile(r"^[a-z][a-z0-9_]{1,15}$")


def banner(argv: list[str]) -> str:
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL, errors="replace",
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"<<harness: failed to run: {type(e).__name__}: {e}>>"
    return (r.stdout or "") + (r.stderr or "")


def extract_modes(text: str) -> list[str]:
    """Best-effort mode tokens from a top-level banner's USAGE line(s).

    CDP top-level banners typically read ``USAGE: blur NAME (mode)`` then
    list modes, or ``USAGE: filter bank|sweeping|...``. We collect
    pipe-separated lowercase tokens from lines mentioning the program
    usage, dedupe, and let the per-mode banner capture confirm (a bogus
    token just yields an error banner, which the report keeps anyway).
    """
    modes: list[str] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        for chunk in re.split(r"[\s]+", line.strip()):
            if "|" in chunk:
                for tok in chunk.split("|"):
                    tok = tok.strip().lower()
                    if _MODE_TOKEN.match(tok) and tok not in modes:
                        modes.append(tok)
    return modes[:40]


def main() -> None:
    cdp_dir = Path(sys.argv[1])
    st_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/SoundThread")
    out = (
        Path(sys.argv[3]) if len(sys.argv) > 3
        else Path("docs/curation/harness_report.json")
    )

    soundthread: dict = {}
    st_json = st_dir / "scenes" / "main" / "process_help.json"
    if st_json.exists():
        soundthread = json.loads(st_json.read_text())

    programs = sorted(
        p.name for p in cdp_dir.iterdir()
        if p.is_file() and (p.stat().st_mode & 0o111)
    )
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cdp_dir": str(cdp_dir),
        "program_count": len(programs),
        "soundthread_process_count": len(soundthread),
        "programs": {},
    }

    st_by_prog: dict[str, list[str]] = {}
    for key in soundthread:
        st_by_prog.setdefault(key.split("_")[0], []).append(key)

    for name in programs:
        text = banner([str(cdp_dir / name)])
        modes = extract_modes(text)
        entry: dict = {
            "banner": text[:4000],
            "modes_guessed": modes,
            "mode_banners": {},
            "soundthread_keys": sorted(st_by_prog.get(name, [])),
        }
        for mode in modes:
            mb = banner([str(cdp_dir / name), mode])
            # Keep only banners that look like real usage (mention the
            # mode or USAGE); error banners are kept short.
            entry["mode_banners"][mode] = mb[:2500]
        report["programs"][name] = entry

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    covered = sum(1 for p in report["programs"].values() if p["soundthread_keys"])
    print(f"{len(programs)} programs scanned; {covered} have SoundThread coverage")
    print(f"report: {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
