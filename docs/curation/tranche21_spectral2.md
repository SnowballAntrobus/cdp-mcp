# Tranche 21 — spectral tail II (heavy/multi-input spectral) probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (-fsigned-char rebuild; banners "CDP Release 7.1 2016"
  where printed), Linux x86_64 sandbox. Source consulted at `/tmp/CDP8/dev`
  (`standalone/specross.c`, `new/newmorph.c`, `new/spectwin.c`, `new/superaccu.c`).
- **Fixtures:** `/tmp/probe21b`, python-soundfile, mono 44100 Hz float32.
  - `qa2/qa3/qb15/qc2.wav` — ATTACK-SHAPED harmonic tones (10 ms attack, exp decay to
    0.35): 220 Hz 2.0/3.0 s, 330 Hz 1.5 s, 277.18 Hz 2.0 s. (First-round AM-enveloped
    tones `pa*/pb*` put the "attack" at 1.78 s and tripped specross's attack gate —
    kept as the gate probe.)
  - `det2.wav` — 228 Hz harmonic tone (between A3/A#3) for spectune.
  - `vow2.wav` — 110 Hz vowel-'a' formant synth (F1 700 / F2 1220 / F3 2600).
  - `n2.wav` — flat uniform noise +-0.5.
  - `.ana` via `pvoc anal 1` defaults. Round-trip durations: 2.0 s → 2.0230,
    1.5 s → 1.5209, 3.0 s → 3.0215.
- **Method:** tranche-2 verbatim. .ana durations measured via `pvoc synth` round-trips
  (never sf.info on .ana); repeat-run comparisons on DATA chunks (helper `an.py` — the
  .ana/.for header carries a DATE stamp that always differs). Unseeded pairs > 1.1 s apart.
- **PINNED RULE (multi-input duration rows):** 2-input entries are incompatible with the
  single-input duration fixture — findings rows are `null` with the verified model in
  `duration_row_reason` (morph bridge precedent).

Refusals quoted verbatim (stdout, exit 255 unless noted).

---

## 1. specross partials (CURATED — the prize)

Working argv: `specross partials qa2.ana qb15.ana out.ana 1 2 80 5 50 2000 0.1 1 0.5` — exit 0.

- **DURATION = indur2, always** (pvoc synth round-trips): (2.0, 1.5) → 1.5122;
  (1.5, 2.0) → 2.0114; (3.0, 1.5) → 1.5122 (≈1 window short of indur2; infile1's
  length never matters). Source: `interp_spectra()` loops over infile2's windows and
  writes one output window per infile2 window.
- **Engine (source-read):** output keeps infile2's partial frequencies; NON-harmonic
  channels ZEROED (`spec_interp`); harmonic amps interpolated src2→src1 by `interp`
  (`get_newlevel`: `diff = (src1level - src2level) * interp`); `level` scales src1's
  contribution.
- **ATTACK GATE:** AM-enveloped infile1 (attack at 1.782 s) vs 1.5 s infile2 →
  `ERROR: Attack time on 1st source is at or beyond end of 2nd.` plus
  `WARNING: Attack time of 1st sound not close to start of sound (duration 2.026 secs).`
- **Ranges (all refusal-probed, verbatim):** tuning `(0.000000 to 6.000000)`; minwin
  `(0.000000 to 525.000000)` (input-dependent window count); signois `(0.000000 to
  1000.000000)`; harmcnt `(1.000000 to 8.000000)`; lo/hi `(10.000000 to 2756.250000)`
  (nyquist/8, input-dependent); thresh/level/interp `(0.000000 to 1.000000)`;
  lo ≥ hi → `ERROR: Impossible pitch range specified.`
- **Breakpoints:** interp brk (0→1) exits 0 and differs from BOTH scalar endpoints and
  from 0.5 → **capable**; source `read_data_from_interp_file` RESCALES brk times to
  infile2's duration (first time must be 0, times advance, values 0-1, `;` comments,
  single pair collapses to scalar) → `breakpoint_duration_source: input2`.
  Params 1-8 refuse: `Cannot read parameter N [...]: brkpnt_files not permitted.`
- **UNDOCUMENTED FLAGS:** source `set_vflgs(..., "ap", 2, 0, "00")` — `-a`
  (AMP_SCALING, standalone.h:433) changes output (verified); `-p` accepted,
  byte-identical no-op on the probes.
- Deterministic (repeat data chunks identical). Wav input refused
  (`File qa2.wav is not of correct type`). Per-window `0 min X.XX sec` stdout spam +
  `WARNING: failed to write PEAK data` on every run (family-wide, harmless).
