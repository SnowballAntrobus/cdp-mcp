# Tranche 2 — time-domain curation probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (built from ComposersDesktop/CDP8 source; banners
  self-report "CDP Release 7.1 2016"), Linux x86_64 sandbox.
- **Note:** these outcomes are re-verified on macOS r8 by the CDP-gated suite
  (`tests/test_curation_formulas.py` and `tests/test_breakpoint_curation.py`) after the
  findings rows are integrated.
- **Inputs:** synthesized in `/tmp/probe` via python-soundfile — mono 44100 Hz float32
  enveloped noise bursts `n1` (1.0 s), `n2` (2.0 s), `n3` (3.0 s); 440 Hz sine tones
  `tone1` (1.0 s), `tone2` (2.0 s); stereo noise `st2` (2.0 s). Noise carries a 50 ms
  edge ramp plus a slow amplitude envelope so waveset programs have level and
  zero-crossings to chew on.
- **Methodology:** replicates `docs/curation/tranche1_timedomain.md` /
  `docs/phase-2-breakpoint-review.md`. Breakpoint probes use a 2-line file
  `0.0 <lo>\n2.0 <hi>` substituted at the parameter's argv position (or `-X<file>`
  attached for flags). Determinism compares sha256 of **decoded samples** (soundfile,
  float64), never raw bytes; unseeded pairs are launched > 1.1 s apart (clock-seed
  collision trap).

Refusal errors quoted below are verbatim from the binary (emitted to stdout with exit 255).

---

## 1. modify revecho, submode 2 (VARYING DELAY)

Working argv: `modify revecho 2 n2.wav out.wav 250 0.5 0.5 0.3 1.0 0 0 1.0` — exit 0
(positionals: delay mix feedback lfomod lfofreq lfophase lfodelay tail).

| input | indur | delay (ms) | feedback | tail | outdur | predicted `indur + tail` |
| ----- | ----- | ---------- | -------- | ---- | ------ | ------------------------ |
| n2 | 2.0 | 250 | 0.5 | 0.5 | 2.5000 | 2.5 |
| n2 | 2.0 | 250 | 0.5 | 1.0 | 3.0000 | 3.0 |
| n2 | 2.0 | 250 | 0.5 | 0   | 2.0000 | 2.0 |
| n1 | 1.0 | 250 | 0.5 | 0.5 | 1.5000 | 1.5 |
| n1 | 1.0 | 250 | 0.5 | 1.0 | 2.0000 | 2.0 |
| n2 | 2.0 | 500 | 0.5 | 1.0 | 3.0000 | 3.0 |
| n2 | 2.0 | 250 | 0.9 | 1.0 | 3.0000 | 3.0 |

- **duration_model:** `expression: indur + tail` — exact (4 decimal places) across
  two input durations, three tail values, two delays, feedback up to 0.9.
- **Scalar ranges (CDP-enforced, all probed):** delay `(0.022676 to 10000.000000)` (min =
  one sample period at 44.1 kHz — srate-dependent); mix `(0.000000 to 1.000000)`;
  feedback `(-1.000000 to 1.000000)`; lfomod `(0.000000 to 1.000000)`; lfofreq
  `(-50.000000 to 50.000000)`; lfophase `(0.000000 to 1.000000)`; lfodelay
  `(0.000000 to 2.000000)` on a 2 s file (max = indur, input-dependent); tail
  `(0.000000 to 30.000000)`; prescale `-p` `(0.000031 to 1.000000)`; seed `-s`
  `(0.000000 to 256.000000)`.
- **DIVERGENCE:** cgromody.htm gives tail's range as "-1.0 to 1.0"; the binary enforces
  0–30 s (refuses −0.5, accepts 2.0). Manual documentation error.
