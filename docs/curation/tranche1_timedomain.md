# Tranche 1 — time-domain curation probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (built from ComposersDesktop/CDP8 source; banners
  self-report "CDP Release 7.1 2016"), Linux x86_64 sandbox.
- **Note:** these outcomes are re-verified on macOS r8 by the CDP-gated suite
  (`tests/test_curation_formulas.py` and `tests/test_breakpoint_curation.py`) after the
  findings rows are integrated.
- **Inputs:** synthesized in `/tmp/probe` via python-soundfile — mono 44100 Hz float32
  noise bursts `n1` (1.0 s), `n2` (2.0 s), `n3` (3.0 s); 440 Hz sine tones `tone1` (1.0 s),
  `tone2` (2.0 s); stereo noise `st2` (2.0 s).
- **Methodology:** replicates `docs/phase-2-breakpoint-review.md`. Breakpoint probes use a
  2-line file `0.0 <lo>\n2.0 <hi>` substituted at the parameter's argv position (or
  `-X<file>` attached for flags). Determinism compares sha256 of **decoded samples**
  (soundfile, float64), never raw bytes (CDP embeds timestamps in headers).

Refusal errors quoted below are verbatim from the binary (emitted to stdout with exit 255).

---

## 1. modify radical, submode 1 (REVERSE)

Working argv: `modify radical 1 n2.wav out.wav` — exit 0.

| input | indur (s) | outdur (s) |
| ----- | --------- | ---------- |
| n2    | 2.000     | 2.000      |
| n1    | 1.000     | 1.000      |
| st2 (stereo) | 2.000 | 2.000 (2 ch) |

- **duration_model:** `static` — exact.
- **Reversal verified sample-exact:** `out[:100] == in[::-1][:100]` (allclose, atol 1e-6).
- **Breakpoints:** no numeric parameters; nothing to probe.
- **Determinism:** two runs → identical decoded-sample sha256. Not stochastic.
- **Channels:** stereo accepted → `any`.

## 2. modify speed, submode 2 (semitone varispeed)

Working argv: `modify speed 2 n2.wav out.wav -12` — exit 0.

| input | indur | semitones | outdur | predicted `indur / 2**(st/12)` | rel err |
| ----- | ----- | --------- | ------ | ------------------------------ | ------- |
| n2 | 2.0 | -12 | 4.0000 | 4.0000 | 0.0011% |
| n2 | 2.0 | +12 | 1.0000 | 1.0000 | 0.0000% |
| n1 | 1.0 | -12 | 2.0000 | 2.0000 | 0.0023% |
| n2 | 2.0 | +7  | 1.3348 | 1.3348 | 0.0007% |
| n3 | 3.0 | -5  | 4.0045 | 4.0045 | 0.0007% |

- **duration_model:** `expression: indur / 2 ** (semitones / 12)` — sub-0.01% across the table.
- **Range:** ±48 and -96 all accepted (−96 → 256.0 s from 1 s input); no practical CDP limit found. min/max left null.
- **Breakpoints:** `semitones` positional brk (`0.0 -12 / 2.0 12`) → exit 0, output produced
  (1.848 s) → **capable** (manual-confirmed: "Both speed and semitone-transpos may vary over time").
- **Determinism:** identical decoded samples across two runs. Not stochastic.
- **Channels:** stereo accepted (2 ch out, 4.0 s at −12) → `any`.
- `-o` (brk times read as outfile times) is a value-less switch; not exposed (extend loop `-b` precedent).

## 3. distort multiply

Working argv: `distort multiply tone2.wav out.wav 2` — exit 0.

| input | indur | N | outdur |
| ----- | ----- | - | ------ |
| tone2 | 2.0 | 2 | 1.9989 |
| tone2 | 2.0 | 4 | 1.9989 |
| tone1 | 1.0 | 2 | 0.9989 |
| n2    | 2.0 | 2 | 2.0000 |

- **duration_model:** `static` (≤0.11% short — final partial wavecycle dropped).
- **Breakpoints:** `multiplier` brk (`0.0 2 / 2.0 8`) → exit 0, output produced, and the
  output differs from **both** the N=2 and N=8 scalar renders → genuinely time-varying →
  **capable**. **DIVERGENCE:** neither the banner nor cdistort.htm mentions time-variability
  for MULTIPLY (they do for REPEAT); SoundThread marks it automatable — SoundThread and the
  binary agree, the CDP docs are silent.
- **Scalar range (CDP-enforced):** N=17 → `ERROR: Parameter[1] Value (17.000000) out of range (2.000000 to 16.000000)`.
- **Determinism:** identical decoded samples. Not stochastic.
- **Channels:** stereo refused: `Application doesn't work with this type of infile.` (exit 255) → `mono`.
- `-s` smoothing switch (value-less) verified working as scalar; not exposed (precedent).

