# Session state — 2026-07-15 (Phase 5 CLOSED)

> Written so a compacted/fresh conversation can resume without re-deriving
> context. The deep record lives in: `docs/phase-*-handoff.md` (Phase 5:
> `docs/phase-5-handoff.md`), `docs/phase-6-design.md` (preliminary,
> pre-Phase-5 — reevaluation is now due), `docs/curation/tranche*`
> transcripts + findings JSONs, `docs/forensics.md`,
> `docs/generalization-matrix.md`, `docs/mir-gap-analysis.md`, and git
> log (`af6962e..HEAD` — every commit message is a work record).

## Where things stand

- **Phases 1–5 COMPLETE** (Ableton export + process-output cache deferred
  with recorded rationale). **107 curated entries** on (program, mode,
  submode) keying, 176 uncurated stubs (283 total), 32 tools + 3
  prompts, MIR v2, generalization matrix, cdp://examples/* library.
  Phase 5 record: `docs/phase-5-handoff.md`.
- Suite: 1425 hermetic / 1526 with `CDP_PATH=/tmp/CDP8/NewRelease`
  (rebuild substrate via `scripts/build_cdp8_linux.sh`; run real-CDP
  chunked in-sandbox — see landmine below). Ruff clean.
- User verifies on macOS r8 with `CDP_PATH=... pytest` after each pull
  (expected: one red — filter bank vintage hang, forensics P5-1 — until
  the local `filter` binary is rebuilt).
- **Phase 6 reevaluation DONE (2026-07-15):** `docs/phase-6-design.md`
  rewritten as the active design — all four checklist items resolved
  (gesture-engine curation complete; grain-vs-timeline split decided:
  they compose; stereo seed-link → Phase 6b behind housekeep-chans
  curation + usage trigger; texture owns clouds, timeline() stays
  deterministic placement). timeline() gains headroom staging from
  P5-3 (native getlevel pre-flight, headroom="auto"/"off"/"fail").
  Uncurated-program survey appended to the design doc (sequence2 +
  retime reshaped tranche 11).
- **Tranche 11 DONE (2026-07-15, commits 0f7b1d9 + 910391a +
  integration): 107 → 134 curated / 302 total** (8 stubs retired).
  The Phase 6 primitives are all curated now: extend sequence2
  (duration rule exact: MAX(time + min(indur/2^((pitch−notional)/12),
  dur)); resampling transposition; overload warns-but-writes raw
  floats — NO wrap, unlike submix mix), extend iterate 1/2 + iterline
  1/2 + iterlinef (shared engine, seed 0 = clock, default seed 1;
  fade-brk binary bug; iterlinef needs exactly 25 inputs), shrink 1/4
  (bouncing-ball; -r seedless; -s > indur segfaults), texture
  decorated 5, retime 1/3/4/5/6/7/8/9/10/12 (event = runs bounded by
  LITERAL digital zeros — gate real recordings first; no-silence
  behavior pinned per mode), peakfind↔clicknew round-trip verified,
  sorter 1/5, stutter, housekeep chans 3/4/5 (the 6b SPLIT half;
  merge = submix interleave since repair drops — ignores argv
  outname). Dropped with evidence: refocus (bandcnt floor 2, self-
  named outputs), repair, retime 2/11, shrink 5/6, chans 1/2.
  Duration fixture now writes aux data files for rows that need them
  (_AUX_FILES). Suite: 1621 hermetic / 1735 real-CDP, ruff clean.
  **timeline() design input settled: sequence2 = pitch-aware sibling
  (no pan, no wrap), submix mix = pan-aware (wraps, needs headroom
  staging). Both empirically pinned — the build can decide the routing
  question from data.**
  Phase 6 build queue (error mapping, timeline(), IOI/density,
  Bucephalus example, free_string) is ON HOLD behind the curation
  completion run below.
