# Tranche 6 — grain / pitch-tune / combine / distort-interact curation probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (built from ComposersDesktop/CDP8 source; Groucho
  programs banner "CDP Release 7.1 2016"; `clip` and `scramble` are CDP8-era additions
  that print no version banner), Linux x86_64 sandbox.
- **Note:** these outcomes are re-verified on macOS r8 by the CDP-gated suite after the
  findings rows are integrated.
- **Inputs:** synthesized in `/tmp/probe6` via python-soundfile (PCM_16 unless noted) —
  mono 44100 Hz enveloped noise bursts `n1` (1.0 s), `n2` (2.0 s), `n3` (3.0 s); 440 Hz
  sines `tone1` (1.0 s), `tone2` (2.0 s); stereo noise `st2` (2.0 s). Tranche-specific
  extras for the grain family (which needs **clear attack structure with real silences**):
  `click2` (2.0 s, 10 grains — 60 ms decaying noise bursts with 8-sample hard attacks at
  0.2 s onsets, 140 ms silent holes), `click3` (3.0 s, 15 grains), `clickd2` (2.0 s,
  20 grains at 0.1 s spacing), `clickamp` (alternating 0.9/0.15 grain amplitudes, for
  gate probes), `click3lv` (0.9/0.4/0.15 three-level train, for the default-gate pin),
  `clickst` (stereo click train), `fixn2`/`fixn3` (FLOAT flat noise
  `standard_normal*0.2`, replicating the duration-fixture's `_write_noise` — grain
  programs see **1 grain** in it). Spectral inputs are `pvoc anal 1` conversions
  (default analysis; 2 s wav → 2.029070 s `.ana`, 344 windows/s, 1 s → 1.026163 s).
- **Methodology:** replicates `docs/curation/tranche2_timedomain.md`. Breakpoint probes
  use a 2-line file `0.0 <lo>\n2.0 <hi>` substituted at the parameter's argv position (or
  `-X<file>` attached for flags). Determinism compares decoded samples (soundfile,
  float64) for wavs and the RIFF **data chunk only** for `.ana` (tranche-5 LIST-date-chunk
  trap); unseeded pairs launched > 1.1 s apart. Refusals quoted verbatim (exit 255 unless
  noted).

---

## 0. SEED HUNT — the Phase 6 stereo-seed-linking trigger question

The tranche brief flagged that a **seeded mono stochastic grain entry** would trigger the
deferred stereo seed-linking machinery. Findings (machinery deliberately NOT built):

