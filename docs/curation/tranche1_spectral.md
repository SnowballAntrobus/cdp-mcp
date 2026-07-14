# Tranche 1 — spectral curation probe transcript

Six SPECTRAL entries curated empirically against real CDP binaries:
`blur avrg`, `blur scatter`, `blur drunk`, `focus exag`, `combine diff`, `morph glide`.

## Test environment

- CDP binaries: **built from source at `/tmp/CDP8/NewRelease`** (Linux x86_64 sandbox);
  banners self-identify as "CDP Release 7.1 2016". Findings are to be re-verified on
  macOS r8 by the CDP-gated test suite when these rows are pinned.
- Source tree available at `/tmp/CDP8/dev` — used to confirm RNG seeding behavior at
  the source level (see blur scatter / blur drunk below).
- Probe inputs (generated, 16-bit PCM mono 44.1 kHz, synthetic gliss harmonics + light
  envelope so grabbed windows differ):
  - `in1.wav` 2.000 s, `in2.wav` 1.000 s, `in3.wav` 3.000 s, `stereo.wav` 1.0 s stereo.
- Analysis: `pvoc anal 1 inN.wav inN.ana` (defaults: 1024 points, overlap 3).
- Output verification: every `.ana` output resynthesised with `pvoc synth out.ana out.wav`;
  durations and sha256 taken from the wav's **decoded data chunk** (headers carry
  timestamps and tick between runs).
- Breakpoint probes: 2-point files (`0 <low>` / `<t_end> <high>`) substituted at the
  parameter's argv position, or attached to the flag (`-X<brk>` — no space), per the
  Phase 2 methodology (`docs/phase-2-breakpoint-review.md`).

### Channel constraint (shared)

`pvoc anal 1 stereo.wav stereo.ana` → exit 255,
`Application doesn't work with this type of infile.`
Stereo audio cannot even be analysed, so all six entries are `channel_constraint: "mono"`
at the .ana level (the refusal happens upstream at PVOC, not in the six programs).

---

## 1. blur avrg

Banner: `blur avrg infile outfile N` — "N must be ODD and <= half the -N param used in
original analysis. N may vary over time."

| argv | exit | synth dur | note |
| --- | --- | --- | --- |
| `blur avrg in1.ana av1.ana 9` | 0 | 2.0230 s | baseline (indur 2.0) |
| `blur avrg in3.ana av2.ana 9` | 0 | 3.0215 s | indur 3.0 |
| `blur avrg in1.ana av3.ana 21` | 0 | 2.0230 s | 2nd param value, same dur |
| `blur avrg in1.ana avE.ana 8` | 0 | — | **even N accepted** |
| `blur avrg in1.ana avX.ana 513` | 0 | — | **N > half points accepted** |
| `blur avrg in1.ana avB.ana b_avrg.brk` (`0 3` / `1.9 21`) | 0 | 2.0230 s | breakpoint accepted |

- **duration_model: static** — out ≈ indur + one analysis-frame pad (+1.2% / +0.7%,
  well inside 5%); param value does not affect duration.
- **breakpoint_capable: n = true** (exit 0, output resynthesises).
- **Determinism**: identical rerun → identical decoded sha (`587ca3347c8e1270`).
- **Divergence**: banner's ODD/<=half constraints are not enforced (even 8 and 513 both
  run clean); the HTML manual never mentions the odd rule at all.

## 2. blur scatter

Banner: `blur scatter infile outfile keep [-bblocksize] [-r] [-n]` — "keep & blocksize
may vary over time." No seed flag in banner or manual.

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `blur scatter in1.ana sc1.ana 8` | 0 | 2.0056 s | `f5005a87813988a2` |
| `blur scatter in1.ana sc1b.ana 8` (immediate rerun) | 0 | 2.0056 s | `f5005a87813988a2` |
| `blur scatter in1.ana sc1c.ana 8` (3rd run) | 0 | 2.0056 s | `f5005a87813988a2` |
| `blur scatter in1.ana scT2.ana 8` (rerun after `sleep 2.3`) | 0 | 2.0056 s | `f5005a87813988a2` |
| `blur scatter in1.ana scR1/scR2.ana 8 -r` (sleep 2.1 between) | 0 | 1.9998 s | `1f0ed6debb29b041` both |
| `blur scatter in3.ana sc2.ana 8` | 0 | 3.0157 s | indur 3.0 |
| `blur scatter in1.ana sc3.ana 24` | 0 | 2.0230 s | 2nd keep value |
| `blur scatter in1.ana scB.ana b_keep.brk` (`0 4` / `1.9 12`) | 0 | 2.0230 s | keep brk accepted |
| `blur scatter in1.ana scBS.ana 8 -b300` | 0 | — | blocksize scalar ok |
| `blur scatter in1.ana scBB.ana 8 -bb_blk.brk` (`0 100` / `1.9 800`) | 0 | 2.0230 s | blocksize brk accepted |
| `blur scatter in1.ana scN.ana 8 -n` | 0 | — | -n ok |

