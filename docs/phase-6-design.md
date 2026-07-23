# Phase 6 — Gesture Construction (REEVALUATED post-Phase-5, 2026-07-15)

> Status: **active design.** First recorded 2026-07-15 pre-Phase-5 (from
> the beat/tempo design discussion; Bucephalus Bouncing Ball as the
> reference aesthetic: constructed, evolving, non-repeating rhythm;
> per-event-unique sound design; instruments influencing each other's
> tone). Reevaluated the same day after Phase 5 closed — the curation
> sweep hit every program family this phase builds on, and every
> "empirical must" the preliminary draft listed is now answered. The
> checklist walk and its verdicts are §Reevaluation below; the
> preliminary draft's text is superseded by this revision (git history
> holds it).

## The boundary commitment (micro vs macro) — UNCHANGED

**Gesture construction belongs in cdp-mcp; track arrangement stays in
the DAW.** A six-second accelerando of forty unique bounces is a *sound
object* in the Wishart sense — composed offline, auditioned with
`compare()`, tagged, exported as one wav. Sections, layering,
automation, mastering remain Ableton's job; the design doc's "not a
general DAW" non-goal stands unamended.

## Detection vs construction (the beat-machinery ruling) — UNCHANGED

Grid-based detection machinery (beat tracking, meter induction, tempo
curves) stays out; grid-free event-timing analysis (IOI statistics +
event-density trajectory on `segments()`'s onset machinery) comes in.
The Phase 5 generalization matrix strengthened the case: the onset
machinery held across all four material classes, including the
adversarial drifting-bed proxy.

## Reevaluation — the four checklist items, resolved

1. **Did Phase 5 curate submix/envel/formants/grain?** All of them.
   submix mix (arity-0, `pre_output` mixfile, tranche 7), submix
   interleave, envel impose/extract/replace/dovetail, formants
   get/put/vocode, and five grain entries (duplicate, timewarp,
   reverse, rerhythm sm1, reposition — the latter two with aux
   timefiles). **Component 1 of the preliminary draft ("curate the
   gesture engine") is DONE and drops out of Phase 6 scope.** Every
   empirical must for `timeline()` is answered: mixfile line syntax
   verified mono/stereo, cwd-relative path resolution confirmed,
   output-duration rule `max(at+dur) − min(at)` probe-verified, and
   the overlap/summing question closed emphatically by forensics P5-3
   (overload WRAPS; `submix getlevel 1` is the native pre-flight; `-g`
   attenuates pre-quantisation, `-a` is a no-op).
2. **grain rerhythm/reposition vs timeline() — the split:** they don't
   compete, they compose. The grain pair re-times amplitude-gated
   events *within one file* (single source, aux timefile, subject to
   the gate constraints — including the generalization matrix's
   acceptance-with-truncation landmine on weakly-articulated material).
   `timeline()` places *multiple sources* at explicit times with
   levels/pans — cross-source, silence-tolerant, gate-free. Idiomatic
   combination: `sweep()` makes N variants → `timeline()` places them →
   `grain rerhythm` micro-times a placed layer afterwards. Both stay;
   no machinery overlaps.
3. **Seeded mono stochastic consumer for stereo seed-linking:** landed
   several times over (scramble sm9/sm10 — mono-only, positional seed;
   texture simple/grouped `-r` seed; extend scramble seed). The
   dual-mono seed-link machinery (split stereo → same seed per channel
   → merge, preserving the image) now has real consumers — **but its
   prerequisite is uncurated**: `housekeep chans` (the channel
   splitter/merger). Verdict: **Phase 6b, contingent** — curate
   housekeep chans in a small tranche 11 first; build the seed-link
   wiring only after a real gesture session actually hits a mono-only
   stochastic op with stereo material. Not on the critical path.
4. **Does texture depth reduce timeline()'s job?** Yes, by subtraction:
   statistical cloud material (many events, density-specified, not
   individually authored) is texture simple/grouped's native job —
   note-data driven, seeded, already curated. `timeline()` therefore
   stays a strictly *deterministic placement* tool: explicit events,
   no density parameters, no stochastic generation. (texture decorated
   didn't land in Phase 5 — fine; not a Phase 6 dependency, candidate
   for tranche 11.)

## Planned components (revised)

1. **`timeline()` tool** — the core build. Events
   `[{source, at, level?, pan?}]` → validate refs (full grammar incl.
   `latest_batch[i]`) + SR/channel compatibility → write mixfile via
   the data-file machinery → execute through `validate_node` /
   `execute_validated_node` with the `submix mix` entry (inheriting
   security, watchdog, lineage). Duration pre-flight computed by the
   tool as `max(at + source_duration) − min(at)` — the entry's model
   deliberately can't know the events (its expression references the
   mixfile so the preflight guard skips; watchdog covers).
   **New since the draft — headroom staging (P5-3):** validation runs
   `submix getlevel 1` on the written mixfile natively; if the
   normalisation factor is < 1, default behavior `headroom="auto"`
   applies it as `-g` and reports the factor in the result;
   `headroom="off"` renders raw (wraps — the report says so);
   `headroom="fail"` returns a structured error carrying the factor.
   One call = one composed gesture; per-event compact report.
2. **Grid-free rhythm analysis**: IOI block
   (mean/std/min/max/slope — slope is the accelerando detector) + a
   16-point event-density trajectory into `segments()` (cache key
   bump). Unchanged from the draft.
3. **The Bucephalus pipeline** (workflow validation, no new machinery):
   `sweep()` an impact across N variants → agent computes bounce times
   (geometric series) → `timeline()` renders → `segments()` + IOI
   verifies the accelerando → `analyze()` trajectory confirms the
   decay. Ship the result as a `cdp://examples/*` recipe once it runs.
4. **Engine hygiene, folded in from the Phase 5 open items:**
   a. **stdout-refusal error mapping** — CDP refusals ("No grains
      found", "must be mono/stereo", "NO CHANGE to original sound
      file.", "Insufficient parameters") currently surface as generic
      exit-255 `subprocess_error` with `fix: None`; map the known
      pattern table to structured errors with fixes. Cheap, and
      load-bearing for gesture pipelines where sweep-variant refusals
      must be legible. Do this FIRST — it pays off across everything
      else.
   b. **`free_string` positional param type** — the one schema gap
      Phase 5 left standing (blur shuffle's domain-image map,
      `tklib3.c:646`). Duration rule already pinned in the tranche-10a
      transcript; entry promotion is mechanical once the type exists.
      Low priority, high certainty.
5. **Phase 6b (contingent, not critical path):** tranche 11 mini-sweep
   (see the survey below), and the stereo seed-link dual-mono machinery
   behind its usage trigger (item 3 above). **Trigger INSTRUMENTED
   (2026-07-16):** validation now trips a structured
   `stereo_seed_link_missing` error when a mono-only seeded entry
   receives stereo material — the fix text tells the agent to notify
   the user (each report is the usage evidence) and carries the
   manual split/same-seed/merge workaround.

## Uncurated-program survey for Phase 6 (2026-07-15, banner-level)

A pass over the 176 uncurated stubs plus the uncurated MODES of curated
binaries (invisible to the stub list — the stub generator only covers
programs with no curated entry). Banner-verified against the sandbox
binaries; no probing yet.

**Two finds that bear on the timeline() design itself:**

- **`extend sequence2`** — multi-source score renderer: a sequence file
  of `(input-sound-number, output-time, midi-pitch, loudness, duration)`
  rows over N inputs. This is a *pitch-aware* timeline with no pan;
  `submix mix` is *pan-aware* with no pitch. Decide during the
  timeline() build: either timeline() stays submix-only (pan, no
  pitch) and sequence2 is curated as the sibling for pitch-bearing
  event lists, or timeline() grows a per-event `pitch?` field and
  routes to sequence2 when any event carries one. Either way sequence2
  is tranche-11 priority #1.
- **`retime`** — a 12-mode event-timing suite on silence-separated
  events: position at specified times/beats (modes 6/7 — within-file
  timeline), regularize to a tempo (1/4), speed-change events (5),
  accent-level events (10), silence-pattern events (9). Covers the
  within-file half of the grain/timeline split with much less gate
  sensitivity than the grain family (silence-separated, not
  amplitude-gated). Priority #2.

**Tranche-11 candidates, gesture-relevant (curation order):**

1. `extend sequence2` (+ `extend iterate` — seeded per-event-unique
   repetition, and `iterline`/`iterlinef` — iteration along a
   transposition line; the Bucephalus per-event-evolution primitives).
2. `retime` (the event-timing modes: 1, 4–7, 9, 10).
3. `shrink` — repeat-while-shortening (modes 1–3 gap-contraction):
   the bouncing-ball accelerando as a single native op.
4. `peakfind` (peak times → textfile) + `clicknew` (textfile →
   clicktrack): timefile glue between analysis and the grain
   reposition/rerhythm aux inputs, plus audible verification of
   constructed rhythm.
5. `sorter` (chop to elements, reorder by loudness/duration/random
   with seed) + `stutter` (seeded slice-and-stutter with silences) —
   event-level reorganizers.
6. `refocus` — generates per-source envelope sets that bring each
   sound into focus in turn pre-mix ("instruments affecting each
   other's tone" at gesture scale; composes with timeline()).
7. Channel machinery for Phase 6b: `housekeep chans` (split; modes
   1–5 confirmed) + `repair` (join N mono → stereo/multi) — split and
   merge for the seed-link wiring.
8. Previously queued: texture decorated retry, blur shuffle promotion.

**Second tier (pattern-render engines, banner-plausible, defer until a
gesture session wants them):** `motor` (nested pulse-streams, seeded),
`ceracu` (polyrhythmic resync cyclestreams), `splinter`
(repeat-and-shrink waveset splinters), `tesselate`, `madrid`,
`crumble`/`cascade`, `repeater`, `freeze`, `sfecho`, `flatten`,
`isolate`/`rejoin`, `grainex`. These don't violate the
pattern-generator non-goal — they're render engines, not event-list
constructors; the LLM still authors the numbers.

**Out of Phase 6 scope:** the multichannel spatial family (mchanpan,
mchstereo, panorama, tangent, transit, spin, flutter, wrappage,
texmchan, mchiter — arrangement/spatialization is the DAW's side of
the boundary), the synthesis long tail (newsynth, multisynth, chirikov,
fractal, ts...), and the spectral long tail (specross, spectwin,
superaccu... — Phase 7+ material).

## Non-goals (with reactivation triggers) — UNCHANGED

- **Pattern-generator tool** (euclidean/bounce-curve/jitter
  constructors): the LLM computes event-time lists unaided; a
  constructor is sugar. Reactivation trigger: usage evidence of the
  agent repeatedly hand-building the same pattern families
  token-expensively — the exact evidence pattern that reversed the
  sweep() non-goal.
- **Live/streaming interaction**: CDP is offline; "instruments
  affecting each other" is realized as offline envelope-transfer
  (envel impose/extract — curated) and cross-synthesis (formants
  vocode — curated), not sidechains.

## Post-run recheck (2026-07-16, after tranches 12–23)

The curation completion run (134 → 338 entries) counts as Phase 6's
curation half. Design consequences:

- **timeline() routing DECIDED: v1 is submix-only.** Pitch-bearing
  event lists route to `extend sequence2` directly (curated, no-wrap,
  resampling transposition) — timeline()'s docstring says so rather
  than auto-routing; the semantics differ enough (wrap behavior,
  duration rules) that silent routing would surprise.
- **Headroom staging simplified**: `submix getlevel 3` is now a
  CURATED data-output entry — timeline()'s pre-flight runs it through
  the normal engine path, no internal escape hatch needed. Factor is
  1/peak unconditionally (>1 = headroom, not a warning).
- **The gate → retime chain is curated end-to-end** (tranche 13), so
  grid-free rhythm work on real recordings has its upstream fix.
- **Error mapping's pattern table tripled in value**: the run recorded
  dozens of verbatim stdout refusals across 12 tranches — the mapping
  work now has an evidence corpus, not guesses.
- **Two NEW schema gaps join free_string** (both fully evidenced):
  `.frq`/`.trn` output kinds (the 15-program pitch-transform layer is
  verified working and execute()-reachable but schema-blocked) and the
  mode-token argv gap (columns/tabedit family — DEFERRED, usage
  trigger: a gesture session actually wanting native time-list
  generators; the LLM computes these unaided today).
- **NEW DELIVERABLE — discoverability.** At 43 entries an agent could
  eyeball list_programs; at 338 it cannot. Today nothing searches the
  curated knowledge itself (search_docs covers only the CDP manual,
  which describes but doesn't prioritize, and covers uncurated
  programs indiscriminately). Shipping: `search_programs()` — FTS over
  the curated entries' description/musical_use/notes/category fields,
  ranked, with category/domain filters — plus a `recommend_transforms`
  workflow prompt encoding the sample-driven path (analyze() MIR
  scorecard → material class per the generalization matrix → targeted
  search_programs queries → constraint check against known_issues/
  channel/articulation limits → sweep()/batch() auditions →
  compare()). Examples library remains the chain-level entry point.

## Build order

1. Error mapping (4a) — small, immediate, de-risks everything after.
2. `timeline()` (1) with headroom staging; hermetic tests against the
   submix mix entry's argv shape + real-CDP acceptance on the sandbox
   substrate.
3. IOI/density into `segments()` (2).
4. Bucephalus pipeline end-to-end + example recipe (3).
5. `free_string` type + blur shuffle promotion (4b) when convenient.
6. Phase 6b items behind their triggers.
