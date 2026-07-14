#!/usr/bin/env python3
"""Parse afta8's CDP Interface definitions.lua into JSON priors.

The Renoise CDP Lua Tool (com.afta8.CdpInterface, v0.68) ships 889
process definitions hand-tuned by afta8 + Djeroek — exe/mode, per-arg
names, slider ranges (sometimes Lua expressions over the input's
``length`` in ms, kept verbatim as strings), switch flags, breakpoint
capability (``input = "brk"``), doc URLs with anchors, and musical tips.

This is a PRIORS source for curation (like SoundThread's
process_help.json): it suggests and prioritizes; the binaries decide.

Usage:
    python3 scripts/parse_afta8_definitions.py XRNX_EXTRACT_DIR [OUT.json]
Default OUT: docs/curation/afta8_definitions.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ENTRY_RE = re.compile(r'^dsp\["(.+?)"\]\s*=\s*\{', re.M)
_FIELD_RE = re.compile(
    r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^,}]+))'
)


def _parse_block(block: str) -> dict:
    """Parse one dsp[...] table body: cmds + argN sub-tables."""
    out: dict = {"args": {}}
    for m in re.finditer(r'(cmds|arg\d+)\s*=\s*\{(.*?)\}\s*,?\s*$',
                         block, re.M | re.S):
        key, body = m.group(1), m.group(2)
        fields: dict = {}
        for fm in _FIELD_RE.finditer(body):
            name = fm.group(1)
            if fm.group(2) is not None:
                fields[name] = fm.group(2)
            else:
                raw = fm.group(3).strip()
                try:
                    fields[name] = float(raw) if "." in raw else int(raw)
                except ValueError:
                    fields[name] = {"expr": raw}  # Lua expression (length/1000 …)
        if key == "cmds":
            out["cmds"] = fields
        else:
            out["args"][key] = fields
    return out


def main() -> None:
    src = Path(sys.argv[1]) / "definitions.lua"
    out_path = (
        Path(sys.argv[2]) if len(sys.argv) > 2
        else Path("docs/curation/afta8_definitions.json")
    )
    text = src.read_text(encoding="latin-1")

    entries: dict = {}
    matches = list(_ENTRY_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parsed = _parse_block(text[m.end():end])
        cmds = parsed.get("cmds", {})
        exe, mode = cmds.get("exe", ""), cmds.get("mode", "")
        parsed["display_name"] = m.group(1)
        # brk-capable args are the tool's breakpoint UI hooks.
        parsed["brk_args"] = sorted(
            a["name"] for a in parsed["args"].values()
            if isinstance(a.get("input"), str) and a["input"] == "brk"
            and isinstance(a.get("name"), str)
        )
        entries[f"{exe}::{mode}::{m.group(1)}"] = parsed

    by_exe: dict[str, int] = {}
    for k in entries:
        by_exe[k.split("::")[0]] = by_exe.get(k.split("::")[0], 0) + 1
    payload = {
        "source": "com.afta8.CdpInterface_v0.68_api5.xrnx / definitions.lua",
        "entry_count": len(entries),
        "exe_count": len(by_exe),
        "entries": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"{len(entries)} definitions across {len(by_exe)} executables")
    print(f"-> {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