- **duration_model: static** (2.0→2.0056, 3.0→3.0157; keep 8 vs 24 same dur).
- **breakpoint_capable: keep = true, blocksize = true.**
- **Determinism/seed (HEADLINE)**: identical args → **bit-identical output on every run**,
  including runs separated by > 2 s and runs using `-r`. Chunk-level comparison of the
  `.ana` files shows only the `LIST` header chunk (creation date) differs; `fmt ` and
  `data` chunks are identical. Source confirmation: `scat_preprocess()`
  (`/tmp/CDP8/dev/blur/ap_blur.c`) never calls `initrand48()`; CDP's `drand48` shim
  (`dev/sfsys/osbind.c`) wraps unseeded `rand()`. **stochastic: false,
  phase_sensitive: false, seed_param: none exists.** The design doc's
  phase-sensitive/stochastic flag for this mode does not hold on this build.

## 3. blur drunk

Banner: `blur drunk infile outfile range starttime duration [-z]`. No "may vary" claims,
no seed flag.

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `blur drunk in1.ana dr1.ana 5 0.5 1.5` | 0 | 1.4977 s | `7ffae474170d526e` |
| `blur drunk in1.ana dr1b.ana 5 0.5 1.5` (rerun after `sleep 2.2`) | 0 | 1.4977 s | `0cd8d6894ccc27fb` **≠** |
| `blur drunk in1.ana dr2.ana 5 0.5 1.0` | 0 | 0.9985 s | |
| `blur drunk in1.ana dr3.ana 5 0.5 2.5` | 0 | 2.4990 s | |
| `blur drunk in3.ana dr4.ana 5 0.5 1.5` | 0 | 1.4977 s | indur 3.0, same outdur |
| `blur drunk in1.ana drX.ana 5 0.5 4.0` | 0 | 3.9996 s | **extension beyond indur** |
| `blur drunk in1.ana drZ.ana 5 0.5 1.5 -z` | 0 | — | -z ok |

Breakpoint refusals (raw text):

- range: `ERROR: Cannot read parameter 1 [b_rng.brk]: brkpnt_files not permitted.` (exit 255)
- starttime: `ERROR: Cannot read parameter 2 [b_stt.brk]: brkpnt_files not permitted.` (exit 255)
- duration: `ERROR: Cannot read parameter 3 [b_dur.brk]: brkpnt_files not permitted.` (exit 255)

Seed-flag probes: `-s1` → `ERROR: Unknown flag '-s'`; `-r1` → `ERROR: Unknown flag '-r'`.

- **duration_model: set_by `duration`** — outdur tracks the param within 0.25% at 1.0,
  1.5, 2.5, and 4.0 s, independent of indur (2 s and 3 s inputs identical); output may
  exceed the input duration.
- **breakpoint_capable: all three positionals = false** (raw refusals above).
- **Stochastic: TRUE** — identical argv twice → different decoded output. **No seed flag
  exists.** Source confirmation: `drnk_preprocess()` calls `initrand48()` which is
  `srand(time(NULL))` (`dev/sfsys/osbind.c:331`) — also implying two runs inside the same
  wall-clock second would silently produce identical output. `phase_sensitive: true`,
  `stereo_link_default: "related"`; known_issues records that the stereo seed-link
  machinery lands later and has no seed flag to drive for this program.

## 4. focus exag

Banner: `focus exag infile outfile exaggeration` — "exaggeration >0 will widen troughs:
<0 will widen peaks. exaggeration may vary over time."

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `focus exag in1.ana ex1.ana 2` | 0 | 2.0230 s | `a697cb3bf32a9036` |
| `focus exag in1.ana ex1b.ana 2` (rerun) | 0 | 2.0230 s | `a697cb3bf32a9036` = |
| `focus exag in3.ana ex2.ana 2` | 0 | 3.0215 s | indur 3.0 |
| `focus exag in1.ana ex3.ana 0.5` | 0 | 2.0230 s | 2nd param value |
| `focus exag in1.ana exN.ana -0.5` | 255 | — | see below |
| `focus exag in1.ana exB.ana b_exag.brk` (`0 0.5` / `1.9 2`) | 0 | 2.0230 s | brk accepted |

Negative-value refusal (raw):
`ERROR: Parameter[1] Value (-0.500000) out of range (0.001000 to 1000.000000)`

- **duration_model: static**; **breakpoint_capable: exaggeration = true**; deterministic.
- **Divergence (banner wrong, manual right)**: the banner's ">0 / <0" wording implies
  negative values are meaningful; CDP enforces 0.001–1000 and refuses negatives. Manual:
  "< 1 widens troughs and narrows formants (focuses on the peaks); > 1 narrows troughs
  and widens formants". min/max in the JSON are taken from the enforcement error text.

## 5. combine diff

