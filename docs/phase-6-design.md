# Phase 6 — Gesture Construction (PRELIMINARY design, pre-Phase-5)

> Status: **draft, deliberately written before Phase 5** and to be
> reevaluated after it — the Phase 5 curation expansion sweeps through the
> exact program families this phase builds on (`submix`, `envel`,
> `formants`, `grain`, `texture`), and their empirical findings should
> shape the design rather than the reverse. Recorded 2026-07-15 from the
> beat/tempo design discussion (Bucephalus Bouncing Ball as the reference
> aesthetic: constructed, evolving, non-repeating rhythm; per-event-unique
> sound design; instruments influencing each other's tone).

## The boundary commitment (micro vs macro)

**Gesture construction belongs in cdp-mcp; track arrangement stays in the
DAW.** A six-second accelerando of forty unique bounces is a *sound
object* in the Wishart sense — composed offline, auditioned with
`compare()`, tagged, exported as one wav. Sections, layering, automation,
mastering remain Ableton's job; the design doc's "not a general DAW"
non-goal stands unamended.

## Detection vs construction (the beat-machinery ruling, refined)

- **Grid-based detection machinery stays out**: beat tracking, meter
  induction, tempo curves answer "what grid is this music on?" — the
  material here has no grid to find, and confident-looking garbage is
  worse than no data (the existing verbose `tempo_bpm` is already the
  weakest field). Unchanged from the MIR gap analysis.
- **Grid-free event-timing analysis comes in**: once rhythm is
  *constructed*, the agent must verify it. Inter-onset-interval
  statistics (mean/std/min/max/slope — IOI slope is an accelerando
  detector) and a 16-point event-density trajectory, built on
  `segments()`'s existing onset machinery. This corrects a scope miss in
  the MIR report (its vocabulary sample skewed timbral).

## Planned components (all contingent on Phase 5 findings)

1. **Curate the gesture engine**: `submix mix` (CDP's mixfile — a text
   file of per-event `soundfile time [level] [pan…]` lines — is an
   offline micro-arranger and an `aux_file` parameter, the plumbing
   Phase 4 built). Empirical musts before any tool code: exact mixfile
   line syntax mono/stereo, path resolution relative to cwd=session
   root, SR-mismatch behavior, overlap/summing headroom, output-duration
   rule. Also `envel impose`/`extract` (envelope transfer — the offline
   sidechain: percussive material gating/ducking pads = "instruments
   affecting each other's tone") and `formants vocode` (spectral
   imposition). Phase 5 may curate these en route — check before
   duplicating.
2. **`timeline()` tool**: events `[{source, at, level?, pan?}]` →
   validate refs (full grammar incl. `latest_batch[i]`) + SR/channel
   compatibility → write mixfile via the data-file machinery → execute
   through `validate_node`/`execute_validated_node` with the `submix
   mix` entry (inheriting security, watchdog, lineage). Duration
   pre-flight computed by the tool as max(at + source_duration) — the
   entry's duration model cannot know the events. One call = one
   composed gesture; per-event compact report.
3. **The Bucephalus pipeline** (workflow, no new machinery beyond the
   above): `sweep()` an impact across N variants (each bounce unique) →
   agent computes bounce times (geometric series; the LLM is good at
   arithmetic) → `timeline()` renders the gesture → `segments()` + IOI
   verifies the accelerando → `analyze()` trajectory confirms the decay.
4. **Grid-free rhythm analysis**: IOI block + density trajectory into
   `segments()` (cache key bump).

## Non-goals (with reactivation triggers)

- **Pattern-generator tool** (euclidean/bounce-curve/jitter
  constructors): the LLM computes event-time lists unaided; a
  constructor is sugar. Reactivation trigger: usage evidence of the
  agent repeatedly hand-building the same pattern families token-
  expensively — the exact evidence pattern that reversed the sweep()
  non-goal.
- **Live/streaming interaction**: CDP is offline; "instruments affecting
  each other" is realized as offline envelope-transfer and
  cross-synthesis, not sidechains.

## Reevaluation checklist after Phase 5

- Did Phase 5 curate submix/envel/formants/grain? Fold findings in here.
- Do `grain rerhythm`/`grain reposition` cover part of timeline()'s job
  natively (within-file event re-timing vs multi-source placement)?
  Decide the split.
- Did a seeded mono stochastic entry land (grain family is the
  candidate)? If yes the stereo seed-linking machinery has its consumer
  and may belong in Phase 6 alongside gesture work.
- Does texture (more modes) reduce what timeline() must do for cloud-like
  material?
