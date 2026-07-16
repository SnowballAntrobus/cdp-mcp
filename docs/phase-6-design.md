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
   (housekeep chans, texture decorated retry, blur shuffle promotion
   after 4b) and the stereo seed-link dual-mono machinery behind its
   usage trigger (item 3 above).

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

## Build order

1. Error mapping (4a) — small, immediate, de-risks everything after.
2. `timeline()` (1) with headroom staging; hermetic tests against the
   submix mix entry's argv shape + real-CDP acceptance on the sandbox
   substrate.
3. IOI/density into `segments()` (2).
4. Bucephalus pipeline end-to-end + example recipe (3).
5. `free_string` type + blur shuffle promotion (4b) when convenient.
6. Phase 6b items behind their triggers.