Banner: `combine diff infile infile2 outfile [-ccrossover] [-a]` — "crossover may vary
over time."

| argv | exit | synth dur | note |
| --- | --- | --- | --- |
| `combine diff in1.ana in2.ana cd1.ana` | 0 | 2.0230 s | indur1=2, indur2=1 → **indur1** |
| `combine diff in2.ana in1.ana cd2.ana` | 0 | 1.0217 s | order reversed → **indur1** |
| `combine diff in1.ana in3.ana cd3.ana` | 0 | 2.0230 s | indur1=2, indur2=3 → **indur1** |
| `combine diff in1.ana in2.ana cd4.ana -c0.5` | 0 | 2.0230 s | data sha ≠ default |
| `combine diff in1.ana in2.ana cd5.ana -c1` | 0 | — | `.ana` data sha **== cd1** |
| `combine diff in1.ana in2.ana cd6.ana -a` | 0 | — | data sha ≠ default |
| `combine diff in1.ana in2.ana cd7.ana -cb_cross.brk` (`0 0` / `0.9 1`) | 0 | 2.0230 s | brk accepted |
| `combine diff in1.ana in2.ana cd1b.ana` (rerun) | 0 | 2.0230 s | decoded sha identical |

- **duration_model: expression `indur1`** — output duration equals input1's whether
  input2 is shorter (2+1→2.02) or longer (2+3→2.02), and reversing the order flips it
  (1.02). **Divergence from `combine cross`'s `indur_min`.**
- **Default crossover = 1.0**: omitted `-c` and `-c1` produce bit-identical `.ana` data
  chunks (`ac61e64b5c2795be`). Matches SoundThread's default (1.0).
- **breakpoint_capable: crossover = true**, `breakpoint_duration_source: "input1"` —
  input1's duration is the output timeline, so envelopes scale against it (also matches
  combine_cross's convention). `subzero` (-a) is a no-value switch, verified effective
  (different output data).
- Deterministic (`600026e80a8c1069` twice).

## 6. morph glide

Banner: `morph glide infile infile2 outfile duration` — "INFILE1, INFILE2 are
single-window analysis files extracted with spec grab."

Window prep: `spec grab in1.ana g1.ana 0.5`, `spec grab in2.ana g2.ana 0.3`
(single-window .ana files, 6 174 bytes each).

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `morph glide g1.ana g2.ana mg1.ana 1.0` | 0 | 0.9985 s | `614184b335ea5084` |
| `morph glide g1.ana g2.ana mg1b.ana 1.0` (rerun) | 0 | 0.9985 s | `614184b335ea5084` = |
| `morph glide g1.ana g2.ana mg2.ana 2.0` | 0 | 1.9969 s | |
| `morph glide in1.ana in2.ana mgF.ana 1.0` (full-length inputs) | 0 | 0.9752 s | `793dd18194116ab3` |
| `morph glide g1z.ana g2z.ana mgZ.ana 1.0` (grabs at t=0) | 0 | 0.9752 s | `793dd18194116ab3` **= mgF** |

Breakpoint refusal (raw):
`ERROR: Cannot read parameter 1 [b_gdur.brk]: brkpnt_files not permitted.` (exit 255)

- **duration_model: set_by `duration`** (0.15% / 0.16% error at 1.0 / 2.0 s; the
  single-window inputs contribute no duration of their own).
- **breakpoint_capable: duration = false** (raw refusal above). No breakpoint-capable
  params → no `breakpoint_duration_source` required on this 2-input entry.
- Deterministic.
- **Divergence (manual requirement unenforced)**: full-length .ana inputs are accepted
  with exit 0, and the result is byte-identical to gliding between each file's first
  window (`spec grab ... 0`). The "must be spec grab output" rule is a convention CDP
  does not check; the entry's known_issues directs users to grab explicitly.

---

## Headline findings

1. **blur scatter is NOT stochastic run-to-run** (design doc flagged it as a
   phase-sensitive candidate): its RNG is never seeded — identical args give bit-identical
   output every run, `-r` included. Verified empirically (sleeps > 2 s) and in source
   (`scat_preprocess()` lacks `initrand48()`). No seed flag exists.
2. **blur drunk IS stochastic and unreproducible**: `srand(time(NULL))` at preprocess,
   no seed flag (`-s`/`-r` rejected). Same-second reruns would collide; otherwise every
   run differs. Entry ships `phase_sensitive: true`, `stereo_link_default: "related"`.
3. **combine diff's output duration is `indur1`**, not `indur_min` — input order changes
   output length, unlike combine cross. Default `crossover` empirically pinned at 1.0.
4. **focus exag banner is wrong about sign**: negatives refused, enforced range
   0.001–1000 (taken into the JSON as min/max).
5. **blur avrg's ODD-N / half-points constraints are unenforced** (8 and 513 both run).
6. **morph glide accepts full-length .ana silently**, using only the first window —
   byte-identical to grabbing at t=0.
