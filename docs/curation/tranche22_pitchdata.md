# Tranche 22 — pitch/repitch pitch-data family probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (-fsigned-char rebuild, banners "CDP Release 7.1 2016"),
  Linux x86_64 sandbox. To be re-verified on macOS r8 by the CDP-gated suite after integration.
- **Fixtures:** synthesized in `/tmp/probe22a` via python-soundfile, all mono 44.1 kHz float32,
  30 ms edge ramps, 10 harmonics with 1/h^1.2 rolloff:
  `vow` (steady 220 Hz, 2.0 s), `glide` (exponential 220→440 Hz, 2.0 s), `mid` (330 Hz, 1.5 s),
  `wob` (261.63 Hz with ±1.5 st sine wobble at 1 Hz, 2.0 s — the quantise/transfer target),
  `noise` (white, 2.0 s), plus `/tmp/probe/tone2.wav` (440 Hz sine). All pvoc-anal'd
  (`pvoc anal 1`, defaults: 1024 points / overlap 3 → window rate 344, 698 windows for 2.023 s).
- **Methodology:** tranche-2 verbatim. `.frq`/`.trn`/`.evl`/`.ana` comparisons are DATA-chunk
  sha256 only (the LIST chunk carries a DATE — raw bytes always differ). Unseeded pairs launched
  > 1.2 s apart. Refusals quoted verbatim (exit 255 unless noted).
- **Engine facts that shaped this tranche** (pinned before probing): `schema.output_format` has
  no binary pitch-data member (`.wav/.ana/.evl/.for/.txt` only) — every producer of binary
  pitch/transposition data is inexpressible as an entry output on the current schema;
  `validate_params._check_type` rejects caller-supplied plain strings for non-aux params
  (only aux_file paths, `.brk` paths, numbers, bools, breakpoint lists pass) — the same wall
  that silently dead-ends `grain reorder`'s required `code` str param (pre-existing, worth an
  integrator look). Both gaps drove the curation shapes below.

---

## 1. Binary pitch-data format pin (.frq / .trn / .evl)

`repitch getpitch 1 vow.ana vowtone.ana vow.frq -z` → exit 0. `xxd` + chunk walk:

- **Container:** RIFF/WAVE; `fmt` 18 bytes, format 3 (IEEE FLOAT), 1 channel,
  "sample rate" = **analysis window rate** (0x158 = 344), block align 4, 32 bit.
- **LIST adtl note properties** (`sfif` block): `orig channels`, `original sampsize`,
  `original sample rate`, `arate`, `analwinlen` (1024), `decfactor`, **`is a pitch file`**, `DATE`.
- **data chunk:** one float32 **Hz value per analysis window** (698 values for 2.023 s).
  **Markers: -1.0 = unpitched window (only with `-z`), -2.0 = silence.**
  vow.frq with -z: first5 `[-2, -1, -1, -1, 218.371]`, 8 negatives; without -z: `[-2, 218.371, ...]`,
  1 negative — unpitched windows interpolated through, the -2 silence marker survives.
- **.trn** (repitch combine/quantise 2/...) = same container with **`is a transpos file`**;
  ratios per window. **repitch analenv output** = same container with **`is an envelope`** —
  the SAME property as `envel extract`'s `.evl` (window size prop = 2.9 ms anal grain vs
  extract's wsize) → analenv's declared `.evl` output format is honest (see §8).

## 2. repitch getpitch (modes 1 and 2) — CURATED (submodes 1, 2)

Working argv: `repitch getpitch 1 in.ana outtone.ana pfil [-tR -gM -sS -nH -lL -hT -a -z]`;
mode 2 same shape with a TEXT bfil and `-d` instead of `-z` (`-z` in mode 2 refused
`ERROR: Unknown variant flag -z`).

- **Two outputs:** the resynthesizable pitch-trace tone (.ana, same window count as input —
  resynth peak 219.5 Hz / RMS 0.82 from the 220 Hz source; wobtone follows the wobble) and the
  pitch-data side file (binary .frq mode 1 / time-TAB-Hz text mode 2).
- **Mode-2 text is DATA-REDUCED:** steady vow → 2 lines; the 220→440 glide → 2 lines at the
  default `-d0.25` but **298 lines at `-d0.01`**; `-d` CDP-enforced
  `Parameter[8] Value (0.000000) out of range (0.000020 to 12.000000)`.
- **GARBAGE-THROUGH (first-class):** white noise does NOT refuse — exit 0 with a spurious
  294–1192 Hz track (mode 1 and 2 both). No "No valid pitch found." was ever printed on this
  build. Content responsibility is the caller's; `-s/-n/-g` are the guards.
