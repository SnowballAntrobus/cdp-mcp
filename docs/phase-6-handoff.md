# Phase 6 handoff — gesture construction + full coverage (2026-07-16)

> Companion records: `docs/phase-6-design.md` (the reevaluated design +
> post-run recheck), `docs/curation/roadmap-tranches-12plus.md` +
> `tranche9..24`-era transcripts/findings, `docs/forensics.md` §P6,
> and the git log — every commit message is a work record.

## What Phase 6 was

Two halves. The **curation completion run** (tranches 9–23, six waves
of paired agents): 43 → 348 curated entries covering every relevant
CDP family; 99 stubs remain (out-of-scope spatial family, toolkit
plumbing, defect-dropped programs — all evidenced). And the **gesture
construction build** on top of it:

- **`timeline()`** (tool #33): deterministic multi-source event
  placement — events `{source, at, level?, pan?}` with the full
  reference grammar, mixfile via the data-file machinery, duration
  pre-flight `max(at+dur) − min(at)`, execution through the standard
  node path onto `submix mix`. Headroom staging runs the CURATED
  `submix getlevel 3` pre-flight (overload WRAPS — P5-3):
  `headroom="auto"` applies the factor as `-g`, `"fail"` errors with
  it, `"off"` renders raw with a wrap warning. v1 is submix-only by
  decision: pitch-bearing scores route to `extend sequence2`
  (no-wrap, resampling transposition) per the docstring.
- **Grid-free rhythm analysis** in `segments()`: IOI stats
  (mean/std/min/max/slope) with an accelerando/ritardando/steady
  trend verdict (±5% of mean IOI per event) + a 16-point density
  trajectory. No grid inference, per the standing ruling.
- **Discoverability** (tool #34 + prompt #4): `search_programs()` —
  FTS5 over the curated entries themselves (weighted: names >
  taxonomy > musical_use > description > params > known_issues),
  natural-phrase handling (stopwords, prefix match, AND→OR retry) —
  and the `recommend_transforms` prompt encoding the sample-driven
  path: analyze(verbose) → material class per the generalization
  matrix → targeted searches → known_issues/constraint checks →
  sweep/batch audition → compare/tag.
- **Error mapping**: 11 stdout-refusal patterns from the curation
  run's verbatim corpus, each with a grounded fix (e.g. NO
  SILENCE-GAPS → the verified gate→retime chain).
- **Schema gaps closed**: `free_string` positionals (blur/distort
  shuffle curated) and `.frq`/`.trn` pitch-data kinds — the
  15-program repitch transform layer promoted (8 musically distinct
  entries); the full curated pitch workflow (getpitch → quantise/
  vibrato/... → transposef) runs with no `execute()` escape.

## Not done / deferred

- **Bucephalus pipeline example** — skipped on user instruction
  (usage credits); all machinery it needs (sweep, timeline, IOI
  verify, analyze) is shipped and individually tested. First real
  gesture session can produce the `cdp://examples/*` recipe.
- **Mode-token argv gap** (columns/tabedit family) — deferred with
  usage trigger, unchanged.
- **Phase 6b stereo seed-link** — machinery prerequisites curated
  (housekeep chans 3/4 split, submix interleave merge); build waits
  on a real session hitting a mono-only stochastic op with stereo
  material.
- Deferred with rationale, still: export_to_ableton, process-output
  cache.

## Suite

3160 hermetic / real-CDP green in chunks (the full single-process
real-CDP run exceeds the sandbox call cap — run whole on a real
machine). Ruff clean. macOS QA expectation unchanged: filter-bank
vintage hang (P5-1) until the local binary is rebuilt; the
aarch64-only signed-char landmine (P6-1) does not affect macOS.

## Manual checklist (your machine)

1. `CDP_PATH=... pytest` — expect the P5-1 red only.
2. `search_programs("make it shimmer and sustain")` — sanity-check
   the ranking against your taste; try your own vocabulary.
3. The recommend_transforms prompt on a real sample: analyze →
   search → sweep → compare.
4. A real gesture: sweep an impact × 8, compute a geometric bounce
   series, `timeline(events, headroom="auto")`, then `segments()` —
   the rhythm block should call it "accelerando".
