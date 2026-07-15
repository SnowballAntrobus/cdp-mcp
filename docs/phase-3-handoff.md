# Phase 3 Handoff

> Companion to `docs/phase-2-handoff.md`, `docs/forensics.md`, and
> `docs/testing-principles.md`. Written 2026-07-14 at commit `e97319d`.
> Suite: 818 passed, 49 skipped (real-CDP-gated), 1 deselected (slow),
> ruff clean without CDP; **867 passed, 0 skipped** with `CDP_PATH` set
> against the in-sandbox source build (Linux) — the gated rows all
> executed for real (see Verification state). macOS r8 re-verification
> is checklist item 1.

## Shipped (this pass, commits 7e88f3f..e97319d)

**Build substrate:** `scripts/build_cdp8_linux.sh` — reproducible CDP8
build from source, 211 of ~228 binaries (a few clang-only externals
skipped, none needed), on any Linux sandbox/CI. Exploration substrate
only: **binaries built here decide during curation; the user's macOS r8
install remains the source of truth** via the CDP-gated suite. First
cross-check (filter-sweeping banner-only tail: 4.000 s → 5.000 s with
no `-t`) reproduced exactly across both.

**Wave-1 tools (server now exposes 21):**
- `search_docs`/`read_doc` — stdlib-only SQLite FTS5 over CDP's HTML
  manual (version-stamped + corpus-fingerprinted, bm25 snippets,
  sanitized MATCH, `cdp://docs/<relpath>` uris; real-corpus test: 148
  pages, "sweeping filter" surfaces cgrofilt).
- `why(target)` — backwards provenance walk over `lineage.json`:
  same-graph hops, cross-graph hops via reverse node_index lookup,
  terminal source records; depth cap 25, cycle guard; mid-chain lineage
  gaps degrade to warnings rather than discarding the chain.
- `write_data_file(name, content)` — auxiliary text/data inputs
  (`<session>/data/`, allowlist .txt/.dat/.csv/.brk, 4 MiB cap, atomic,
  security-gate acceptance pinned).
- `cluster(targets|"latest_batch", k=None, seed=42)` — MFCC-stat
  features → StandardScaler → PCA → Ward agglomerative; silhouette
  auto-k (2..6); per-cluster medoid = the one file to audition. Closes
  batch → cluster → compare-medoids → keep. New dep: scikit-learn ≥ 1.3.

**Curation harness:** `scripts/curation_harness.py` — 211-binary banner
scan + SoundThread `process_help.json` cross-ref (129 processes) →
`docs/curation/harness_report.json`, the tranche-planning substrate.

**Curation, three tranches (6 → 42 entries):** 13 + 12 + 11 new entries
(`e6f95d4`, `4777440`, `e737082`), every value probed against real
binaries — full transcripts and machine-readable findings in
`docs/curation/tranche{1,2,3}_{spectral,timedomain}*`. The four-source
evidence hierarchy institutionalized: **binaries decide, source
explains, manual describes, SoundThread + afta8 prioritize.** Duration
models up to ternary and floor-division expressions (modify stack,
bounce bounce, extend doublets) verified through the repo's own
simpleeval; 41 duration-formula rows and the per-parameter breakpoint
probe table pinned as CDP-gated regressions. Headline forensics
(forensics.md P3-1..P3-13): blur scatter NOT stochastic, blur drunk
stochastic-and-seedless, revecho's `_WIN32` seeding split, four
undocumented distort breakpoint capabilities, the filter-group
banner-only tail class, specfnu sm19's teardown crash, spec magnify /
focus fold / extend doublets silent-success edges.

**afta8 acquisition + merge:** `external/com.afta8.CdpInterface_v0.68`
xrnx (user-downloaded; sandbox proxy blocks renoise.com) parsed by
`scripts/parse_afta8_definitions.py` → `docs/curation/
afta8_definitions.json`: 888 process definitions across 97 executables —
17× the design doc's "~50 processes" estimate (`506a20b`). Cross-check
vs tranche 1: 5 exact breakpoint agreements, 0 contradictions; afta8
brk flags confirmed a conservative floor. Tips merge (`4c3c0eb`):
musical guidance folded into `musical_use`/param descriptions on 11 of
the 19 then-curated entries — advisory prose only, probed fields
untouched; one unresolved contradiction (filter sweeping shape
numbering) logged in `known_issues` with a re-verification cue.

**Harness fix (`e97319d`):** spectral duration rows now measured via
`synth_for_audition` round-trips instead of `sf.info()` on `.ana` —
see Verification state.