- **Ranges verbatim:** `-t` `(0.000000 to 6.000000)` [Param 2]; `-s` `(0.000000 to 1000.000000)`
  [4]; `-n` `(1.000000 to 8.000000)` [5]; `-l`/`-h` `(10.000000 to 2756.250000)` [6/7]
  (nyquist/8, input-dependent); `-g0` accepted.
- **`-a` live** (data chunk differs); **`-z` semantics verified** (§1).
- **Overwrite refusal verbatim:** existing pfil → `ERROR: INVALID DATA` /
  `ERROR: Cannot open output pitch file d1.frq`. Subdirectory side paths work (`sub/s.frq`,
  dir pre-existing).
- **Determinism:** .frq data chunks byte-identical 1.2 s apart.
- **ENGINE SHAPE (the side-output pattern):** entry output = the tone .ana; the side filename
  rides a positional `str` param declared before the flags. The engine's str-param wall
  (see Environment) means the value is **pinned to its curated default**
  (`pitch_trace.frq` / `pitch_trace.txt`) — callers omit it; custom names are execute()-only.
  One live trace per name per session (CDP never overwrites); the side file is not in lineage
  and not re-created on cache hits. All documented in the entries.

## 3. The transform layer (approx/exag/invert/quantise/randomise/smooth/vibrato/cut/fix/interp/pchshift/insertzeros/insertsil/pitchtosil/noisetosil) — ALL DROPPED (schema gap), all verified running

Every one of these takes a pitchfile as its typed MAIN INFILE and writes a binary pitchfile
(mode 1-style) or binary transposition file (mode 2-style). Verified: **text pitch data in the
infile slot refuses** `Application doesn't work with this type of infile.` (vibrato probe) —
binary in, binary out, and `output_format` has no binary pitch member → inexpressible as
entries. All 15 verified exit 0 with RIFF outputs (argv pinned in findings): approx 1,
exag 1 (60 2.0), invert 1 (map 0), quantise 1/2 (q-set file), randomise 1 (3 200), smooth 1
(300), vibrato 1 (6 1), cut 3 (0.5 1.5), fix (-i), interp 1, pchshift (7), insertzeros 1 /
insertsil 1 (time-pair file), pitchtosil, noisetosil.

- **randomise is stochastic and UNSEEDABLE** (no seed argv; runs 1.3 s apart differ).
- **quantise verified musically** end-to-end through chain B (§10).
- Integrator candidate: adding `.frq`/`.trn` to `DATA_OUTPUT_FORMATS` + the Literal would
  unblock this entire layer as arity-0 data→data entries (the consuming side already works
  via aux_file).

## 4. repitch combineb — CURATED (submode 1); combine, combineb 2/3 dropped

`repitch combineb 1 pitchfile pitchfile2 outtbrkfile [-dI]` → TEXT time/ratio pairs.

- **First slot must be BINARY** (`Application doesn't work with this type of infile.` with text
  first — verbatim); second slot takes binary OR text (both verified). Banner pins the reason:
  "It's IMPOSSIBLE to generate binary outfile from exclusively brkpnt infiles."