- **Engine spot-check (process_impl, two wavs, auto-PVOC):** ok; outdur 1.5209 = indur2.

## 2. newmorph newmorph 1 (CURATED — the other prize) + modes 2-7

Working argv: `newmorph newmorph 1 qa2.ana qb15.ana out.ana 0 0.5 1.5 1 4` — exit 0.

| pair (indur1, indur2) | stagger | flags | outdur | model `stagger + indur2` |
| --- | --- | --- | --- | --- |
| (2.0, 1.5) | 0 | | 1.5209 | 1.5209 |
| (1.5, 2.0) | 0 | | 2.0230 | 2.0230 |
| (2.0, 1.5) | 0.5 | | 2.0201 | 2.0209 |
| (1.5, 2.0) | 0.5 | | 2.5223 | 2.5230 |
| (2.0, 1.5) | 0.5 | -e | 2.0201 | min(2.0209, 2.0230) |
| (1.5, 2.0) | 0.5 | -e | **1.5209** | min(2.5230, **1.5209**) |
| mode 5, (2.0, 1.5) | 0.5 | | 2.0201 | rule holds across modes |

- **duration_model:** `stagger + indur2`; `-e` cuts at infile1's end →
  min(stagger + indur2, indur1). Verified as above.
- **Ordering constraints (verbatim):** stagger 0.9 / startmorph 0.5 →
  `ERROR: start of amp interpolation is set before entry of 2nd soundfile.`;
  endmorph 1.9 on the (2.0, 1.5) pair (and 5.0 anywhere) →
  `ERROR: end of interpolation is beyond end of one of soundfiles.`
- **Ranges (verbatim):** stagger `(0.000000 to 2.023039)` (= indur1); exponent
  `(0.020000 to 50.000000)`; peaks `(1.000000 to 16.000000)`.
- **Breakpoints:** all five positional slots refuse (`Cannot read parameter 1
  [b_exp.brk]: brkpnt_files not permitted.` on stagger; all 5 probed → INCORRECT USE).
- Modes 1-6 all run, all six shas distinct; `-n`/`-f` change output. Deterministic
  (identical repeat data chunks).
- **MODE 7 DROP:** `newmorph 7 ... nm7.ana 4 3` writes `nm70.ana nm71.ana nm72.ana`
  (outcnt numbered files) — multi-output, no single-outfile argv.

## 3. newmorph newmorph2 1 & 2 (both CURATED)

- **Mode 1 (peaksfile extractor):** `newmorph2 1 qa2.ana pk_a.txt 6` → 6 lines, one
  peak frequency per line, most prominent first: `157.016924 / 81.590736 / 76.337778 /
  54.753339 / 48.560505 / 47.812285` (spectral-envelope peaks, not the fundamental).
  peakcnt refusals at 0/17: `(1.000000 to 16.000000)`. Deterministic. Data out (.txt).
- **Mode 2 (tune to peaksfile):** `newmorph2 2 qb15.ana out.ana pk_a.txt 0.3 1.2 1 6`
  — exit 0. **Static duration** (1.5209→1.5209, 2.0230→2.0230). Mode 3 runs, distinct
  sha (cosinusoidal). endmorph 5 on a 1.5 s file **ACCEPTED** (unlike the 2-input
  modes). peakcnt 8 vs a 6-line file accepted. exponent `(0.020000 to 50.000000)`;
  `-r2` → `(0.000000 to 1.000000)`. startmorph brk refused (`Cannot read parameter 2`).
  **-r0.5 deterministic** (two runs 1.3 s apart byte-identical — no live seed) and
  output-changing vs base.
- Landmine met: CDP refuses to overwrite outputs (`Cannot open output file _t.ana`) —
  stale-name trap; probes redone with fresh names.

## 4. spectwin (CURATED submode 4)

Working argv: `spectwin spectwin 4 qa2.ana qb15.ana out.ana` — exit 0.

- **DEFAULT TRAP (first-class):** frqint/envint default 1.0 ⇒ output = infile2
  VERBATIM. Verified: mode-1 render with `qa2.ana` as infile1 is byte-identical to the
  render with `vow2.ana` as infile1 (sha f7a4e883dc2a4256 both) — infile1 ignored.
  Source (`spectwin.c` case 3): `amp = amp1*(1-ei) + amp2*ei; frq = frq1*(1-fi) + frq2*fi`.