## Deliberate deviations from the design doc (all documented in-code/docs)

- **FTS5 rebuild is lazy**, at tool-call time (`docs_index.ensure_index`
  from `search_docs`/`read_doc`), not at `set_session()` as the design
  committed. Sessions that never touch docs tools never pay the build;
  the staleness check (CDP version + corpus fingerprint) still runs
  before every query that could observe stale data. Rationale in the
  `docs_index.py` module docstring.
- `analyze(verbose)` returning summary statistics rather than per-frame
  matrices is a **Phase 2** deviation, unchanged here (recorded in
  `docs/phase-2-handoff.md`).
- **Single-mode specfnu pinning:** `KnowledgeIndex` keys entries by
  `(program, mode)` = `("specfnu", "specfnu")`, so exactly one of
  specfnu's 23 modes can be curated under the current schema. Mode 1
  (NARROW FORMANTS) was pinned after an 8-mode survey; mode 19 is
  disqualified outright by a teardown crash after valid output
  (forensics P3-8). Curating more specfnu modes needs a submode-aware
  key — a schema decision, not a curation one.
- **`cluster()` shipped PCA + Ward only.** The design's optional UMAP
  path was not added — no consumer asked, and the committed default
  needs only scikit-learn.
- **Dual-source verification script** (import-time HTML-vs-source argv
  cross-check) was superseded by something stronger: probing the
  binaries themselves and pinning every outcome as executable CDP-gated
  rows (`test_curation_formulas.py`, `test_breakpoint_curation.py`).
  A static argv-shape comparison would have missed most of what the
  probes caught (unenforced constraints, silent successes, wrong banner
  ranges).
- **`texture simple` dropped, not shipped broken** (tranche 3): its
  required notedata slot is an auxiliary TEXT file the schema cannot
  express — `validate_params` rejects non-`.brk` strings, and a
  `.brk`-named notedata file would be mis-routed through the breakpoint
  compiler. The dropped record in
  `docs/curation/tranche3_timedomain_findings.json` preserves full probe
  data (genuinely stochastic, WORKING `-r` seed — CDP's first
  controllable-seed find — mono-in/stereo-out) and a concrete
  recommendation: an `aux_file` ParameterSpec type that
  `validate_params` accepts as-is, `build_cdp_argv` renders
  cwd-relativised at its positional slot, and lineage records by content
  hash — `write_data_file` already produces exactly these files. That
  work is **landing concurrently** with this handoff.
- **No channel-handling / stereo-seed-link wiring** — the design doc
  expected Phase 3's first `phase_sensitive: true` entry to trigger it.
  Honestly: 42 entries in, **no curated entry provides the required
  consumer.** The machinery needs a *seeded, stochastic, mono-only*
  entry, so that a stereo input forces the L/R split and the
  linked/related/independent seed modes have a seed to drive. What we
  actually have: `blur drunk` is phase_sensitive and mono-constrained
  but **seedless** (`srand(time(NULL))`, no flag — forensics P3-2);
  `extend zigzag`/`extend scramble` are seeded and stochastic but accept
  stereo natively (`channel_constraint: any` — no split path ever
  fires); `texture simple` is seeded but **mono-in/stereo-out** (and
  dropped). The L/R-split machinery still has no exercisable case.
  **Reactivation trigger: the first seeded, mono-constrained stochastic
  curated entry** — the grain family is the likeliest source.
- **Mono-sum listening tests** for `phase_sensitive: true` entries
  (design Phase 3 item) were not performed; `stereo_link_default:
  "related"` values rest on source-level seeding analysis. Open item —
  meaningful only once the wiring above exists to consume them.

## Verification state

- Without CDP: 818 passed, 49 skipped (all real-CDP-gated), 1 deselected
  (slow), ruff clean. With `CDP_PATH` pointed at the sandbox source
  build: **867 passed, 0 skipped** — every gated case (41 duration
  formula rows, the breakpoint probe table, acceptance suites)
  **executed** against real binaries in-sandbox (2026-07-14, `e97319d`).
  This is new capability: before `build_cdp8_linux.sh`, gated cases only
  ever ran on the dev macOS machine.
- Division of authority stands: the sandbox build is the exploration
  substrate; **macOS r8 is the source of truth**, and re-running the
  suite there is the cross-platform check (checklist item 1). The one
  behavioral cross-check performed both sides (filter-sweeping tail)
  agreed exactly.
