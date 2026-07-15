#!/usr/bin/env python3
"""Phase 3 long-tail generator — minimal uncurated knowledge stubs.

Reads the curation harness report (``docs/curation/harness_report.json``,
produced by ``scripts/curation_harness.py``) and, for every CDP program
that no curated entry covers, writes a minimal ``curated: false`` stub
into ``src/cdp_mcp/knowledge/data_uncurated/<program>.json``.

The stubs exist for *discovery only*: the loader surfaces them through
``list_programs(curated_only=False)`` so an LLM can see the long tail of
what the CDP install offers, but ``process()`` hard-gates on
``entry.curated`` and refuses them — ``execute()`` remains the path for
uncurated programs.

Field policy (deliberately conservative):

- ``mode``: the first harness-guessed mode, else ``"<unknown>"``.
- ``domain``: ``"spectral"`` if the usage banner mentions ``.ana``,
  else ``"time"`` — a best guess, clearly labeled unverified.
- ``description``: the first meaningful banner line (skipping version
  banners, USAGE lines, and errors), truncated to 200 chars.
- ``stability: "unstable"``, ``input_arity: 1``, empty parameters —
  nothing here is verified against the binary.
- ``channel_constraint`` / ``input_format`` / ``output_format`` are
  required by the schema (no defaults), so the stub carries ``"any"``
  and the domain-matched extension.

Every generated dict is validated through the real
:class:`cdp_mcp.schema.KnowledgeEntry` before writing; entries that fail
are skipped and logged so a malformed stub can never break the loader.

Usage:
    PYTHONPATH=src python3 scripts/generate_uncurated_entries.py \
        [HARNESS_REPORT.json] [OUT_DIR]

Defaults: docs/curation/harness_report.json,
src/cdp_mcp/knowledge/data_uncurated/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from cdp_mcp.schema import KnowledgeEntry  # noqa: E402

_DEFAULT_REPORT = _REPO_ROOT / "docs" / "curation" / "harness_report.json"
_DEFAULT_OUT_DIR = _REPO_ROOT / "src" / "cdp_mcp" / "knowledge" / "data_uncurated"
_CURATED_DIR = _REPO_ROOT / "src" / "cdp_mcp" / "knowledge" / "data"

_DESCRIPTION_MAX_CHARS = 200

# Banner lines that carry no descriptive content — version banners,
# usage syntax, error output from programs that refuse a bare run.
_SKIP_PREFIXES = ("cdp release", "usage", "error", "<<harness")


def curated_programs() -> set[str]:
    """Program names covered by at least one curated entry."""
    programs: set[str] = set()
    for path in sorted(_CURATED_DIR.glob("*.json")):
        try:
            programs.add(json.loads(path.read_text(encoding="utf-8"))["program"])
        except (json.JSONDecodeError, KeyError, OSError) as e:
            print(f"WARNING: unreadable curated entry {path.name}: {e}", file=sys.stderr)
    return programs


def first_meaningful_line(banner: str, program: str) -> str:
    """First banner line that looks like a description, capped at 200 chars.

    Skips blank lines, CDP version banners, USAGE/syntax lines (including
    the argv-template continuation lines that start with the program name,
    a flag bracket, or ``OR``), and error output. Returns ``""`` when
    nothing qualifies (e.g. programs whose bare run prints only an error).
    """
    for line in banner.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith(_SKIP_PREFIXES):
            continue
        # Argv-template continuations under a USAGE: header.
        if lowered.startswith((program.lower() + " ", "[", "-")) or lowered == "or":
            continue
        return stripped[:_DESCRIPTION_MAX_CHARS]
    return ""


def guess_domain(banner: str) -> str:
    """``"spectral"`` iff the banner mentions ``.ana`` or "analysis file".

    No banner in the r8 harness report literally contains ``.ana`` (CDP
    banners write "infile"), so the phrase "analysis file(s)" — the
    banners' way of saying the program operates on PVOC analysis data —
    is accepted as the same signal. Everything else defaults to
    ``"time"``; both are best guesses, flagged unverified in
    ``known_issues``.
    """
    lowered = banner.lower()
    return "spectral" if (".ana" in lowered or "analysis file" in lowered) else "time"


def build_stub(program: str, info: dict) -> dict:
    banner = info.get("banner", "") or ""
    modes = info.get("modes_guessed") or []
    # Domain guess reads the mode banners too — some programs only
    # reveal their file type at mode level. Description stays top-level.
    all_text = banner + "".join((info.get("mode_banners") or {}).values())
    domain = guess_domain(all_text)
    fmt = ".ana" if domain == "spectral" else ".wav"
    return {
        "program": program,
        "mode": modes[0] if modes else "<unknown>",
        "category": "uncurated",
        "domain": domain,
        "input_arity": 1,
        "channel_constraint": "any",
        "input_format": fmt,
        "output_format": fmt,
        "curated": False,
        "stability": "unstable",
        "description": first_meaningful_line(banner, program),
        "musical_use": "",
        "parameters": {},
        "duration_model": {"kind": "static"},
        "examples": [],
        "known_issues": ["auto-generated from usage banner; unverified"],
        "references": [],
    }


def main(argv: list[str]) -> int:
    report_path = Path(argv[1]) if len(argv) > 1 else _DEFAULT_REPORT
    out_dir = Path(argv[2]) if len(argv) > 2 else _DEFAULT_OUT_DIR

    report = json.loads(report_path.read_text(encoding="utf-8"))
    covered = curated_programs()
    out_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for program, info in sorted(report["programs"].items()):
        if program in covered:
            continue
        stub = build_stub(program, info)
        try:
            KnowledgeEntry.model_validate(stub)
        except ValidationError as e:
            print(f"SKIP {program}: stub failed schema validation: {e}", file=sys.stderr)
            skipped += 1
            continue
        target = out_dir / f"{program}.json"
        target.write_text(
            json.dumps(stub, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written += 1

    print(
        f"Wrote {written} uncurated stub(s) to {out_dir} "
        f"({len(covered)} curated program(s) excluded, {skipped} skipped)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