## 4. distort repeat

Working argv: `distort repeat tone2.wav out.wav 2` — exit 0.

| input | indur | multiplier | outdur | predicted `indur * multiplier` | rel err |
| ----- | ----- | ---------- | ------ | ------------------------------ | ------- |
| tone2 | 2.0 | 2 | 3.9955 | 4.0 | 0.113% |
| tone2 | 2.0 | 4 | 7.9909 | 8.0 | 0.113% |
| tone1 | 1.0 | 2 | 1.9955 | 2.0 | 0.227% |
| n1    | 1.0 | 2 | 1.9999 | 2.0 | 0.007% |
| n2    | 2.0 | 3 | 5.9999 | 6.0 | 0.001% |

- With `-c4` (cyclecnt): 3.9819 s vs 4.0 predicted (0.45%) — model unaffected.
- With `-s100` (skipcycles) on tone2/mult 2: 3.5409 s — the 100 skipped wavecycles
  (≈0.227 s of a 440 Hz tone) are **dropped from the output entirely** (expected
  (2.0−0.227)×2 = 3.545). Model over-predicts when skipcycles > 0; documented, not modelled.
- **duration_model:** `expression: indur * multiplier` (skipcycles = 0 assumption).
- **Breakpoints:** `multiplier` positional brk → exit 0 (7.986 s) → **capable**.
  `cyclecnt` `-c<brk>` → exit 0 (3.982 s) → **capable**. Both banner-confirmed
  ("multiplier and cyclecnt may vary over time"). `skipcycles` `-s<brk>` →
  `ERROR: Cannot read parameter 3 [sk.brk]: brkpnt_files not permitted.` → **not capable**.
- **Scalar ranges (CDP-enforced):** multiplier 1 → `out of range (2.000000 to 32767.000000)`;
  `-c0` → `out of range (1.000000 to 32767.000000)`; `-s-1` → `out of range (0.000000 to 32767.000000)`.
- **Determinism:** identical decoded samples. Not stochastic.
- **Channels:** stereo refused (`Application doesn't work with this type of infile.`) → `mono`.

## 5. extend zigzag, submode 1

Working argv: `extend zigzag 1 n2.wav out.wav 0.0 2.0 5.0 0.2 -r1` — exit 0.

| input | dur requested | outdur observed |
| ----- | ------------- | --------------- |
| n2 | 6.0 | 7.9932 (+33%) |
| n2 | 4.0 | 5.6185 (+40%) |
| n1 | 3.0 | 3.2135 (+7%) |
| n2 | 5.0 (seeds 1,2,3 + 3 unseeded) | 6.476 / 5.920 / 7.641 / 5.619 / 6.046 / 5.249 (+5%…+53%) |
| n2 | 6.0, `-m0.5` (seeds 10-12) | 6.893 / 7.163 / 7.058 |

- **duration_model:** `dur` is a **floor** — mode 1 must finish at the file end, so CDP
  zigzags past `dur` by a stochastic amount that can exceed `dur + indur` (7.641 for dur 5,
  indur 2). Constraining `-m` does not tame it. Not predictable within 5% → curated as
  `set_by: dur` documented as a lower bound (deliberately NOT `static`: static (=indur)
  would predict 2 s where actual output is 5–8 s, far worse for pre-flight capping on an
  extend process). **No duration row pinned.**
- **Breakpoint probes (all refused):**
  - start: `ERROR: Cannot read parameter 1 [b_start.brk]: brkpnt_files not permitted.`
  - end: `ERROR: Cannot read parameter 2 [b_end.brk]: brkpnt_files not permitted.`
  - dur: `ERROR: Cannot read parameter 3 [b_dur.brk]: brkpnt_files not permitted.`
  - minzig: `ERROR: Cannot read parameter 4 [b_minzig.brk]: brkpnt_files not permitted.`
  - splicelen (`-s`): `ERROR: Cannot read parameter 5 [b_spl.brk]: brkpnt_files not permitted.`
  - maxzig (`-m`): `ERROR: Cannot read parameter 6 [b_max.brk]: brkpnt_files not permitted.`
- **Stochasticity:** unseeded runs launched back-to-back → **identical** decoded samples
  (clock-seeded, same-second collision); unseeded runs 1.5 s apart → different. `-r1` run
  twice → identical → seed gives exact reproducibility. **Stochastic**; `phase_sensitive: true`,
  `stereo_link_default: "related"`.
- **Seed hazard:** `-r7` on the canonical args aborts:
  `ERROR: CANNOT ACHIEVE TASK: / ERROR: Final zig too short for splicelen.`
- **Channels:** stereo accepted (6.476 s, 2 ch) → `any`.

## 6. extend scramble, submode 1

Working argv: `extend scramble 1 n2.wav out.wav 0.1 0.3 5.0 -s5` — exit 0.