- **The 2026-07-14 `.ana` harness lesson:** the macOS QA run failed all
  16 spectral duration rows with `LibsndfileError` — libsndfile cannot
  open `.ana`, and the shared harness measured with `sf.info()` while
  the tranche agents had (correctly) measured via pvoc-synth round-trips
  *outside* the shared test. Integration bug, not platform divergence;
  fixed in `e97319d` by routing `.ana`/`.pvx` through
  `synth_for_audition`. The durable rule is now `testing-principles.md`
  §10: **integration code extending a pinned table must EXECUTE the
  table, not just collect it** — and with the sandbox build, executing
  gated rows before merge costs nothing.

## Open items for Phase 4/5

- **Phase 4 design list, unchanged:** `tag()`, `journal()`,
  `set_config()`; `save_graph()`/`load_graph()`/`list_graphs()`;
  `cleanup()` built alongside dependency_index (1b Task 14);
  `cleanup_cache()`; process-output cache reconsideration (1b Task 12) —
  must key on **sample equivalence, not raw sha256**, and re-run the
  determinism investigation per `docs/phase-2-determinism.md`;
  regenerate-from-lineage round-trip; prompt templates;
  `export_to_ableton()`.
- **Phase 2 leftovers carry over** (see `docs/phase-2-handoff.md`):
  Task 04/07 re-lands (`git revert c804a03` before exposing `_pvoc.*`;
  `audio_align.py` when a length-alignment consumer appears),
  `breakpoint_duration_source` input2/max/min, audit moderates M6–M12.
- **`aux_file` + texture: landing concurrently** with this handoff.
  Unblocks the whole TEXTURE suite plus modify stack's per-layer
  transposition-file form (same schema gap, tranche-3 findings).
- **`curated: false` long-tail: landing concurrently** — the
  auto-generated minimal entries for the uncurated remainder of the 211
  binaries (design Phase 3 item) are being implemented in a parallel
  pass as this handoff is written; treat repo state as authoritative.
- **Family gaps in the curated 42:** zero entries from the **grain**,
  **repitch**, and **synth/generator** families (texture pending the
  aux_file landing). Grain matters doubly — the design doc named it a
  phase-sensitive candidate, and a seeded mono-only grain program is the
  likeliest reactivation trigger for the stereo seed-link wiring.
- Also still open: strange_glis's `default: false` bool (always-emitted
  `-i` if engine-built — flagged in tranche 3, entry not yet migrated to
  the `default: null` convention); specfnu submode-aware keying; the
  filter-sweeping shape-numbering contradiction (afta8 vs our pinning vs
  the r8 banner — `known_issues` carries the re-verification cue).
- **Phase 5 (design list):** examples library; curation 42 → ~100;
  generalization testing (clarinet multisample, field recording, synth
  one-shot, vocal phrase); documentation.

## Manual-test checklist (real CDP, your machine)

1. `pytest` with `CDP_PATH` set — the 49 skips become real: all 41
   duration-formula rows (16 spectral ones now synth-measured), the
   breakpoint-curation probe table, both acceptance suites. Also
   `pytest -m slow` for the keepalive stress test.
2. `search_docs("sweeping filter")` — expect cgrofilt near the top;
   `read_doc` the returned uri. Run a second query and confirm no
   rebuild (lazy index built once, then fingerprint-stable).
3. `why()` on a real chain: process a 2–3 node chain (e.g. wav →
   auto-PVOC → `blur spread` → `stretch time`), then `why("latest")` —
   the walk should land on the source wav with hashes at every hop.
4. `batch()` 6+ param variations (e.g. `bounce bounce` over a
   count/shorten grid) → `cluster("latest_batch")` — sane k from the
   silhouette scan, one medoid per cluster → `compare()` two medoids
   (also re-exercises the 1 MB composite downscale, forensics P3-15).
5. One tranche-3 entry end-to-end with its model: `extend doublets`
   segdur 0.25 / repets 3 on a 2 s input — dry-run predicts ~5.145 s;
   confirm the render matches within tolerance.
6. If `aux_file`/texture has landed: `write_data_file("nd.txt", "60")` →
   `texture simple` mode 5 → confirm stereo-out from mono-in, and `-r5`
   twice → identical outputs (the working-seed find, forensics P3-5).
7. `specfnu` sm1 on macOS r8 — confirm `WARNING: failed to write PEAK
   data` appears on a *successful* run and the envelope still reports
   ok (forensics P3-8 says harnesses must tolerate it; verify ours does
   on this platform too).