- **CURATION COMPLETION RUN (tranches 12-23, 6 waves; plan + full
  target lists: docs/curation/roadmap-tranches-12plus.md).** Status:
  - Wave 1 DONE (2026-07-16): T12 submix depth (15) + T13 envelope
    family (19) -> **168 curated / 330 total**. getlevel curable as
    sm3 (timeline() headroom = curated call); gate -> retime chain
    verified; overload map per submix mode; forensics P6-1
    (aarch64 signed-char, build script fixed). Suite 1749/1874.
  - Wave 2 DONE (2026-07-16): T14 sfedit/editing (21) + T15 gesture
    (18) -> **207 curated / 355 total** (14 stubs retired).
    isolate->rejoin contract pinned (round-trip bit-faithful);
    strans stereo-vibrato corruption -> curated as modify speed 6;
    extend freeze pshift/ampcut brk no-op; sorter esiz brk
    version-sensitive. Suite 1958 hermetic / 2107 real-CDP.
  - Wave 3 DONE (2026-07-16): T16 waveset/distort (22) + T17
    synthesis (19) -> **248 curated / 374 total** (22 stubs
    retired). motor duration sample-exact; cascade's advertised
    time-variable params all inert; fracture's real seed flag is
    -S not the banner's -h; impulse chans header-relabel bug;
    distort filter 0-frame trap confirmed. Suite 2251 hermetic /
    2433 real-CDP (a-e/f-m/n-z thirds — the a-m half now exceeds
    the 45 s sandbox call cap).
  - Wave 4 DONE (2026-07-16): T18 texture/filter depth (17) + T19
    grain/FOF (15) -> **280 curated / 402 total**. P5-1 vintage-hang
    scope closed from source (only 'bank' affected); filter iterated
    >1.48 s buffer landmine; nine texture siblings all distinct
    (source-pinned placement); FOF 'material requirement' never
    checked by the binary (garbage-through pinned); grain align
    channel corruption; tweet exclude-file segfault. Suite 2781
    hermetic / 2984 real-CDP (thirds).
  - Wave 5 DONE (2026-07-16): T20 spectral I (26) + T21 spectral II
    (16) -> **322 curated / 424 total** (20 stubs retired). blur
    weave free-string landmine defused (it's a datafile); hilite
    arpeg uninitialized-memory bug (all 8 modes dropped, diagnosed);
    specross outdur = indur2 always; newmorph stagger rules;
    spectwin default renders infile2 VERBATIM; engine fix: explicit
    .ana output_format now wins over domain-derived naming (specanal
    is the cross-domain analyzer — time input, spectral output).
    Suite 2938 hermetic / 3163 real-CDP.
  - Wave 6 DONE (2026-07-16): T22 pitch-data (11) + T23 text
    utilities (5) -> **338 curated / 437 total**. The pitch WORKFLOW
    verified (getpitch -> combineb -> transposef re-sings a wobble
    onto a steady vowel); .frq format pinned; hfchords -> synth
    chord round-trip exact.
  - **RUN COMPLETE: 134 -> 338 curated (+204) across six waves.**
    Remaining 99 stubs = out-of-scope spatial family, toolkit
    plumbing, and defect-dropped programs (all evidenced in
    docs/curation/tranche12..23 findings).
- **PHASE 6 COMPLETE (2026-07-16)** — record:
  `docs/phase-6-handoff.md`. Shipped: timeline() (tool #33, headroom
  staging via curated getlevel; submix-only by decision, sequence2 =
  the pitch-aware sibling); IOI/density rhythm block in segments()
  (accelerando detection, cache v2); search_programs() (tool #34) +
  recommend_transforms prompt (discoverability over 348 entries);
  11-pattern stdout-refusal error mapping; free_string + .frq/.trn
  schema gaps closed (blur/distort shuffle + 8 repitch transforms
  promoted — full curated pitch workflow, no execute() escape).
  **348 curated / 447 total; 34 tools + 4 prompts; suite 3160
  hermetic.** Skipped on user instruction: the Bucephalus example
  recipe (machinery all shipped; first real gesture session makes
  it). Deferred with triggers: mode-token argv gap, Phase 6b stereo
  seed-link, export_to_ableton, process-output cache.
  **THE CURRENT NEXT STEP: real-material usage.** Run the manual
  checklist in the handoff (search quality, recommend_transforms on
  a real sample, a real timeline() gesture); usage evidence drives
  Phase 7 scoping.

## Phase 5 wave 2 — DONE (commits 5715795 + c45b714, 2026-07-15)

All five items below shipped: 78 curated / 260 total; three schema
gaps closed (pre_output, data outputs, arity-0); scramble seed
trigger verified; every known Phase 6 blocker cleared. Suite: 1204
hermetic / 1276 real-CDP (chunked halves in-sandbox).

### The plan as executed (was: not yet started)

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

## Phase 5 wave 3 — DONE (tranche 9, commit 634864e + integration)

12 second/third-submode entries on the (program, mode, submode) keying
(728b986): scramble sm9, filter bank 5/6, morph bridge 2/3, modify
radical 2/5, modify speed 5, envspeak 2, synth wave 2/4, specfnu 2 —
**90 curated / 272 total**, zero drops. Integration folded the findings
into the pinned tables (breakpoint matrix + duration rows now keyed by
triple; loader counts 90/272; pair-shaped lookups that went ambiguous —
synth wave, filter bank — fixed with explicit submodes). Headline finds:
filter bank 5 is GEOMETRIC spacing (not "equal Hz" per SoundThread);
bank vintage hang covers modes 4–6; morph bridge per-mode duration rules
diverge from sm1. Suite: 1301 hermetic / 1383 real-CDP (chunked halves
in-sandbox), ruff clean.

## Phase 5 wave 4 — DONE (tranche 10, commits e79e829 + 6d9f22a + integration)

The remaining ST-covered singles, split across two parallel curation
agents (10a spectral / 10b time-domain): 17 new entries — blur chorus 5,
blur noise, focus focus, spec cut/gain, spectstr stretch, strange
waver 1, extend baktobak, housekeep extract 4, modify sausage,
multiosc 3, phase 1/2, repitch transpose 3, sfedit excise 1 + join,
synspline — **107 curated / 283 total** (6 program stubs retired).
Headline finds: blur chorus is DETERMINISTIC (no initrand48, ap_blur.c);
synspline seed 0 is the clock path (ST's default slider value renders
irreproducibly); baktobak discards pre-join audio (not ST's whole-file
prepend); sausage clock-seeded unseedable, min(indurs)/velocity, always
stereo; spectstr usage banner's 'time' token is a CDP typo the binary
rejects. **blur shuffle dropped — engine gap**: required positional free
string (domain-image map, tklib3.c:646) that processing.py's param
typing can't express; duration rule pinned in the 10a transcript;
execute()-reachable. Candidate for the Phase 6 reevaluation list.
Suite: 1415 hermetic / 1511 real-CDP (chunked halves), ruff clean.

## Phase 5 close-out — DONE (2026-07-15)

- Generalization matrix shipped (`89f0dc7`): four proxies, four chains,
  three non-generalization findings pinned (grain
  acceptance-with-truncation; envspeak accepts swells; drift scales
  with articulation). Real material + listening remain the user's half
  (handoff checklist items 2–3).
- Examples library shipped (`f0a525d`): six cdp://examples/* recipes,
  list_examples() (tool #32), read_doc namespace dispatch, every
  definition dry-run in CI. No wav files needed or added.
- Handoff + README bump shipped (`08a768f`).
- Wave-2 bug finds promoted to forensics P5-2/3/4 (newdelay feedback ±1
  hang; submix mix overload WRAP + -g valve/-a no-op; quirk unipolar
  zero-frame silent success) — the user-queued item, cleared.

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

- Binary-vintage landmine (2026-07-15, forensics P5-1): `filter bank`
  on binaries older than CDP8 fix `11cdcb4` (2025-06-05) does an OOB
  heap write every run — the user's macOS r8 binary HANGS (the one red
  test in the 2026-07-15 local run, 1275/1276). Entry now
  `version_sensitive: true` with a known_issues lead; remedy = rebuild
  `filter` from current CDP8 source. Linux substrate is post-fix and
  green. The duration row stays: correct vs fixed binaries, and it
  doubles as the vintage detector.