- **Breakpoint probes (all 9 refused):**
  - delay: `ERROR: Cannot read parameter 1 [b_delay.brk]: brkpnt_files not permitted.`
  - mix: `ERROR: Cannot read parameter 2 [b_mix.brk]: brkpnt_files not permitted.`
  - feedback: `ERROR: Cannot read parameter 3 [b_fb.brk]: brkpnt_files not permitted.`
  - lfomod: `ERROR: Cannot read parameter 4 [b_mod.brk]: brkpnt_files not permitted.`
  - lfofreq: `ERROR: Cannot read parameter 5 [b_freq.brk]: brkpnt_files not permitted.`
  - lfophase: `ERROR: Cannot read parameter 6 [b_phase.brk]: brkpnt_files not permitted.`
  - lfodelay: `ERROR: Cannot read parameter 7 [b_ldel.brk]: brkpnt_files not permitted.`
  - tail: `ERROR: Cannot read parameter 8 [b_tail.brk]: brkpnt_files not permitted.`
  - prescale (`-p`): `ERROR: Cannot read parameter 9 [b_pre.brk]: brkpnt_files not permitted.`
- **HEADLINE DIVERGENCE — seed is a no-op; the "random" path is deterministic:**
  - positive lfofreq (sine sweep): two runs → identical decoded shas (expected).
  - negative lfofreq (documented "random oscillations"), unseeded, 1.1 s apart →
    **identical**; `-s5` twice → identical **and equal to the unseeded sha**; seeds
    1/9/77 and 3 vs 200 (deeper mod, −20 Hz) → all identical.
  - Sanity: the random path IS taken — lfofreq +20 vs −20 differ (max sample diff 0.38),
    and lfophase 0 vs 0.5 changes the negative-freq output.
  - Mechanism (source-confirmed): `dev/newsfsys/osbind.c` defines its own
    `drand48() { return (double)rand()/(double)RAND_MAX; }` "for both WIN32 and unix!",
    which overrides libc's `drand48` at link time (`nm` shows `T drand48` in the
    `modify` binary, `U srand48`). `dev/modify/delay.c` seeds via glibc `srand48(seed)`
    on non-Windows — a generator the shim never reads — and never calls `srand()` on this
    path, so `rand()` runs from its fixed default seed every time. On `_WIN32` the same
    code calls `srand(seed)`, which **does** seed the shim, so the flag presumably works
    there. Entry curated `stochastic: false`, `version_sensitive: true`, seed exposed
    with the no-op documented.
- **Channels:** stereo accepted (3.0 s, 2 ch out) → `any`.

## 2. distort average

Working argv: `distort average tone2.wav out.wav 5` — exit 0.

| input | indur | cyclecnt | outdur | drift vs static |
| ----- | ----- | -------- | ------ | --------------- |
| tone2 | 2.0 | 5   | 1.9841 | −0.80% |
| tone2 | 2.0 | 20  | 1.9501 | −2.50% |
| tone2 | 2.0 | 100 | 1.8141 | **−9.30%** |
| tone1 | 1.0 | 5   | 0.9864 | −1.36% |
| n2    | 2.0 | 5   | 1.9978 | −0.11% |
| n2    | 2.0 | 50  | 2.0113 | +0.57% |
| n2    | 2.0 | 100 | 1.9955 | −0.23% |
| n1    | 1.0 | 5   | 1.0006 | +0.06% |
| n3    | 3.0 | 20  | 3.0249 | +0.83% |

- **duration_model:** `static`. Holds within ±1.4% on noise across cyclecnt 5–100 and on
  tones at low cyclecnt; on strongly periodic material at high cyclecnt the final partial
  group (< cyclecnt wavecycles) is dropped — up to −9.3% observed (documented in
  known_issues, row pinned on noise/cyclecnt 5 at −0.11%). Output can also come out
  slightly *longer* (+0.83%) since averaged wavelengths are re-quantised.
- **skipcycles drops material:** `-s100` on tone2/cyclecnt 5 → 1.7574 s
  (−0.2267 s ≈ 100 cycles of 440 Hz dropped from the output entirely) — same behavior as
  distort repeat; documented, excluded from the model.