| input | minseg | maxseg | outdur | observed | rel err |
| ----- | ------ | ------ | ------ | -------- | ------- |
| n2 | 0.1 | 0.3 | 5.0 | 5.0959 | 1.92% |
| n2 | 0.1 | 0.3 | 3.0 | 3.1043 | 3.48% |
| n1 | 0.1 | 0.3 | 4.0 | 4.2368 | **5.92%** |
| n2 | 0.1 | 0.2 | 5.0 | 8 seeds: max err **3.57%** (0.12–3.57%) |

- **duration_model:** `set_by: outdur`. Overrun is bounded by the final chunk
  (< maxseglen), so prediction is within 5% only when maxseglen ≪ outdur. Row pinned with
  maxseglen 0.2 / outdur 5 (bound 4%).
- **Breakpoint probes (all refused):**
  - minseglen: `ERROR: Cannot read parameter 1 [b_min.brk]: brkpnt_files not permitted.`
  - maxseglen: `ERROR: Cannot read parameter 2 [b_max.brk]: brkpnt_files not permitted.`
  - outdur: `ERROR: Cannot read parameter 3 [b_od.brk]: brkpnt_files not permitted.`
  - splen (`-w`): `ERROR: Cannot read parameter 4 [b_w.brk]: brkpnt_files not permitted.`
- **Stochasticity:** unseeded runs 1.2 s apart → different decoded samples; `-s5` run twice
  → identical. **Stochastic**; `phase_sensitive: true`, `stereo_link_default: "related"`.
- **Runtime-enforced bounds are input/splice-dependent:** minseglen 0.01 on a 2 s file →
  `ERROR: Parameter[1] Value (0.010000) out of range (0.031000 to 1.985000)`.
- **Channels:** stereo accepted (5.043 s, 2 ch) → `any`.
- `-b` / `-e` value-less switches not exposed (precedent).

## 7. filter lohi, submode 1

Working argv: `filter lohi 1 n2.wav out.wav -60 1000 4000` — exit 0.

| input | indur | tail arg | outdur |
| ----- | ----- | -------- | ------ |
| n2 | 2.0 | (omitted) | **3.0000** |
| n2 | 2.0 | `-t0`     | 2.0172 |
| n2 | 2.0 | `-t0.5`   | 2.5000 |
| n1 | 1.0 | (omitted) | **2.0000** |
| n1 | 1.0 | `-t0`     | 1.0172 |
| n1 | 1.0 | `-t0.5`   | 1.5000 |

- **DIVERGENCE (headline):** the banner shows `[-ttail]` but cgrofilt.htm's FILTER LOHI
  section lists only `-s prescale` — the same banner-only tail parameter this project first
  caught on `filter sweeping`, with the same behavior: **omitting `-t` appends exactly
  +1.00 s**. Entry pins `tail` default 1.0 (always emitted) and models `indur + tail`.
- With `-t0` a small ring-out remainder is still appended, growing with filter order:
  +22.3 ms at attenuation −30 (order 2), +17.2 ms at −60 (order 4), +16.3 ms at −96 (order 8).
- **Breakpoint probes (all refused):**
  - attenuation: `ERROR: Cannot read parameter 2 [b_att.brk]: brkpnt_files not permitted.`
  - passband: `ERROR: Cannot read parameter 3 [b_pass.brk]: brkpnt_files not permitted.`
  - stopband: `ERROR: Cannot read parameter 4 [b_stop.brk]: brkpnt_files not permitted.`
  - tail (`-t`): `ERROR: Cannot read parameter 6 [b_tail.brk]: brkpnt_files not permitted.`
  - prescale (`-s`): `ERROR: Cannot read parameter 7 [b_pre.brk]: brkpnt_files not permitted.`
- **Scalar range (CDP-enforced):** attenuation +10 →
  `ERROR: Parameter[1] Value (10.000000) out of range (-96.000000 to 0.000000)`; 0 accepted.
- **Determinism:** identical decoded samples. Not stochastic.
- **Channels:** stereo accepted (hipass 4000/1000: 3.0 s, 2 ch) → `any`.

---

## Final row confirmations (exact pinned params, unseeded, noise inputs)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| modify radical (static), indur 2.0 | 2.0 | 2.0000 | 0.000% |
| modify speed, semitones −12, indur 2.0 | 4.0 | 4.0000 | 0.001% |
| distort multiply, multiplier 2, indur 2.0 | 2.0 | 2.0000 | 0.002% |
| distort repeat, multiplier 3, indur 2.0 | 6.0 | 5.9999 | 0.001% |
| extend scramble, 0.1/0.2/outdur 5, indur 2.0 | 5.0 | 5.0081 | 0.161% |
| filter lohi, −60/1000/4000, tail 1.0, indur 2.0 | 3.0 | 3.0000 | 0.000% |

All seven entries shipped; none dropped.