- **Mode coincidences at defaults:** modes 1/3 byte-identical (file2's formant env) and
  2/4 byte-identical (file2 verbatim); the file-1 side of the mode choice only matters
  when envint < 1.
- **-f/-e BREAKPOINT BUG (first-class):** brkfiles ACCEPTED (bogus path
  `-fnosuchfile.brk` → exit 255, so the file IS parsed) but values NEVER applied —
  `-f` with 0→1 ramp, `-e` ramp, and a CONSTANT-0 file all render byte-identical to the
  flag-less default (not even the first value); `-f0` scalar differs. Source: fi/ei
  snapshotted into locals before `read_values_from_all_existing_brktables` runs.
- **duration = min(indur1, indur2):** (2.0,1.5)/(1.5,2.0) → 1.5209 both; (3.0,2.0) →
  2.0230. Source: `ssampsread = min(sampsread0, sampsread1)`.
- **Ranges (verbatim):** -f/-e `(0.000000 to 1.000000)`; -d `(0.000000 to 8.000000)`;
  -s `(0.000000 to 48.000000)`; -r `(0.000000 to 1.000000)`. `-d3 -s7 -r0.7`
  byte-identical no-op at default weights (dupl modifies infile1 only); differs at
  `-f0 -e0`. Deterministic (repeat -f0.5 -e0.5 identical).

## 5. selfsim (CURATED)

`selfsim selfsim qa2.ana out.ana 1` — exit 0. Static (2.0230→2.0230, 3.0215→3.0215,
vowel too). Param refusals at 0/1000: `(1.000000 to 697.000000)` (input window count).
Brk refused (`Cannot read parameter 1`). Deterministic. Wav refused.

## 6. superaccu (CURATED submode 1)

`superaccu superaccu 1 qa2.ana out.ana [-ddecay] [-gglis] [-r]` — exit 0.

| input (indur) | decay | outdur | tail | implied ln(eps) |
| --- | --- | --- | --- | --- |
| qa2 (2.023) | (default) | 4.8268 | 2.8038 | −12.91 |
| qa2 | 0.01 explicit | 4.8268 | 2.8038 | — (== default ⇒ default IS 0.01) |
| qa2 | 0.1 | 7.6800 | 5.6570 | −13.03 |
| qa2 | 0.3 | 12.8900 | 10.8670 | −13.08 |
| qa2 | 0.5 | 20.9705 | 18.9475 | −13.13 |
| qa3 (3.022) | 0.1 | 8.6727 | 5.6512 | tail indur-independent |
| n2 noise (2.023) | (default) | 5.4248 | 3.4018 | −15.7 (content-dependent!) |
| n2 noise | 0.1 | 8.9252 | 6.9022 | −15.9 |

- **DEFAULT DIVERGENCE (first-class):** banner `Default 1.0 (no attenuation)`; source
  `ap->default_val[SUPACDECAY] = 0.01` (superaccu.c:729) and range caps at 0.9 —
  "no attenuation" is illegal. Flag-less == `-d0.01` (durations identical).
- **duration_model:** `indur + 14.5 / (10000 * (1 - decay**0.0001))` (ln-free
  approximation of `indur + 14.5/-ln(decay)`); tail ends at an ABSOLUTE float-zero
  threshold (`flteq(sum, 0.0)` in the tail loop) ⇒ CONTENT-DEPENDENT ±~20% (noise rings
  longer). Findings row rel_tol 0.20.
- **decay brk-capable** (out-of-range value inside a brk range-checked verbatim
  `Value (0.000000) out of range (0.000010 to 0.900000) in brkpntfile b_fi.brk.`;
  valid 0.5→0.8 ramp runs → **61.7157 s** from 2 s). **glis brk-capable** (differs from
  scalar). Brk tables keep being read through the tail.
- Ranges: decay 0/0.95 refused `(0.000010 to 0.900000)`; `-g12` accepted (banner
  "approx -11.7 to 11.7"; source bound MAXGLISRATE/frametime). `-g2` changes content
  not duration; `-r` byte-identical no-op even with -g2 on this source (source: active
  only when a glissing band finds a quieter better channel).
- **Modes 3/4 tuning file takes MIDI, not Hz (divergence):** `220` refused
  `ERROR: Pitch out of range (10.000000 - 14700.000000) : line 1: file tun1.txt`;
  MIDI file `57/61.7/64` runs (modes 3 and 4, distinct shas). Mode 2 runs (tempered).
- Deterministic. **Engine spot-check:** decay 0.1 → 7.68 vs model 7.67.

## 7. spectune (CURATED tune 1)

`spectune tune 1 det2.ana out.ana` — exit 0;
`INFO: Transposing from MIDI 57.62 to 58.000000 : by ratio 1.022113` (228 Hz → A#3).
Static (2.0230→2.0230). Deterministic (repeat identical). `-f` changes output.
Ranges: `-m0` → `(1.000000 to 8.000000)`; `-i13` → `(0.000000 to 6.000000)`; `-n` brk →
`Cannot read parameter 8 [...]: brkpnt_files not permitted.` Noise is still "tuned"
(found MIDI 97.50, ratio 1.029210 — no unpitched refusal).
**Mode 4 INFO-ONLY:** with an outfile arg → `Unknown parameter 'st4.txt'` (exit 0, no
file); without → prints `INFO: 57.621337`. Engine-incompatible; pinned in known_issues.

## 8. tunevary (CURATED)

`tunevary tunevary qa2.ana out.ana ptmp1.txt [-f -c -t -b]` — exit 0 with template
`0 57 64 69 / 1.5 57 64 69`. Static (2.0230/3.0215). Deterministic. All four flags
output-changing as scalars.

- **BANNER DIVERGENCE (first-class): "All parameters may vary over time" is false.**
  - `-f` brk (0.2→1.0 ramp, constant 0.2, step file): ALL byte-identical to flag-less
    default; `-f0.2` scalar differs. Ignored.
  - `-b` brk (constant 300): byte-identical to default; `-b300` scalar differs. Ignored.
  - `-c` brk: changes output but constant-0.5 brk ≠ `-c0.5` scalar (both ≠ default).
  - `-t` brk: changes output but constant-4 brk ≠ `-t4` scalar.
  All four curated scalar-only.
- Ranges (verbatim): `-f2`/`-c2` → `(0.000000 to 1.000000)`; `-t0` →
  `(1.000000 to 513.000000)` (channel count); `-b30000` → `(9.000000 to 22050.000000)`.
- Template refusals: non-increasing times → `ERROR: Input data times do not increase at
  line 2`; unequal entries → `ERROR: Line 2 has different number of entries to previous
  lines`.
- **Engine spot-check (aux in session data/):** ok.

## 9. peak (CURATED extract 4)

`peak extract 4 qa2.ana out.txt 3 5 0.001 50 4000` — exit 0; output one
`frq<TAB>amp` line per stream, loudest = 1.0 (6 streams on the probe tone).
`-f` → 2-row varibank (times 0 and 1000, verified); `-m` → MIDI values; `-h1`
accepted. Deterministic (byte-identical text). Ranges (verbatim): winsiz
`(1.000000 to 96.000000)`; peak `(1.000000 to 1000.000000)`; floor
`(0.000100 to 1.000000)`; lo/hi `(43.066406 to 22050.000000)` (chanwidth-nyquist,
input-dependent). Brk refused (parameter 1). Reserved extension:
`ERROR: Cannot open a textfile (pko.wav) with a reserved extension.`
**Engine spot-check (data output):** ok, content verified.

## 10. get_partials (CURATED harmonic 3)

`get_partials harmonic 3 qa2.ana out.txt 220 0.01 0.5` — exit 0; `frq  amp` per
harmonic, fundamental-normalised (`220 1.000 / 440 0.488 / 660 0.310 ...` — textbook
1/h). Mode 4 = MIDI (`57.0 1.0 / 69.0 0.488 ...`); `-v` = varibank2 blocks
(`0 220.0 1.0 / 100000 220.0 1.0 / #`). Modes 1-2 refuse multi-window files:
`ERROR: This mode only works with single-window analysis files`. Deterministic.
Ranges (verbatim): fundamental `(10.000000 to 22050.000000)`; threshold
`(0.000002 to 1.000000)`; time `(0.000000 to 2.025941)` (input-dependent). Brk refused
(parameter 1).

## 11. specanal (CURATED specanal 1); modes 2-6/9 pinned

`specanal specanal 1 qa2.wav out.ana 1024 3` — exit 0; wav→ana. Static-ish
(2.0→2.0027 at 1024/3, 2.0085 at 1024/1; 3.0→3.0012). Deterministic. Mono only
(`must be mono` verbatim); .ana input refused.
**chs DIVERGENCE:** banner "multiple of 4 (4 - 32768)"; binary enforces
`(2.000000 to 32768.000000)` (refusal at 40000) and accepts 5 and 2 (both resynthesise).
ovlp refusal at 5: `(1.000000 to 4.000000)`.
**Siblings:** mode 2 wrote **690** per-window textfiles (multi-output — drop); mode 9
**SEGFAULT** (exit 139); modes 7 (127-line semitone-bin levels), 8 (HF varibank/MIDI),
10 (time-varying HF varibank) write single textfiles — execute()-usable, uncurated.

## 12. oneform (CURATED get + put 2; combine deferred)

- `formants get vow2.ana vow2.for -f4` → .for (366 KB). Flag-less formants get refuses
  `Insufficient parameters on command line`.
- **oneform get extension trap:** output named `.txt` → file written as
  `vow_1f.txt.wav`; bare name → `.wav` appended; `.for` name KEPT (v1f.for). The 1f
  file is a RIFF/WAVE container. time refusals at 5/-1: `(0.000000 to 2.025941)`.
  Repeat runs differ ONLY at the header DATE (`CDB3586A` vs `0CB4586A`); data chunks
  identical → deterministic.
- **oneform put argv:** 1f file sits BETWEEN input and output
  (`oneform put 2 in.ana v1f.for out.ana`) — pre_output aux; my first
  outfile-before-aux attempt refused `cannot open input file ofp1.ana to read data.`
  Modes 1/2 run, distinct shas; static (2.0230/3.0215); deterministic;
  `-l200 -h6000 -g2` changes output. `-h23000` → `(5.000000 to 22050.000000)`;
  **-g0 ACCEPTED** (no lower bound); `-g` brk refused (parameter 3). .ana in the 1f
  slot → `ERROR: Second fvile is not a formant file` (binary typo verbatim).
- **oneform combine deferred:** needs a binary pitchfile from the uncurated repitch
  layer (tranche 22).

## 13. fturanal (CURATED anal 1 + synth 1)

- **anal:** `fturanal anal 1 vow2.ana ftr1.txt marks1.txt` (marks 0/0.3/0.8/1.2/1.6) —
  exit 0; 5-row feature file (times+dur, F1, F2, F3, brightness rows — verbatim content
  in the findings aux). **Modes 2 and 3 SEGFAULT** (exit 139, zero-byte outputs;
  reproduced with two marklists and two sources). `-r2` →
  `(0.000000 to 1.000000)`; `-r0.5` byte-identical across runs AND to the base
  (deterministic, no-op on the probe). Deterministic.
- **synth:** `fturanal synth 1 vow2.wav out.wav ftr1.txt` — exit 0, 1.9800 s from
  2.0 s (−1.0%, splice losses), mono, −11.3 dBFS, deterministic. `-s20` →
  `(2.000000 to 15.000000)`. Feature times past the wav end →
  `WARNING: Times at or beyond end of sndfile (2.000000) in file ftr1.txt. Ignoring
  them.` (normal on anal→synth chains: .ana times overshoot by one window).
  **Banner gap:** mode list skips 8 but mode 8 RUNS; mode 11 →
  `Program mode value [11] is out of range [1 - 10].`

## 14. DROPS (evidence)

- **speculate:** `speculate speculate qa2.ana spc 200 2000` → exit 0, **84 numbered
  files** (spc0.wav ... spc83.wav) from a "Plain Bob" permutation sequence — generic-
  name multi-output, no outfile argv. Drop per precedent.
- **specgrids:** `specgrids qa2.ana sg 2 8` → writes `sg0.ana sg1.ana` (outfilecnt
  numbered files) — multi-output. (changrouping range verbatim
  `(1.000000 to 256.000000)`.) Drop; afta8 also comments it out as
  "[Doesn't work - multiple outs]". Manual: identical to SPECNU SLICE mode 1.
- **specvu:** BOTH modes crash with heap corruption — `specvu: malloc.c:2617:
  sysmalloc: Assertion ... failed.` / SIGABRT (exit 134), outputs ZERO-BYTE (modes 1
  and 2, repeated). Would fail non-empty data verification even if the crash were
  tolerated. Drop.
- **features:** mode 1 exits 0 but writes ZERO-BYTE .txt on both the vowel and tone
  probes (fails non-empty data verification — the getlevel-2 precedent); mode 2 writes
  NUMBERED files (`f2out0.txt`); mode 3 exit 255; modes 4-6 take NO outfile argv and
  print to stdout (mode 4 verified). Drop.
- **newmorph newmorph 7**, **specanal 2-6/9**, **spectune 4**, **fturanal anal 2-3** —
  submode-level drops recorded in their entries (multi-output / segfault / info-only).

## Final row confirmations (engine spot-checks, process_impl real CDP)

| check | result |
| --- | --- |
| specross partials, two wavs (2.0, 1.5), auto-PVOC | ok; outdur 1.5209 = indur2 |
| peak extract 4 (data out) | ok; .txt content `223.48 0.105 / 893.31 0.228 / 1120.23 0.982 ...` |
| superaccu 1, decay 0.1 | ok; outdur 7.68 vs model 7.67 (+0.1%) |
| tunevary + ptmp1.txt aux in session data/ | ok |
| Loader | zero malformed warnings; all 16 triples resolve exactly |