- **Breakpoints:** `cyclecnt` positional brk (`0.0 3 / 2.0 40`) → exit 0, output 1.9297 s,
  and the render differs from **both** the cyclecnt=3 and cyclecnt=40 scalar renders →
  **capable**. **DIVERGENCE:** the banner says nothing about time-variability; the HTML
  manual confirms it ("cyclecnt may vary over time") — banner-silent, manual+binary agree
  (cf. distort multiply, where even the manual was silent).
  - maxwavelen (`-m`): `ERROR: Cannot read parameter 2 [b_mw.brk]: brkpnt_files not permitted.`
  - skipcycles (`-s`): `ERROR: Cannot read parameter 3 [b_sk.brk]: brkpnt_files not permitted.`
- **Scalar ranges (CDP-enforced):** cyclecnt 1 →
  `ERROR: Parameter[1] Value (1.000000) out of range (2.000000 to 32767.000000)`
  (afta8's 2–6000 is an advisory subset); maxwavelen →
  `out of range (0.000363 to 1.000000)` (lower bound srate-dependent); skipcycles −1 →
  `out of range (0.000000 to 32767.000000)`. Content limit: cyclecnt 6001 on a 2 s tone →
  `ERROR: CANNOT ACHIEVE TASK: / ERROR: source sound too short to attempt this process.`
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo refused: `Application doesn't work with this type of infile.`
  (exit 255) → `mono`.

## 3. distort fractal

Working argv: `distort fractal tone2.wav out.wav 4 1.0` — exit 0.

| input | indur | scaling | loudness | outdur (frames) |
| ----- | ----- | ------- | -------- | --------------- |
| tone2 | 2.0 | 4  | 1.0 | 2.0 (88200) |
| tone2 | 2.0 | 64 | 1.0 | 2.0 (88200) |
| tone1 | 1.0 | 4  | 1.0 | 1.0 (44100) |
| n2    | 2.0 | 4  | 1.0 | 2.0 (88200) |
| n2    | 2.0 | 64 | 0.5 | 2.0 (88200) |
| n1    | 1.0 | 16 | 1.0 | 1.0 (44100) |

- **duration_model:** `static` — **sample-exact** (frame counts equal input in all six runs).
- **Breakpoints:** `scaling` brk (`0.0 2 / 2.0 64`) → exit 0 and differs from both endpoint
  scalar renders → **capable**; `loudness` brk (`0.0 0.3 / 2.0 1.0`) → exit 0 and differs
  from both endpoints → **capable** (both banner-confirmed: "scaling and loudness may vary
  over time"). pre_attenuation (`-p`):
  `ERROR: Cannot read parameter 3 [b_pa.brk]: brkpnt_files not permitted.`
- **Scalar ranges (CDP-enforced):** scaling 1 / 30000 →
  `out of range (2.000000 to 22050.000000)` (max = srate/2, input-dependent); loudness
  −0.5 → `out of range (0.000031 to 32767.000000)` — and **11 is accepted** (afta8's 0–10
  is advisory; >1 amplifies); pre_attenuation −1 / 0 / 40000 →
  `out of range (0.000031 to 32767.000000)` (values > 1 accepted despite the name).
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo refused (`Application doesn't work with this type of infile.`) → `mono`.

## 4. distort interpolate

Working argv: `distort interpolate tone2.wav out.wav 2` — exit 0.

| input | indur | multiplier | outdur | predicted `indur * multiplier` | rel err |
| ----- | ----- | ---------- | ------ | ------------------------------ | ------- |
| tone2 | 2.0 | 2 | 3.9932 | 4.0 | 0.17% |
| tone2 | 2.0 | 4 | 7.9841 | 8.0 | 0.20% |
| tone1 | 1.0 | 2 | 1.9932 | 2.0 | 0.34% |
| n2    | 2.0 | 2 | 4.0008 | 4.0 | 0.02% |
| n2    | 2.0 | 3 | 5.9996 | 6.0 | 0.01% |
| n1    | 1.0 | 8 | 7.9992 | 8.0 | 0.01% |

- **duration_model:** `expression: indur * multiplier` (skipcycles = 0 assumption);
  worst error 0.34%.
- With `-s100` (skipcycles) on tone2/mult 2: 3.5386 s — skipped wavecycles dropped from
  the output entirely (expected (2.0−0.227)×2 = 3.545), matching distort repeat; model
  over-predicts when skipcycles > 0; documented, not modelled.
- **Breakpoints:** `multiplier` positional brk (`0.0 2 / 2.0 8`) → exit 0 (9.975 s ≈ mean
  stretch ×5), differs from both endpoint renders → **capable**. `skipcycles` `-s<brk>` →
  `ERROR: Cannot read parameter 2 [b_sk2.brk]: brkpnt_files not permitted.`
- **BANNER BUG (first-class finding):** the banner ends
  "multiplier and cyclecnt may vary over time." but INTERPOLATE **has no cyclecnt
  parameter** — the line is copy-pasted from distort repeat. cdistort.htm correctly says
  only "multiplier may vary over time".
- **Scalar ranges (CDP-enforced):** multiplier 1 →
  `out of range (2.000000 to 32767.000000)` (afta8's 0–50/def 10 is advisory — 60 accepted,
  yielding 119.73 s from 2 s); skipcycles −1 / 40000 → `out of range (0.000000 to 32767.000000)`.
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo refused (`Application doesn't work with this type of infile.`) → `mono`.

## 5. envel dovetail, submode 1

Working argv: `envel dovetail 1 n2.wav out.wav 0.3 0.5 1 1` — exit 0.

| input | indur | args | outdur |
| ----- | ----- | ---- | ------ |
| n2 | 2.0 | 0.3 0.5 1 1 | 2.0000 |
| n2 | 2.0 | 0.3 0.5 0 0 | 2.0000 |
| n1 | 1.0 | 0.2 0.2 1 1 | 1.0000 |
| n2 | 2.0 | 0.5 0.5 1 1 -t0 | 2.0000 |
| n2 | 2.0 | 22050 22050 1 1 -t1 | 2.0000 |
| n2 | 2.0 | 22050 22050 1 1 -t2 | 2.0000 |
| st2 (stereo) | 2.0 | 0.3 0.5 1 1 | 2.0000 (2 ch) |

- **duration_model:** `static` — exact. Fades verified applied in place: first/last 50 ms
  RMS at 3.4% / 1.4% of the source, middle untouched (ratio 1.0).
- **UNDOCUMENTED SHAPE VALUES (first-class finding):** intype/outtype accept **0–3**, not
  the documented 0/1. Source: `envlcon.h` defines `ENVTYPE_LIN 0 / EXP 1 / STEEP 2 / DBL 3`
  and `envprepro.c` passes the user value straight through for mode DOVE. Probes: 2 and 3
  exit 0 with distinct outputs, and `dovetail 1 ... 3 3` is **byte-identical** to
  `dovetail 2` (same fades) — submode 2 is a special case of submode 1. intype 5 / −1 →
  `ERROR: Unknown case in create_envelope()`; intype 4 → `ERROR: INTERNAL ERROR: (Bug?)`
  (no range check).
- **Runtime constraint:** infade 1.2 + outfade 1.2 on 2 s →
  `ERROR: Start and End Trims overlap: cannot proceed.` Negative infadedur →
  `ERROR: INSUFFICIENT MEMORY to reallocate level array.` (misleading refusal, no range check).
- **times flag:** `-t1` (samples) and `-t2` (grouped-samples) verified working
  (22050-sample fades on a 44.1 kHz file behave as 0.5 s); `-t3` →
  `ERROR: Unknown case: ENV_DOVETAILING: envelope_preprocess()`.
- **Breakpoint probes (all refused):**
  - infadedur: `ERROR: Cannot read parameter 1 [b_if.brk]: brkpnt_files not permitted.`
  - outfadedur: `ERROR: Cannot read parameter 2 [b_of.brk]: brkpnt_files not permitted.`
  - intype: `ERROR: Cannot read parameter 3 [b_it.brk]: brkpnt_files not permitted.`
  - outtype: `ERROR: Cannot read parameter 4 [b_it.brk]: brkpnt_files not permitted.`
  - times (`-t`): `ERROR: Cannot read parameter 5 [b_it.brk]: brkpnt_files not permitted.`
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo accepted → `any`.

## 6. sfedit cut, submode 1

Working argv: `sfedit cut 1 n2.wav out.wav 0.5 1.5` — exit 0.

| input | start | end | splice | frames | outdur | predicted `end - start` |
| ----- | ----- | --- | ------ | ------ | ------ | ----------------------- |
| n2 | 0.5  | 1.5  | (default 15) | 44100 | 1.0 | 1.0 |
| n2 | 0.25 | 1.75 | (default) | 66150 | 1.5 | 1.5 |
| n1 | 0.2  | 0.9  | (default) | 30870 | 0.7 | 0.7 |
| n2 | 0.5  | 1.5  | -w0   | 44100 | 1.0 | 1.0 |
| n2 | 0.5  | 1.5  | -w100 | 44100 | 1.0 | 1.0 |
| n2 | 0    | 2.0  | (default) | 88200 | 2.0 | 2.0 |
| st2 (stereo) | 0.5 | 1.5 | (default) | 44100 | 1.0 (2 ch) | 1.0 |

- **duration_model:** `expression: end - start` — **sample-exact**; the splice window does
  not change the duration (fades are applied inside the block).
- **Content verified:** `-w0` output is a sample-exact copy of `input[0.5s:1.5s]`
  (allclose, atol 1e-7); with the default splice the interior is bit-identical and only
  the edges are faded (first output sample 0).
- **Silent swap (first-class finding):** `start=1.5 end=0.5` is accepted (exit 0) and the
  output is **byte-identical** to the `0.5 1.5` cut — CDP swaps reversed bounds without
  warning.
- **Scalar ranges:** start 2.5 / end 3.5 on a 2 s file →
  `ERROR: Parameter[N] Value (...) out of range (0.000000 to 2.000000)` (bounds = input
  duration, runtime-enforced; no clamping). splice −1 →
  `out of range (0.000000 to 5000.000000)` (afta8's 0–1000 is an advisory subset);
  splice 600 on a 1 s block → `ERROR: Edited portion is too short for specified splicelen.`
- **Breakpoint probes (all refused):**
  - start: `ERROR: Cannot read parameter 1 [b_st.brk]: brkpnt_files not permitted.`
  - end: `ERROR: Cannot read parameter 2 [b_en.brk]: brkpnt_files not permitted.`
  - splice (`-w`): `ERROR: Cannot read parameter 3 [b_sp.brk]: brkpnt_files not permitted.`
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo accepted → `any`.

---

## Final row confirmations (exact pinned params, noise inputs)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| modify revecho 2, delay 250/mix 0.5/fb 0.5/lfomod 0.3/lfofreq 1/phase 0/lfodelay 0/tail 1.0, indur 2.0 | 3.0 | 3.0000 | 0.000% |
| distort average (static), cyclecnt 5, indur 2.0 | 2.0 | 1.9978 | 0.110% |
| distort fractal (static), scaling 4/loudness 1.0, indur 2.0 | 2.0 | 2.0000 | 0.000% |
| distort interpolate, multiplier 3, indur 2.0 | 6.0 | 5.9996 | 0.007% |
| envel dovetail 1 (static), 0.3/0.5/1/1, indur 2.0 | 2.0 | 2.0000 | 0.000% |
| sfedit cut 1, start 0.5/end 1.5, indur 2.0 | 1.0 | 1.0000 | 0.000% |

All six entries shipped; none dropped.