- **The grain family has NO seed flag anywhere.** All 15 mode banners checked (count,
  omit, repitch, timewarp, find, duplicate, rerhythm, reverse, reposition, reorder,
  remotif, assess, r_extend, grev, noise_extend, align): no `-s`-style seed on any of
  them (`r_extend`'s `-s` is "don't keep start of sound").
- **Source:** `dev/grain/*.c` contains **no `srand` call**. `drand48()` appears only in
  the r_extend path (`timestretch_iterative`,
  `rand_ints_with_restricted_repeats`/`do_repet_restricted_perm` — the ASC/PSC
  amplitude/pitch scatter and segment permutation) and in noise_extend
  (`grab_noise_and_expand`, grain1.c:3021). `nm` on the `grain` binary shows the
  osbind.c shim (`T drand48`, backed by `rand()/RAND_MAX`) plus `U srand@GLIBC` pulled
  in by a library — so even the "random" grain modes run from `rand()`'s fixed default
  seed: **deterministic every run, unseeded and unseedable** (the modify-revecho
  mechanism from tranche 2, now on the never-seeded side).
- **Empirical:** all five shipped grain modes verified deterministic (decoded-sample
  identical, runs > 1.1 s apart).
- **The nearest true trigger lives elsewhere: `scramble scramble`** (CDP8-era waveset
  scrambler, `dev/science/scramble.c`). Its seed is a **required positional** (0–256)
  and it **WORKS**: line 1123 calls `srand(dz->iparam[SCR_SEED])`, which seeds the
  `rand()` behind the drand48 shim (exactly the path that makes revecho's seed work on
  `_WIN32` only). Verified: seed 5 twice → decoded-identical; seed 5 vs 9 → differ.
  **Mono only** (`ERROR: INVALID DATA / ERROR: File st2.wav is not of correct type
  (must be mono)`). There is no unseeded/clock path (the positional is mandatory), so
  every render is reproducible by construction. If/when curated, THIS is the entry that
  poses the stereo seed-linking question (channel split → per-channel seeds →
  interleave). Recorded only; out of this tranche's set.

## 1. grain scramble — VERIFIED NONEXISTENT

`grain` has no `scramble` mode (mode list quoted from the banner: count, omit, repitch,
timewarp, find, duplicate, rerhythm, reverse, reposition, reorder, remotif, assess,
r_extend, grev, noise_extend, align). cgrogrns.htm mentions "scramble" only once, in
prose ("scrambled together"). The name collides with two real, distinct things:
`extend scramble` (already curated, tranche 1) and the standalone `scramble scramble`
waveset program (see §0). Nothing to curate under (grain, scramble).

## 2. Grain-family shared parameter surface (probed per program, identical outcomes)

All five shipped grain modes share `[-blen] [-lgate] [-hminhole] [-twinsize] [-x]`:

- **Ranges (verbatim, on a 2 s file; max bounds are the input duration and scale with
  it):** len `-b0.001` → `Parameter[N] Value (0.001000) out of range (0.100000 to
  2.000000)`; gate `-l2`/`-l-0.5` → `(0.000000 to 1.000000)`; minhole `-h0.01` →
  `(0.032000 to 2.000000)`; winsize `-t2500` → `(0.000000 to 2000.000000)` (ms). The
  range-refusal parameter NUMBERING shifts with the positional count (reverse: len=1,
  gate=2, minhole=3, winsize=4; duplicate/timewarp/rerhythm: 2/3/4/5; reposition:
  3/…), while **brk refusals number len=3, minhole=5, winsize=6 in every mode** —
  CDP's stage-dependent numbering again (filter bank precedent).
- **DIVERGENCE (default):** every banner says gate "default 1"; the real default is
  **0.3** — manual and afta8 both say 0.3, and behavior agrees: on a 0.9/0.4/0.15
  three-level train, default and `-l0.3` count 7 grains while `-l0.45`/`-l0.5` count 4;
  on the loud/soft train the unflagged `grain reverse` render is **byte-identical** to
  `-l0.3`.
- **DIVERGENCE (range):** manual/banner give len's range as "1 to duration of infile";
  the binary enforces **0.1** to duration.
- **gate is the family's only breakpointable flag** ("Gate may vary over time" in every
  banner): verified **differs-from-both-endpoints** on grain reverse (0.05→0.5 ramp on
  clickamp vs the two scalar renders); exit-0 verified on duplicate, timewarp, rerhythm,
  reposition. len/minhole/winsize brks refused in every mode (verbatim, parameter
  3/5/6).
- **Flag order:** `-x` before a value flag refuses `ERROR: option flag -l out of order
  on cmdline.`; value-flag reordering among themselves was tolerated (`-l0.3 -b0.5`
  ran). Entries declare `-x` last.
- **Grain-count edge cases:** `grain count` on flat fixture noise finds **1 grain**; on
  a pure tone / after that, `grain reverse` refuses `ERROR: INVALID DATA / ERROR: No
  grains found.` (needs ≥ 2), while duplicate (N copies of the whole file), timewarp
  (pass-through), rerhythm (pass-through) and reposition (effectively pass-through)
  all exit 0 on 1-grain material.
- **Stereo:** accepted by all five (2-channel outputs, same duration arithmetic) →
  `channel_constraint: any`.

## 3. grain reverse — SHIPPED

**Working argv:** `grain reverse click2.wav out.wav` — exit 0.

