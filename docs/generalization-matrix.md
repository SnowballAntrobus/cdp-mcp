# Phase 5 generalization matrix

The curated knowledge base (107 entries) was probed almost entirely on
synthetic noise/tone fixtures. This matrix (`tests/test_generalization.py`,
CDP-gated) verifies the acceptance machinery — `process` chaining,
auto-PVOC boundary insertion, curated `duration_model`s, lineage — against
four musically distinct material classes, each a deterministic seeded numpy
synthesis (no wav files in the repo). Real recorded material + listening is
the human half of Phase 5; this is the machine half. **The negative
findings in the last section are the point of the exercise.**

## The four proxies

| Proxy | Stands in for | Synthesis recipe |
|---|---|---|
| clarinet-ish | sustained pitched instrument | D4 (147 Hz), odd-harmonic-dominant partials (1,3,5,7,9 at 1/k, trace evens), 5 Hz / 0.4% vibrato, 150 ms soft attack, 300 ms release, faint breath noise; 2.5 s |
| field recording | broadband environmental bed | one-pole-lowpassed noise bed, 0.23 Hz amplitude drift (0.2–0.9), three sparse decaying sine-burst transients (1.8/0.9/2.6 kHz), 50 Hz hum at −30 dB-ish; 3.0 s |
| synth one-shot | percussive electronic hit | 900→70 Hz exponential pitch sweep, 120 ms decay body, 8 ms bright noise-click attack; 0.7 s |
| vocal phrase | syllabic voice-like phrase | pulse train, 150→115 Hz falling contour + 4.5 Hz jitter, through three two-pole formant resonators (650/1100/2500 Hz), 4-syllable envelope with real inter-syllable silence; 2.5 s |

## The four chains

Each chain: 3–5 curated ops, spectral + time-domain + extend/edit families,
`input="latest"` chaining, ≥1 wav→spectral (auto-PVOC anal) and ≥1
.ana→time (auto-PVOC synth) crossing.

**Clarinet** — the pitch ops finally get real pitch to act on:
`repitch transpose 3` (+12 st; formants move too) → `strange waver 1`
(vibfrq 4, stretch 2, botfrq 100 — harmonicity vibrato needs a harmonic
spectrum) → `modify speed 2` (−12 st varispeed, .ana→time crossing) →
`envel dovetail 1` (0.1 s in / 0.5 s out, exponential).

**Field** — filters and spectral averaging on non-stationary broadband:
`filter sweeping 2` (150–5000 Hz, sweepfrq 1/6 = one cycle over 3 s,
tail 0.5) → `blur blur` (blurring 10) → `modify brassage 2` (velocity 0.5,
granular half-speed, .ana→time) → `extend scramble 1` (seg 0.1–0.3 s,
outdur 4, **seed 7** — pins the otherwise clock-seeded chunk sequence).

**One-shot** — the short-gesture extend ops on the material they were
built for: `bounce` (count 5, startgap 0.35, shorten 0.75 — accelerating
die-away) → `stretch time 1` (2.5×; short input = worst-case analysis
padding) → `extend loop 3` (cnt 4, len 400 ms, .ana→time) →
`sfedit cut 1` (0.2–1.2 s).

**Vocal** — the onset/formant-sensitive ops that refuse unarticulated
material: `grain reverse` (amplitude-gated syllable retrograde) →
`specfnu 1` (narrow 4 — formant-aware, designed for voice) →
`modify loudness 1` (gain 0.8, .ana→time) → `envspeak 1` (wsize 50 ms,
repet 2, rand 0 — syllable stutter, deterministic only at rand 0).

## Results (Linux sandbox build, CDP_PATH=/tmp/CDP8/NewRelease; 5 tests, ~1.8 s total)

| Chain / step | predicted (s) | measured (s) | note |
|---|---|---|---|
| clarinet: repitch transpose 3 | 2.500 (static) | 2.522 | +0.9% analysis padding |
| clarinet: strange waver 1 | 2.522 | 2.522 | exact |
| clarinet: modify speed 2 | 5.045 | 5.044 | exact |
| clarinet: envel dovetail 1 | 5.044 (static) | 5.044 | exact |
| field: filter sweeping 2 | 3.500 | 3.500 | exact |
| field: blur blur | 3.500 (static) | 3.498 | exact |
| field: modify brassage 2 | 6.995 | 6.932–6.936 | −0.9%; wobbles run-to-run (unseeded grains), duration stable to ±0.1% |
| field: extend scramble 1 | 4.0 (set_by) | 4.038 | documented overrun ≤ ~1 chunk; asserted as range, not rel_tol |
| one-shot: bounce | 1.234 | 1.234 | geometric-series formula exact |
| one-shot: stretch time 1 | 3.085 | 3.146 | +2.0% — padding proportionally largest on short input |
| one-shot: extend loop 3 | 1.600 | 1.600 | exact |
| one-shot: sfedit cut 1 | 1.000 | 1.000 | exact |
| vocal: grain reverse | 2.500 (static) | 2.415 | **−3.4%**, see findings |
| vocal: specfnu 1 | 2.415 (static) | 2.438 | +1.0% padding |
| vocal: modify loudness 1 | 2.438 (static) | 2.438 | exact |
| vocal: envspeak 1 (repet 2) | 4.876 | 4.876 | indur × repet exact |

All four chains pass deterministically (repeat runs byte-stable on all
duration assertions; brassage bytes vary, durations don't).

## What did NOT generalize (pinned in `test_material_sensitivity`)

1. **Grain gating on a drifting bed: acceptance-with-truncation, not
   refusal.** The curation-era expectation was binary — articulated
   material passes, flat noise refuses ("No grains found"). The field
   proxy found the third outcome: its slow amplitude drift dips below the
   0.3 default gate, so `grain reverse` segments the *continuous* bed into
   pseudo-grains, runs cleanly, and silently **discards the below-gate
   material — output 2.307 s from a 3.0 s input (−23%)** where the static
   duration model predicts ~3.0. The model holds only for material whose
   silence is actually silent. Weakly-articulated real field recordings
   are exactly this case.
2. **envspeak's "steady tones are refused" claim doesn't cover swells.**
   The clarinet proxy (steady mid-file, but soft attack/release) is
   accepted: the whole swell counts as one "syllable" and the output is
   exactly indur × repet (5.000 s). The refusal only fires for envelopes
   with *no* troughs at all; any onset/offset makes it a one-syllable
   file. Entry-description nuance worth knowing before pointing envspeak
   at pads.
3. **Grain-reverse static-model drift scales with articulation.** Entry
   documents −1.3% on sparse click trains; the 4-syllable vocal proxy
   measures −3.4% (gating/splice loss accrues per grain boundary). Still
   inside a 5% tolerance but the trend means densely-syllabic real speech
   could exceed it — the matrix pins this step at rel 0.08.
4. **Refusal diagnostics live in `stdout`, not `errors`.** Grain
   refusals surface as a generic `subprocess_error` ("CDP exited with code
   255", fix: None); the actionable "ERROR: No grains found." is only in
   the `stdout` field. An LLM driving `process()` gets a usable hint only
   if it reads stdout — candidate for a future error-mapping improvement.

Everything else generalized cleanly: refusals fired exactly as curated on
the sustained tone and the single-grain one-shot; both auto-PVOC crossing
directions worked in all four chains; every other duration model held
within 2% on material classes it was never probed on.