- **Content:** ratios = pitch2/pitch1 (218.4 Hz steady vs wob → ratio 1.127 at 0.91 s;
  218.37 × 1.127 = 246.1 vs wob's 247.2 there ✓). 16 lines default, 9 at `-d2`
  (banner's "Range > 1.0" for -d is wrong — 0.5 accepted). Deterministic (byte-identical).
- **Siblings verified, dropped as attrition:** mode 2 (pitch + transposition → pitch text;
  218.4 × ratio track → 257.7 Hz first line ✓), mode 3 (ratio × ratio → 1.18² = 1.39 ✓);
  `repitch combine` 1 runs (binary .trn out — schema-blocked; its .trn drives transposef 4).

## 5. repitch transposef — CURATED (submodes 3 and 4)

Banner: `transposef 1-3 infile outfile -fN|-pN [-i] transpos [-l][-h][-x]`;
`transposef 4 infile transpos outfile -fN|-pN [-i] [-l][-h][-x]`.

- **-f/-p REQUIRED:** mode 3 without → `Formant parameter missing on cmdline.`;
  mode 4 without → `Insufficient parameters on command line`. Entries hard-default `-p8`
  (SoundThread's transposef_3 value; range 1–12: `-p13` refused
  `Too many formant_bands requested: max for this file is 12`; `-p0` accepted by the binary,
  curated out; `-f0` crashes `INTERNAL ERROR ... set_specenv_frqs()` — vocode precedents hold).
- **ARGV-ORDER LANDMINE (first-class, engine-discovered):** the formant flag must PRECEDE the
  transpos value. `... out.ana ramp.brk -p8` → exit 255 `Formant flag missing on cmdline.`;
  `... out.ana -p8 ramp.brk` → exit 0. (An earlier pipe-masked probe suggested otherwise —
  re-verified with real exit codes both ways.) The mode-3 entry's declaration order encodes it.
- **FORMANT PRESERVATION content-proven:** +12 st on vow: fundamental 220→440.0 exactly for
  both transposef 3 and transpose 3, but energy fraction > 1.5 kHz: source 0.019,
  **transposef 0.010, transpose 0.049** — the envelope stayed put here, moved there.
- **transpos brk-capable:** 0→12 ramp ≠ both endpoints (data chunks df273d4f / 3bb7c934 /
  de4695f7); resynth pitch glides 250 → 417 Hz.
- **Unit equivalence:** mode 1 ratio 2.0 == mode 3 12 st, byte-identical data chunks →
  mode 1/2 dropped as unit variants. Mode 1 accepts combineb's ratio TEXT directly as its
  transpos brk (verified — execute() path).
- **Mode 4:** quantise-made `.trn` in the pre-output slot works (chain B); wrong binary type
  refused `ERROR: vow.frq is not a transposition file.`; TEXT refused
  `ERROR: cannot open input file trans_bb.txt to read data.`; **NO length check** — a
  698-window .trn on a 523-window .ana ran to the .ana's own end (contrast spec bare's hard
  length refusal). Silent-wrong-pairing landmine documented.
- Ranges: transpos ratio 0.00383–256 with the family's mislabeled refusal
  (`Transposition [322.539795] out of range 0.003830 - 256.000000 semitones`).
- Duration static (2.0230); deterministic (det1==det2); wav infile refused
  (`Application doesn't work with this type of infile.`).

## 6. repitch synth — CURATED

`repitch synth binarypitchfile outanalfile harmonics-data` (no mode token).

- Runs on wob.frq (marker values tolerated); output .ana resynth follows the track
  (fund 241–247 Hz mid-file); output duration = pitchfile duration (2.0230).
- Harmonic amps enforced 0–1: `ERROR: Partial amplitude[2] = 2.000000 is out of range
  (0.000000 - 1.000000)`; inline value refused `Can't open textfile 0.7 to read data.`;
  30 harmonics accepted. TEXT pitch input refused (typed infile). Deterministic.
- Loudness does not follow the source (probe RMS 0.076) — analenv pairing documented.

## 7. repitch vowels — CURATED

`repitch vowels infile outfile vowel-data halfwidth curve pk_range fweight foffset`.

- Verified with bare token `ee` AND a time/vowel file (`0 ee / 1.0 ar / 2.0 o`) — both exit 0,
  resynth follows the track. Bad token: `Can't open textfile qq to read vowel data.`
  (unknown tokens are treated as filenames). halfwidth range verbatim
  `Parameter[2] Value (20.000000) out of range (0.010000 to 10.000000)`; curve 0.1–10,
  pk_range/fweight/foffset 0–1 (banner). 15 vowel tokens pinned in the entry.
- **Entry shape:** vowel_data curated as aux_file (file form only — a one-line `0 ee` covers
  the fixed vowel); the bare-token argv form is execute()-only (engine str wall).

## 8. repitch analenv — CURATED (.evl data output)

`repitch analenv vow.ana aev.evl` → exit 0. Container carries **`is an envelope`** — the same
ENVFILE species as `envel extract`'s `.evl` (window size prop 2.9 ms vs 17.4 ms). Round-trip
proof through a curated consumer: `envel envtobrk aev.evl` → exit 0, time/level text at the
2.9 ms grid (`0.000000 0.000000 / 0.002902 0.010066 / 0.005805 0.057719` across the probe
attack). Deterministic. Banner: window-synchronous with pitch/formant data from the same .ana.

## 9. Converters: ptobrk CURATED; pchtotext, pitchinfo, brktopi, convert_to_midi dropped

- **ptobrk** `withzeros vow.frq ptb.txt 20` → 285 lines, **markers preserved as literal
  -1.000000/-2.000000 rows** (`0.000000 -2.0 / 0.002902 -1.0 / ... / 0.011610 218.371368`).
  min-pitch-dur verbatim `Parameter[1] Value (2000.000000) out of range (1.000000 to
  1000.000000)`; text input refused `File ptb.txt is not of correct type`. Deterministic.
- **repitch pchtotext** on the same file: 2 lines — silently data-reduced, markers dropped,
  no control flag. ptobrk's own banner: "should be used instead of 'repitch pchtotext' for
  files containing no-pitch and no-sound markers." → sibling-dropped.
- **pitchinfo convert** REFUSES marker files: `ERROR: Input file contains unpitched windows:
  cannot proceed.` → dropped. **info/zeros**: stdout-only, no outfile argv (report sample:
  `MAX PITCH : 220.31HZ MIDI : 57.02 ...`) → engine-incompatible, dropped. **see**: viewing
  pseudo-sndfile → dropped. **hear**: .ana testtone from a pitchfile — redundant with
  getpitch's own tone output + synth → dropped.
- **brktopi** `brktopi ptb.txt btp.frq` → exit 0, RIFF .frq, correct window count — but the
  marker-file round trip is NOT value-faithful (max |delta| vs the original binary =
  **219.4 Hz**: marker windows re-valued); also rebuilds a full 698-window file from a 2-line
  reduced brk (container params assumed). Binary out → schema-blocked anyway; both pinned.
- **convert_to_midi**: wrote `c2mout.mid` (extension FORCED per banner) and exited **1** on
  the successful probe — breaks both the output-path contract and the exit contract → dropped.
- **repitch generate** `gen.frq gen.txt 44100` from time/MIDI text → exit 0, RIFF .frq —
  the from-scratch melody source; binary out → schema-blocked; recipe pinned in synth/vowels.

## 10. THE WORKFLOW CHAINS — verified end-to-end through process_impl

Engine harness: real `SessionManager`/`KnowledgeIndex`/`process_impl`,
CDP_PATH=/tmp/CDP8/NewRelease, fresh sessions, inputs vow.wav + wob.wav (auto-PVOC engaged).

**Chain A — pitch-contour transfer, ALL CURATED calls:**
1. `process(repitch getpitch sm1, vow.wav)` → tone .ana + `pitch_trace.frq` in session root.
2. `process(repitch getpitch sm2, wob.wav)` → tone .ana + `pitch_trace.txt`.
3. `process(repitch combineb sm1, pitchfile=pitch_trace.frq, pitchfile2=pitch_trace.txt)`
   → 10-point time/ratio .txt (argv in lineage:
   `repitch combineb 1 pitch_trace.frq pitch_trace.txt graphs/.../n1_repitch-combineb.txt`).
4. Ratios → semitones (12·log2 r), passed to
   `process(repitch transposef sm3, vow.wav, transpos=[["abs:t", st], ...], formant_bands=8)`.
   Two integration rules discovered and pinned in the entry: breakpoint lists are
   RELATIVE-time by default → combineb's absolute seconds need **`abs:` mode**
   (`relative time 1.190023 outside [0, 1]` otherwise), and the pitch-data timeline runs on
   the analysis grid ~1% past the wav → **clamp times to the source duration**
   (`absolute time 2.020136 outside [0, 2.0]` otherwise).
5. Resynthesis: the steady 220 Hz vow now tracks wob's wobble —
   A: `[286.7, 276.9, 267.0, 257.1, 247.2, ...]` vs wob: `[290.0, 280.0, 270.0, 250.0,
   240.0, ...]`, **mean |delta| 5.1 Hz** (FFT-bin resolution). PASS.

**Chain B — getpitch → quantise → transposef 4 (curated ends, execute() middle):**
1. `process(repitch getpitch sm1, wob.wav)` → `pitch_trace.frq` (fresh session).
2. execute-style: `repitch quantise 2 pitch_trace.frq qB.trn data/qset.txt` (C-major MIDI set),
   cwd = session root → exit 0.
3. `process(repitch transposef sm4, wob.wav, transposition=qB.trn)` → .ana; resynthesis:
   continuous wobble `[290, 280, 270, 250, 240, ...]` snapped to stepped plateaus
   `[296.6, 296.6, 257.1, 257.1, 247.2, ...]` (D4/C4/B3 within bin error). PASS.

**Spot-checks through process_impl (every curated entry engine-run):**
`repitch synth` (fund follows track: 247.2 Hz vs orig 240.0 mid-file);
`repitch analenv` (→ .evl, 4862 bytes); `pitch pick sm1` (harmonic-series energy fraction
**0.991** at fundamental 220 on vow); `ptobrk withzeros` (44-line marker-aware text);
`repitch vowels` (vseq.txt ee→ar→o, runs, resynth pitched); `pitch transp sm6`
(octave-down energy present at 110 Hz AND octave-up at 2200 Hz in one output). ALL PASS.

## 11. pitch transp — CURATED (submode 6); pick — CURATED (submode 1)

- **transp 6** `vow.ana out 1000 12 -12 [-d]`: content §10 + raw probe (110/330 series below,
  2200/2640 above). Ranges verbatim: frq_split `(5.000000 to 22050.000000)` [Param 1]; depth
  `(0.000000 to 1.000000)` [3]; transpos runtime refusal `Shift above frq split is too great
  to work.` (+100 st; INVALID DATA — content-dependent, no fixed range). Time-variability:
  transpos1 brk ≠ both endpoints; frq_split/transpos2/depth brks each exit 0 and ≠ the scalar
  render (banner confirms all four). `-d0.5` live. Modes 1–3 (octave-hardwired) and 4/5
  (single-direction; negative transpos accepted in 4) dropped as subsets. Duration 2.0230.
- **pick 1** `vow.ana out 220 [-c]`: sieve content-proven (only 220-multiples; engine run
  0.991 energy fraction). fundamental `(10.000000 to 22050.000000)` [1], brk refused
  `Cannot read parameter 1 [cl.brk]: brkpnt_files not permitted.`; clarity `(0.000000 to
  1.000000)` [2], default 1, brk-capable (0.2→1 ramp ≠ both endpoints). Submodes 2/3 same
  shape (octaves / odd partials), 4/5 add frqstep — dropped, execute()-reachable.

## 12. pitch altharms / octmove / chordf / chord — DROPPED (content evidence)

- **altharms 1/2** (`infile pitchfile outfile [-x]`, pitchfile pre-output): exit 0, but NO
  odd/even selectivity on the clean 220 Hz 10-harmonic fixture — per-harmonic energy ratios
  vs source 0.20–0.31 across ALL of h1–h6, both modes, with both a -z and an interpolated
  pitchfile. The documented operation ("delete odd harmonics → octave up") is not observable.
- **octmove 2** (`infile pitchfile outfile [-i] transposition`): runs, content plausible
  (110-series added octave-down with the 220 series held — formant-preserving). Dropped as
  attrition: integer-ratio-only subset of curated transposef 3's musical range.
- **chord / chordf** (`infile outfile [-fN|-pN] transpose_file [-b -t -x]`): exit 0 in every
  variant, but the transposed copies are effectively ABSENT: member energy at +4/+7 st is
  ≤ 1.3% of the fundamental on the harmonic fixture and **0.12–0.17% on a pure 440 Hz sine**
  (both programs, one-value-per-line and single-line files, with/without -x, with a lone `4`).
  Source (`ap_pitch.c` chordget) confirms the file parse (semitones → frq ratios), so the data
  path is right — the spectral move itself does not land on this build. Garbage-through:
  a caller would get silently-unchordal output. Both dropped; re-probe candidates on r8 proper.

## 13. Duration row confirmations (fixture-compatible rows only)

| row | predicted | actual (synth round-trip) | rel err |
| --- | --------- | ------------------------- | ------- |
| repitch transposef 3 (static), transpos -12 / -p8, indur 2.0 | 2.0 | 2.0230 | 1.15% |
| repitch transposef 4 (static), .trn aux, indur 2.0 | 2.0 | 2.0230 | 1.15% |
| pitch transp 6 (static), 1000/+12/-12, indur 2.0 | 2.0 | 2.0230 | 1.15% |
| pitch pick 1 (static), fundamental 220, indur 2.0 | 2.0 | 2.0230 | 1.15% |
| repitch getpitch 1/2 tone (static), indur 2.0 | 2.0 | 2.0230 | 1.15% |
| repitch synth (pitchfile-driven), 2.023 s track | 2.023 | 2.0230 | 0.00% |

Rows shipped in findings: transposef 3, transp 6, pick 1 (aux-free, re-runnable).
Null-with-reason: getpitch 1/2 (fixed-name side file collides across fixture re-runs — CDP
never overwrites), transposef 4 / combineb 1 / synth / vowels / ptobrk (binary aux files
cannot ride _AUX_FILES), analenv (data output, no audio duration).

## 14. Curated / dropped summary

**Curated (11):** repitch getpitch 1, getpitch 2, combineb 1, transposef 3, transposef 4,
synth, vowels, analenv; ptobrk withzeros; pitch transp 6, pick 1.

**Dropped with evidence (findings JSON):** the 15-program binary transform layer (schema gap,
all verified running), repitch combine, combineb 2/3, generate, pchtotext; brktopi;
pitchinfo info/zeros/see/hear/convert; convert_to_midi; pitch altharms, octmove, chord,
chordf, transp 1–5 subsets, pick 2–5 subsets.
