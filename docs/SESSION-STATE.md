# Session state — 2026-07-15 (pre-compaction checkpoint)

> Written so a compacted/fresh conversation can resume without re-deriving
> context. The deep record lives in: `docs/phase-*-handoff.md`,
> `docs/phase-6-design.md` (preliminary, pre-Phase-5),
> `docs/curation/tranche*` transcripts + findings JSONs,
> `docs/forensics.md`, `docs/mir-gap-analysis.md`, and git log
> (`af6962e..HEAD` — every commit message is a work record).

## Where things stand (HEAD `9160225`)

- **Phases 1–4 complete** (Ableton export + process-output cache deferred
  with recorded rationale). **Phase 5 in progress**: wave 1 (tranches 5–6)
  done — **61 curated entries**, 189 uncurated stubs (250 total), 31 tools
  + 3 prompts, MIR v2 (13-field scorecard, trajectory/verbose block,
  33-dim cluster vector).
- Suite: 1063 hermetic / 1123 with `CDP_PATH=/tmp/CDP8/NewRelease`
  (zero CDP-gated skips; rebuild substrate via
  `scripts/build_cdp8_linux.sh`). Ruff clean.
- User verifies on macOS r8 with `CDP_PATH=... pytest` after each pull.

## Agreed next wave (Phase 5 wave 2) — not yet started

1. **Engine schema gaps first** (both discovered by tranche-5 drops, spec
   in `docs/curation/tranche5_mix_env_findings.json` dropped[] records):
   a) `pre_output` aux-param positioning (aux file must render BEFORE the
   output argv slot); b) a data-file OUTPUT kind (entries whose output is
   a `.for`/envelope data file — current verification would mis-accept
   them). Then curate the four blocked entries: **submix mix** (Phase 6
   engine; mixfile empirics already complete in tranche5 transcript),
   formants put, envel extract, formants get.
2. **scramble scramble** — the stereo seed-link trigger (working
   positional seed 0–256, mono-only, stochastic; found in tranche 6 seed
   hunt). Curate it; note it fires the long-deferred channel-machinery
   trigger (build decision belongs to the Phase 6 reevaluation).
3. **synth generators** (noise, wave) — requires the arity-0 schema
   decision (input_arity 0; resolve/preflight with no inputs).
4. **texture depth**: second/third texture modes (grouped/decorated).
5. **ST-covered singles**: envspeak, focus focus, morph bridge,
   distort reform/delete/replace, scramble sm9/10, analjoin, newdelay,
   quirk, silend.
   Target after wave 2: ~75 entries, all known Phase 6 blockers cleared.

## Phase 5 remainder after wave 2

- Generalization test matrix (clarinet-ish / field-recording / synth
  one-shot / vocal proxies through the acceptance chains; real material +
  listening is the user's half).
- Examples library (`cdp://examples/*`, sourced from saved graphs).
- Phase 5 handoff + README status bump (README currently says Phase 4 /
  31 tools / 43 entries — the 43 is stale, rest accurate).

## Phase 6 (preliminary design committed, reevaluate after Phase 5)

`docs/phase-6-design.md` — gesture construction: timeline() on submix
mixfile (empirics DONE: duration rule `max(at+dur)−min(at)`, overload
WRAPS not clips → stage headroom pre-mix, `submix getlevel` = native
pre-flight, cwd-relative paths OK); grid-free IOI/density analysis into
segments(); micro/macro boundary (gesture here, arrangement in Ableton);
pattern-generator non-goal w/ reactivation trigger. Reevaluation
checklist at the doc's end — grain rerhythm/reposition overlap with
timeline() is the open design question.

## Standing conventions (for whoever picks this up)

- Curation agents follow `docs/curation/tranche2_timedomain.md`
  methodology verbatim; findings JSON in tranche-3 shape; agents never
  touch tests/server.py; integrator applies pinned-table updates
  (breakpoint table, duration rows — single-input fixture only, counts,
  category/domain literals) then runs suite both ways.
- Source hierarchy: binaries decide, source explains, manual describes,
  SoundThread + afta8 prioritize/parameterize (re-fetch to /tmp if the
  sandbox was wiped; afta8 xrnx is in `external/`).
- Commits: descriptive, one logical unit each, `-F -` heredoc, author
  Dante Gil-Marin <drgilmarin@icloud.com> via `-c` flags.
- Known landmines: .ana raw-byte comparison (RIFF date chunk — compare
  data chunks); same-second clock-seed collisions; grain ops refuse flat
  noise fixtures; multi-input duration rows don't fit the shared formula
  fixture.

- Sandbox landmine (2026-07-15): the FULL suite with CDP_PATH set stalls
  near the end when run as one process in this sandbox (reproducible;
  both alphabetical halves pass in ~20-26 s each, 1276/1276 green).
  Chunk real-CDP runs in-sandbox; a real machine runs it whole.
