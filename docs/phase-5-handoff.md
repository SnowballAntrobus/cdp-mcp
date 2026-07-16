# Phase 5 handoff — knowledge depth (2026-07-15)

> Companion records: `docs/curation/tranche{5..10}*` (probe transcripts +
> findings JSONs), `docs/generalization-matrix.md`, `docs/forensics.md`
> §P5, `docs/mir-gap-analysis.md`, and the git log `9160225..HEAD` —
> every commit message is a work record. Preliminary Phase 6 design
> (written pre-Phase-5) is `docs/phase-6-design.md`; its reevaluation
> checklist is now live.

## What Phase 5 was

Phase 4 left a polished workflow around a thin knowledge base: 43
curated entries, whole families missing (grain, repitch, synthesis,
texture depth), and every empirical claim tested on noise/tone
fixtures only. Phase 5 was the depth phase: curation 43 → **107
entries** (283 total with the 176-stub long tail), the engine schema
gaps that curation flushed out, MIR v2, a generalization matrix over
four material classes, and a packaged examples library.

## Curation: six tranches, 43 → 107

- **Wave 1 (tranches 5–6, `9160225`):** mix/envelope family + grain/
  pitch family, 18 entries, 43 → 61. Flushed out both engine schema
  gaps (below). Tranche-6 seed hunt methodology established.
- **Wave 2a (tranche 7, `5715795`):** three engine schema gaps closed —
  `pre_output` aux-file positioning (mixfile renders before the output
  argv slot), data-file OUTPUT kinds, and arity-0 generators (
  `input_arity: 0`, resolve/preflight with no inputs) — then the six
  entries those gaps had blocked (submix mix, formants put/get, envel
  extract, synth noise/wave), 61 → 67.
- **Wave 2b (tranche 8, `c45b714`):** the seed-trigger singles —
  scramble sm10, envspeak, morph bridge, distort reform/delete/replace,
  analjoin, newdelay, quirk, silend, 67 → 78.
- **Wave 3 (tranche 9, `634864e` + `9cbb0c6`):** `(program, mode,
  submode)` triple keying (`728b986`) unlocked second submodes of
  already-curated pairs: scramble sm9, filter bank 5/6, morph bridge
  2/3, modify radical 2/5, modify speed 5, envspeak 2, synth wave 2/4,
  specfnu 2 — 78 → 90. Headline: filter bank 5 is GEOMETRIC spacing
  (SoundThread says "equal Hz"); morph bridge's per-mode duration rules
  diverge from sm1.
- **Wave 4 (tranche 10 a+b, `e79e829` + `6d9f22a` + `ba70480`):** the
  remaining SoundThread-covered singles, split across two parallel
  curation agents, 90 → 107. Headlines: blur chorus is deterministic
  (no RNG seeding — same construction as distort reform 6); synspline
  seed 0 is the CLOCK path and SoundThread defaults its slider there;
  baktobak discards pre-join audio; sausage is clock-seeded and
  unseedable with duration `min(indurs)/velocity`; six first-curated
  programs retired their long-tail stubs.
- **Drops with recorded evidence** (findings JSONs `dropped[]`): blur
  shuffle (engine gap: required positional free-string param,
  `tklib3.c:646` — `processing.py` param typing can't express it;
  duration rule pinned in the 10a transcript; `execute()`-reachable),
  housekeep extract 1 (multi-output with no outfile argv, silent
  name-collision skips), blur chorus modes 1–4/6–7 (run fine,
  unprioritized), and the tranche-5/6 records preceding the schema
  fixes.

Standing conventions held throughout: methodology per
`docs/curation/tranche2_timedomain.md` verbatim; binaries decide →
source explains → manual describes → SoundThread + afta8 prioritize;
curation agents never touch `tests/`/`server.py`; the integrator folds
findings into the pinned tables (breakpoint matrix, duration rows,
counts, category/domain pins) and runs the suite both ways.

## MIR v2 (`7b7564e`, gap analysis `78d9eb4`)