| input | args | outdur | note |
| ----- | ---- | ------ | ---- |
| click2 (2.0) | — | 2.007506 | +331 frames (7.5 ms splice tail) |
| click3 (3.0) | — | 3.007506 | +331 frames |
| n2 (2 grains) | — | 1.973129 | −1.34% |
| clickst (stereo) | — | 2.007506 (2 ch) | |
| click2 | -x | 1.799977 | last grain dropped |
| tone2 / fixn2 | — | **refused** | `No grains found.` |

- **duration_model:** `static`, worst observed |error| 1.4% (excl. `-x`).
- **Content verified:** input grain-peak sequence [0.87, 0.37, 0.14, …, 0.85] comes out
  exactly reversed [0.85, 0.14, 0.38, …, 0.87] — order retrograded, grains forwards.
- **gate brk differs from both endpoints** (shas b9d1/71e2 vs 2213). Deterministic.
- **Fixture warning:** the duration-model fixture's flat noise REFUSES here (`No grains
  found.`) — the findings row carries a grainy-input requirement.

## 4. grain duplicate — SHIPPED

**Working argv:** `grain duplicate click2.wav out.wav 2` — exit 0.

| input | repeats | outdur | `indur * repeats` | rel err |
| ----- | ------- | ------ | ------------------ | ------- |
| click2 | 2 | 4.007506 | 4.0 | +0.19% |
| click2 | 3 | 6.015011 | 6.0 | +0.25% |
| click2 | 1 | 2.000000 | 2.0 | exact (identity) |
| click3 | 2 | 6.007506 | 6.0 | +0.13% |
| fixn2 (flat noise) | 2 | 4.007234 | 4.0 | +0.18% |
| fixn2 | 3 | 6.014467 | 6.0 | +0.24% |
| n2 | 2 | 3.973129 | 4.0 | −0.67% |
| n2 | 3 | 5.946259 | 6.0 | −0.90% |
| clickst (stereo) | 2 | 4.007506 (2 ch) | 4.0 | +0.19% |

- **duration_model:** `expression: indur * repeats` — worst −0.9%; splice overhead is
  `(repeats−1) × 331` frames. Works on 1-grain material (whole file duplicated) —
  **fixture-compatible**.
- **N range (verbatim):** `Parameter[1] Value (0.000000/40000.000000) out of range
  (1.000000 to 32767.000000)`. **Fractional N rounds to NEAREST:** 2.5 byte-identical
  to 3 (distort-divide behavior).
- **N brk (1→4):** exit 0, 4.615 s, differs from both endpoint renders → capable
  (banner: "N and Gate may vary over time"). gate brk exit 0. Deterministic. `-x` = last
  grain not duplicated (3.59 s at repeats 2).

## 5. grain timewarp — SHIPPED

**Working argv:** `grain timewarp click2.wav out.wav 2` — exit 0.

| input | ratio | outdur | exact rule* | `indur * ratio` | rel err |
| ----- | ----- | ------ | ----------- | ---------------- | ------- |
| click2 | 2 | 3.799977 | 3.8 | 4.0 | −5.0% |
| click2 | 0.5 | 1.100045 | 1.1 | 1.0 | +10% |
| click2 | 3 | 5.599955 | 5.6 | 6.0 | −6.7% |
| click2 | 1 | 2.000000 | 2.0 | 2.0 | exact |
| click3 | 2 | 5.800000 | 5.8 | 6.0 | −3.3% |
| clickd2 | 2 | 3.900000 | 3.9 | 4.0 | −2.5% |
| fixn2 (1 grain) | 2 / 0.5 / 1 | **2.000000** | 2.0 | 4.0 / 1.0 / 2.0 | model FAILS off ratio 1 |
| clickst (stereo) | 2 | 3.799977 (2 ch) | 3.8 | | |

\* exact rule, verified to the sample: `outdur = ratio × (last onset − first onset) +
(indur − span)` — only the onset-to-onset intervals stretch; grains and the
head/tail remainder do not.

- **duration_model:** `expression: indur * ratio`, **honestly bounded** (−6.7%…+10%
  observed on grainy material with a 0.1–0.2 s uncovered tail; catastrophic on
  no-grain material). Findings row pinned at **ratio 1.0** (2.000000 exact on both
  grainy and fixture-noise inputs) — the only fixture-survivable pin.
- **ratio range (verbatim):** `Parameter[1] Value (0.000500/1001.000000) out of range
  (0.001000 to 1000.000000)` (afta8's max 50 advisory). MINGRAINTIME clamp 0.032 s
  (banner).
- **ratio brk (0.5→2):** exit 0, 2.18 s, differs from both endpoint renders → capable
  (banner adds: "Times in brkpnt files refer to INFILE time"). gate brk exit 0.
  Deterministic; `-x` verified (3.59 s).

## 6. grain rerhythm, mode 1 — SHIPPED (aux multfile)

**Working argv:** `grain rerhythm 1 click2.wav out.wav m15.txt` with `m15.txt` = `1.5`
— exit 0. The multfile sits **after** the output → expressible as `aux_file` (contrast
submix mix's pre-output slot).

| multfile | mode | outdur | predicted (exact arithmetic) |
| -------- | ---- | ------ | ---------------------------- |
| `1.5` | 1 | 2.900023 | 1.5×1.8 + 0.2 = 2.9 |
| `0.5 2.0` | 1 | 2.300068 | gaps cycle 0.1/0.4: 2.1 + 0.2 = 2.3 |
| `1.0` | 1 | 2.000000 | 2.0 exact |
| `0.5\n2.0` (newlines) | 1 | 2.300068 | **byte-identical** to space form |
| `0.5 2.0` | **2** | 4.700000 | each gap → 0.1 + 0.4 copies: 9×0.5 + 0.2 = 4.7 |
| `1.5` on fixn2 | 1 | 2.000000 | 1 grain → no intervals, pass-through |
| `1.5` on clickst | 1 | 2.900023 (2 ch) | |

- **duration_model:** `static` (the mean-multiplier-1 baseline; the exact rule
  `Σ(cycled mult_i × interval_i) + remainder` is data-file-dependent and verified
  exact above). Row pinned on multfile `1.0` → exact.
- **Multfile validation (verbatim):** value 2000 / 0.0001 →
  `ERROR: INVALID DATA / ERROR: Ratio (2000.000000) out of range (0.001000 -
  1000.000000)` (**dash format**, not "to"); non-numeric → `ERROR: No data in file
  'mbad.txt'.`; a time/value `.brk` is consumed as a **flat value list** (its 0.0 time
  refused as a ratio) — the modify-stack transpos trap.
- Mode 3 → `Program mode value [3] is out of range [1 - 2].` gate brk exit 0; len brk
  refused param 3; -h/-t refused 5/6. Deterministic. `-x` verified (2.69 s vs 2.90 s).
- **Submode 2** (each grain plays once per multiplier) probed and documented; not
  shipped (one (program, mode) key).

## 7. grain reposition — SHIPPED (aux timefile)

**Working argv:** `grain reposition click2.wav out.wav t10.txt 0` with `t10.txt` =
`0 0.3 0.6 … 2.7` — exit 0.

| timefile | offset | outdur | predicted (exact rule*) |
| -------- | ------ | ------ | ----------------------- |
| 10 times to 2.7 | 0 | 2.900023 | 2.7 + 0.2 |
| 10 times to 2.7 | 0.5 | 3.400023 | +0.5, leading silence KEPT |
| `0 0.5` (2 times, 10 grains) | 0 | 0.700000 | surplus grains **DROPPED** |
| 10 times to 0.9 (0.1 grid) | 0 | 1.100023 | 0.9 + 0.2 |
| source-matching onsets (0…1.8) | 0 | 2.000023 | ≈ indur (+1 frame) |
| t10 on fixn2 (1 grain) | 0 | 2.000000 | pass-through |
| t10 on clickst | 0 | 2.900023 (2 ch) | |

\* `outdur = offset + last timefile entry + (indur − last source grain onset)`.

- **duration_model:** `static` (baseline: timefile mirroring the source onsets — row
  pinned there, +0.001%); the timefile drives real durations, documented honestly.
- **Timefile validation (verbatim):** unsorted →
  `ERROR: Sync times out of sequence (0.500000 0.200000)`; negative times →
  `ERROR: No data in file 'tneg.txt'.`; a `.brk` envelope is consumed as a flat list
  and refuses as out-of-sequence. First grain at time 0 warns
  `WARNING: 1st grain moved by 0.015011 secs (662 samps) to allow for startsplice`.
- **offset:** positional after the timefile; range refusal
  `Parameter[2] Value (-0.500000) out of range (0.000000 to 32767.000000)`; brk refused
  `Cannot read parameter 1 [g_ratio.brk]: brkpnt_files not permitted.` (numbering
  differs between the two stages). gate brk exit 0; -b/-h/-t brks refused 3/5/6.
  Deterministic. `-x` verified.

## 8. pitch tune, mode 1 — SHIPPED

**Working argv:** `pitch tune 1 n2.ana out.ana 440` — exit 0 (SoundThread
`pitch_tune_1`). **Not data-file-gated:** the pitch_template slot takes a plain number;
the multi-pitch FILE form exists but is optional (see below).

- **duration_model:** `static` — every run returns the input's exact `.ana` duration
  (2.029070 / 1.026163).
- **Tuning verified:** synth of noise-tuned-to-440 has its top eight spectral peaks at
  **exact multiples of 440 Hz** (440, 2200, 4400, 7920, 12320, 14520, 20240, 22000).
- **Template range (verbatim, with cosmetic bug — the VALUE prints in the filename
  slot):** `ERROR: Input frq value 25000.000000 in file 25000 is outside frq range
  (>0 - 22050[nyquist])`; 0 refused the same way; **5 Hz accepted** (ST's 20 Hz min is
  advisory; entry curates min 16 as a musical floor). Mode 2 (MIDI) verified incl.
  fractional 60.5; MIDI 200 refused via its converted frequency.
- **Template FILE form:** `220 440 880` in a text file runs (exit 0, distinct render) —
  a pitch SET (chord), NOT a time envelope. A time/value `.brk` is consumed as a flat
  value list (its 0.0 refused as a frequency). Inexpressible under the scalar schema;
  documented in the entry, execute() for chords.
- **Flags (range refusals verbatim):** focus `-f2` → `Parameter[2] … (0.000000 to
  1.000000)`; clarity `-c1.5` → `Parameter[3]` same; trace `-t5000` → `Parameter[4] …
  (1.000000 to 513.000000)` (= channel count, input-analysis-dependent); bcut
  `-b30000` → `Parameter[5] … (9.000000 to 22050.000000)`.
- **Defaults verified:** unflagged render data-identical to `-f1` (banner's focus
  default 1 confirmed); clarity default 0 (banner/manual).
- **Breakpoints:** ALL four flags accept brks (exit 0) — "All parameters may vary over
  time" (banner+manual); **focus brk verified to differ from both endpoint renders**.
  Flag order `-c` before `-f` tolerated.
- Deterministic (data chunk). Mono `.ana` in/out.

## 9. combine interleave — SHIPPED

**Working argv:** `combine interleave n2.ana n1.ana out.ana 1` — exit 0.

| inputs | leafsize | outdur (.ana) |
| ------ | -------- | ------------- |
| n2 (2 s) + n1 (1 s) | 1 | 1.026163 |
| n1 + n2 (reversed) | 1 | 1.026163 |
| n2 + tone2 (equal) | 4 | 2.029070 |
| n2 + tone2 + n1 (3 inputs) | 2 | 1.026163 |

- **duration_model:** `expression: indur_min` — order-independent; time advances through
  all inputs in parallel, the longer tail is discarded.
- **leafsize (verbatim):** `Parameter[1] Value (1000.000000/0.000000) out of range
  (1.000000 to 698.000000)` — max = the FIRST input's window count (698 = 2 s × 344;
  400 accepted with a 353-window output). Brk refused (`Cannot read parameter 1
  [leaf.brk]: brkpnt_files not permitted.`). leaf 1 vs 4 renders differ.
- **Refusals (verbatim):** wav inputs `Application doesn't work with this type of
  infile.`; single input `Insufficient input files for this process`.
- Deterministic (data chunk). Entry pins arity 2; 3+ inputs = execute().

## 10. combine max — SHIPPED

**Working argv:** `combine max n2.ana tone2.ana out.ana` — exit 0. No parameters.

| inputs | outdur (.ana) |
| ------ | ------------- |
| n2 (2 s) + tone2 (2 s) | 2.029070 |
| n2 (2 s) + n1 (1 s) | **2.029070** |
| n1 + n2 (reversed) | **2.029070** |
| n2 + tone2 + n1 (3 inputs) | 2.029070 |

- **duration_model:** `expression: indur_max` — the output runs to the LONGER input
  (order-independent). **Family DIVERGENCE worth pinning: interleave truncates to the
  shorter, cross runs to the shorter, max runs to the longer.**
- Refusals as interleave (`Insufficient input files…`, infile-type). Deterministic.

## 11. strange shift, mode 4 — SHIPPED

**Working argv:** `strange shift 4 n2.ana out.ana 200 100 8000` — exit 0 (SoundThread
`strange_shift_4`).

- **duration_model:** `static` (2.029070 / 1.026163 across shift ±, band variants).
- **Shift verified:** tone2 + frqshift 200 (band 300–8000) → resynth peak at exactly
  **640.0 Hz**.
- **Ranges (verbatim):** frqshift `Parameter[1] Value (30000.000000) out of range
  (-22050.000000 to 22050.000000)`; frqlo/frqhi `Parameter[2]/[3] … out of range
  (10.766602 to 22039.233398)` — a quarter channel-width inside 0/nyquist,
  analysis-settings-dependent. **frqhi < frqlo accepted silently** (distinct render, no
  warning).
- **Breakpoints:** frqshift brk (50→400) differs from both endpoint renders → capable;
  frqlo/frqhi brks exit 0 (banner: "frqshift, frq_divide, frqlo & frqhi may vary over
  time").
- **-l log interpolation:** byte-identical NO-OP on all-scalar runs; changes the render
  with a breakpointed frqshift (banner: time-varying only, values all +ve or all −ve).
- Mode 6 → `Program mode value [6] is out of range [1 - 5].`; wav input → infile-type
  refusal. Deterministic (data chunk). Submodes 2–3 use a different argv shape
  (frq_divide) — separate entries if curated.

## 12. distort interact — SHIPPED (submode 2 pinned)

**Working argv:** `distort interact 2 tone2.wav n2.wav out.wav` — exit 0. No numeric
parameters; mono only (banner + verbatim stereo refusal `Application doesn't work with
this type of infile.`).

| mode | input1 | input2 | outdur |
| ---- | ------ | ------ | ------ |
| 2 | tone2 (2 s) | n2 (2 s) | 1.997732 (−0.11% vs indur1) |
| 2 | tone1 (1 s) | n2 | 0.997732 |
| 2 | tone2 | n1 (1 s) | 1.997732 |
| 2 | **n2** | **tone2** | **0.078277** (collapsed) |
| 2 | n2 | tone1 | 0.039138 |
| 1 | n2 | n2-copy | 3.999932 (indur1+indur2 −0.002%) |
| 1 | n2 | n1 | 2.014218 |
| 1 | tone2 | n2 | 2.078277 |

- **Submode 2 pinned** (impose input1's wavecycle lengths on input2 — SoundThread
  `distort_interact_2`): **duration_model `expression: indur1`**, valid when input1 has
  FEWER wavecycles (the periodic/pitched sound first); the reversed pairing collapses
  to the duration of input1's first N₂ cycles — headline known-issue, the engine cannot
  enforce pairing.
- **Pseudo-pitch verified:** tone2-lengths-on-noise output's strongest FFT peak =
  **440.0 Hz** exactly.
- **Submode 1** (interleave): equal-material inputs → indur1+indur2; dissimilar
  densities collapse similarly (2.078 from tone+noise). Probed, documented, not shipped
  (one (program, mode) key per schema).
- Mode 3 → `Program mode value [3] is out of range [1 - 2].` Deterministic.

## 13. clip clip, mode 2 — SHIPPED

**Working argv:** `clip clip 2 tone2.wav out.wav 0.7` — exit 0 (SoundThread
`clip_clip_2`; `clip` prints no CDP version banner).

| input | fraction | outdur | note |
| ----- | -------- | ------ | ---- |
| tone2 | 0.7 | 2.000000 | sample-exact |
| n2 | 0.5 | 2.000000 | |
| tone1 | 0.3 | 1.000000 | |
| tone2 | 1 | 2.000000 | **byte-identical to input** |

- **duration_model:** `static` — sample-exact.
- **HEADLINE — output renormalised to full scale:** a 0.7-peak sine at fraction 0.7
  comes back with peak **1.000** (fraction 0.2 → 0.96): input level is not a drive
  control, and headroom must be restaged downstream (pair with the tranche-5
  loudness/mix overload findings).
- **fraction (verbatim):** `Parameter[1] Value (1.500000) out of range (0.000000 to
  1.000000)`; 0 → runtime `ERROR: INVALID DATA / ERROR: No distortion with a zero
  parameter value.` (curated min 0.01, ST's floor). Brk refused
  (`Cannot read parameter 1 [frac.brk]: brkpnt_files not permitted.`).
- **Mono only, CDP8-style refusal wording:** `ERROR: INVALID DATA / ERROR: File st2.wav
  is not of correct type (must be mono)` — differs from the Groucho-era infile-type
  string. Mode 3 → `Program mode value [3] is out of range [1 - 2].` Mode 1
  (clip-at-level) verified working, not pinned. Deterministic.

---

## Final row confirmations (exact pinned params)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| grain reverse (static), click2 2.0 s | 2.0 | 2.007506 | +0.38% |
| grain duplicate, repeats 2, 2.0 s (fixture flat noise) | 4.0 | 4.007234 | +0.18% |
| grain timewarp, ratio 1.0, 2.0 s (grainy AND fixture noise) | 2.0 | 2.000000 | 0.000% |
| grain rerhythm 1 (static), multfile `1.0`, click2 2.0 s | 2.0 | 2.000000 | 0.000% |
| grain reposition (static), source-matching timefile / offset 0, click2 | 2.0 | 2.000023 | +0.001% |
| pitch tune 1 (static), frequency 440, 2 s .ana | 2.0 | 2.029070 | +1.45% |
| combine interleave, n2.ana+n1.ana, leafsize 1, indur_min | 1.0 | 1.026163 | +2.62% |
| combine max, n2.ana+n1.ana, indur_max | 2.0 | 2.029070 | +1.45% |
| strange shift 4 (static), 200/100/8000, 2 s .ana | 2.0 | 2.029070 | +1.45% |
| distort interact 2, tone2+n2, indur1 | 2.0 | 1.997732 | −0.11% |
| clip clip 2 (static), fraction 0.7, 2.0 s | 2.0 | 2.000000 | 0.000% |

**Shipped (11):** grain reverse, grain duplicate, grain timewarp, grain rerhythm 1,
grain reposition, pitch tune 1, combine interleave, combine max, strange shift 4,
distort interact 2, clip clip 2.
**Not shipped (1):** grain scramble — verified nonexistent (no such grain mode; the
standalone seeded `scramble scramble` waveset program is recorded in §0 as the Phase 6
stereo-seed-linking trigger candidate, machinery not built).