`analyze(verbose)` now returns a 13-field scorecard with trajectory
blocks; `cluster()` uses a 33-dim vector. Fields were chosen against
the curated musical vocabulary (the gap analysis documents which
curated adjectives had no measurable correlate before v2).

## Generalization matrix (`89f0dc7`)

Four seeded-numpy proxies — clarinet-ish sustain, drifting
field-recording bed, percussive one-shot, 4-syllable vocal proxy — each
through a 4-op curated chain (spectral + time-domain + extend/edit,
auto-PVOC crossings both directions), duration models checked through
the real preflight evaluator at every step. All four chains green.
`test_material_sensitivity` pins what did NOT generalize:

1. **Grain gating has a third outcome: acceptance-with-truncation.**
   On weakly-articulated beds the 0.3 gate segments the continuous bed
   into pseudo-grains and silently DISCARDS below-gate material (−23%
   vs the static duration model). The static model only holds when
   silence is actually silent.
2. **envspeak accepts swells** despite the curated "steady tones are
   refused" claim — a swell is one "syllable"; output exactly
   `indur × repet`.
3. Grain-op static-model drift scales with articulation density
   (−1.3% click trains → −3.4% syllabic proxy).

Real recorded material + listening remain the human half; the chains
are ready in `tests/test_generalization.py` and as examples.

## Examples library (`f0a525d`)

Six package-shipped `cdp://examples/*` recipes — ready-to-run `graph()`
definitions with musical intent, target material, landmine notes, and
provenance. Every chain executed against real CDP before shipping (the
acceptance chain, the four generalization chains, a tranche-10
showcase). `list_examples()` (tool #32) lists; `read_doc()` gained
`cdp://` namespace dispatch and serves examples even with no CDP manual
installed. Hermetic tests dry-run every shipped definition through the
real `graph()` validation path, so a drifted example fails in CI.

## Suite

**1425 hermetic / 1526 with `CDP_PATH`** (run the real-CDP suite in
chunked halves inside the sandbox — the full single-process run stalls
near the end there; a real machine runs it whole). Ruff clean. The
macOS r8 QA expectation: one known red — filter bank's binary-vintage
hang (forensics P5-1) until the local `filter` binary is rebuilt from
current CDP8 source.

## Open items → Phase 6 reevaluation

The Phase 6 design (`docs/phase-6-design.md`, gesture construction:
`timeline()` on submix mixfiles, grid-free IOI/density analysis,
micro/macro boundary) was written before Phase 5; its reevaluation
checklist should now be walked with these additions:

- **blur shuffle's free-string positional param** — smallest schema
  gap left standing; also the only drop whose duration rule is already
  pinned.
- **Channel machinery trigger** — scramble's stereo seed-link
  (tranche 6) plus phase 2 / sausage stereo behaviors from wave 4.
- **grain rerhythm/reposition vs `timeline()`** — the standing overlap
  question at the design doc's end.
- **Error-mapping improvement** (generalization find): CDP refusals
  like `No grains found` surface only in stdout; `errors[]` is a
  generic exit-255 `subprocess_error` with `fix: None`.
- Deferred with rationale, unchanged: `export_to_ableton`,
  process-output cache (sample-equivalence keying), Phase 2/3
  leftovers listed in `docs/phase-3-handoff.md`.

## Manual-test checklist (real CDP, your machine)

1. `CDP_PATH=... pytest` — expect green except the filter-bank vintage
   hang if your `filter` predates CDP8 `11cdcb4` (rebuild to clear).
2. `list_examples()` → `read_doc("cdp://examples/pitched_vibrato_warp")`
   → run the definition through `graph(dry_run=True)` on a real
   clarinet/wind sample, then execute and listen — this is the human
   half of the generalization matrix.
3. `grain reverse` on a real field recording — listen for the
   truncation finding (output noticeably shorter than input when the
   bed never fully silences).
4. `synspline` twice with seed 1 (identical) and seed 0 twice
   (different — clock path).
5. `submix mix` with a deliberate overload: confirm `getlevel`'s
   factor via `execute()`, render with `atten`, listen for wrap
   artifacts absent.
