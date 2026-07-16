# Tranche 10b — SoundThread-covered singles, time-domain/utility half: probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build; Groucho-family
  programs banner "CDP Release 7.1 2016"; `multiosc`, `phase` and `synspline` print no
  release banner — CDP8-new), Linux x86_64 sandbox. To be re-verified on macOS r8 by the
  CDP-gated suite after integration.
- **Inputs:** shared fixtures from `/tmp/probe` (n1/n2/n3 enveloped noise, tone1/tone2
  440 Hz sines, flat2 flat noise, st2 stereo noise, syl2 syllable train) and `/tmp/probe9`
  (`t9m_tone2.ana` 2 s / `t9m_rich2.ana` 2 s / `t9m_rich15.ana` 1.5 s pvoc-anal-1 pairs).
  Fresh fixtures in `/tmp/probe10b`: `dc2`/`dc1` (440 Hz tone amp 0.4 with +0.1 DC, 2 s/1 s),
  `att2` (attack-resonance decaying noise, 2 s), `stLR2` (distinct L=tone/R=noise stereo),
  `stMS2`/`stMS1` (mostly-mono stereo with small side component, 2 s/1 s).
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. Breakpoint proof =
  brk render differs from BOTH scalar-endpoint renders (at a fixed seed where one exists);
  determinism pairs launched > 1.2 s apart; shas over decoded float64 samples; fresh
  output names per run; duration models verified at >= 2 input durations.
- **SoundThread priors:** `/tmp/SoundThread/scenes/main/process_help.json` keys
  `extend_baktobak`, `modify_sausage`, `housekeep_extract_4`, `phase_phase_1`,
  `sfedit_join`, `sfedit_excise_1`, `multiosc_multiosc_3`, `synspline_synspline`,
  `repitch_transpose_3` — these pin the curated submodes.

Refusal errors quoted verbatim (stdout, exit 255).

---

## 1. extend baktobak

Working argv: `extend baktobak n2.wav out.wav 1.0 15` — exit 0. No mode digit.

| input | indur | join_time | splice | outdur | predicted `2*(indur-join_time)` |
| ----- | ----- | --------- | ------ | ------ | ------------------------------- |
| n2 | 2.0 | 1.0 | 15 | 2.0000 | 2.0 |
| n2 | 2.0 | 0.5 | 15 | 3.0000 | 3.0 |
| n2 | 2.0 | 1.5 | 15 | 1.0000 | 1.0 |
| n2 | 2.0 | 2.0 | 15 | **1 frame** (exit 0) | 0.0 |
| n2 | 2.0 | 1.0 | 100 | 2.0000 | 2.0 |
| n2 | 2.0 | 1.0 | 600 | 2.0000 | 2.0 |
| n1 | 1.0 | 0.5 | 15 | 1.0000 | 1.0 |
| att2 | 2.0 | 1.8 | 15 | 0.4000 | 0.4 |
| st2 (stereo) | 2.0 | 1.0 | 15 | 2.0000 (2 ch) | 2.0 |

- **duration_model `expression: 2 * (indur - join_time)`** — 4-dp exact on every probe;
  the splice never changes duration (15/100/600/1500 ms all identical lengths).
- **CONTENT (first-class vs the ST prior):** output = `reverse(src[join_time:])` then
  `src[join_time:]` — verified sample-exact (both halves allclose to the source segment,
  max diff 0.0; whole output a perfect palindrome). Material BEFORE join_time is
  **discarded**. SoundThread's help ("reverses it and then prepends the reversed sound
  onto the start of the original") is only true as join_time → 0.
- **Degenerate landmine:** `join_time == indur` exits 0 and writes a 1-frame file — no
  refusal; the engine's output verification is the only guard.
- **Ranges:** join_time `(0.000000 to 2.000000)` (runtime = indur; −0.5 and 2.5 refused);
  splice `(0.010000 to 2000.000000)` ms (0/−1/5001 refused; ST's 0.01–500 advisory).
  join 0: `ERROR: Cut point (0.000000 secs)is too near to start of file for the
  splicelength (0.015000 secs) demanded.` — source rule `splice/2 >= join_time`
  (ap_extend.c:1534); join 0.01 with splice 15 runs.
- **Breakpoints (both refused):** join_time `Cannot read parameter 1 [...]:
  brkpnt_files not permitted.`; splice `Cannot read parameter 2 [...]`.
- **Determinism:** identical decoded shas 1.2 s apart. Stereo accepted → `any`.

## 2. housekeep extract, submode 4 (RECTIFY / DC shift)

Working argv: `housekeep extract 4 dc2.wav out.wav -0.1` — exit 0
(`INFO: Finding minimum sample in file. / INFO: Rectifying.`).

| input | indur | shift | out mean (in mean) | outdur |
| ----- | ----- | ----- | ------------------ | ------ |
| dc2 | 2.0 | −0.1 | −0.00002 (+0.09998) | 2.0000 |
| dc2 | 2.0 | +0.1 | +0.19999 | 2.0000 |
| dc2 | 2.0 | +0.05 | +0.14997 | 2.0000 |
| tone2 | 2.0 | +0.1 | +0.09999 (−0.00002) | 2.0000 |
| dc1 | 1.0 | −0.1 | — | 1.0000 |
| stLR2 (stereo) | 2.0 | +0.05 | both ch +0.05 | 2.0000 (2 ch) |

- **Semantics:** shift is ADDED literally to every sample (mean moves by exactly shift;
  min/max move by shift). The program does NOT measure the DC — the user supplies the
  correction. duration_model `static`, sample-exact at both indurs.
- **shift 0 REFUSED** (ST's default value!): `ERROR: CANNOT ACHIEVE TASK: / ERROR: NO
  CHANGE to original sound file.`
- **Headroom guard:** `housekeep extract 4 tone2.wav out 0.6` (peak 0.5) →
  `INFO: Finding maximum sample in file.` then `ERROR: CANNOT ACHIEVE TASK: / ERROR: This
  rectification will distort the sound.` Same refusal for +0.01 on peak-1.0 stereo noise —
  full-scale files admit no shift in the loud direction. Refusal, never clipping.
- **Range:** `(-1.000000 to 1.000000)` (1.5/−1.5/2.5 refused). Breakpoint refused
  (`Cannot read parameter 1 [...]`). Deterministic. Stereo (with headroom) accepted → `any`.
- **Submode-1 forensics (recorded for the dropped sibling):**
  `housekeep extract 1 syl2.wav -g0.05` (NO outfile argv) → exit 0, `INFO: 4 segments
  extracted.`, files `syl0.wav syl1.wav syl2.wav syl3.wav` named from the INPUT stem —
  and the segment whose generated name collided with the input `syl2.wav` was **silently
  skipped** (input untouched at 2.0 s; only 3 new files; `-n` would stop instead).
  Multi-output with no output argv slot → cannot be hosted; dropped with record.

## 3. modify sausage (multi-input brassage)

Working argv: `modify sausage n2.wav tone2.wav out.wav 1 2 1 2 50 0 1 0.5 5 5 50 0 1 0.5
5 5` — exit 0 (16 positionals: velocity density hvelocity hdensity grainsize pitchshift
amp space bsplice esplice hgrainsize hpitchshift hamp hspace hbsplice hesplice).

| inputs | velocity | outdur | predicted `min(indur)/velocity` |
| ------ | -------- | ------ | ------------------------------- |
| 2.0 + 2.0 | 1.0 | 1.9800 | 2.0 |
| 2.0 + 2.0 | 0.5 | 3.9333 | 4.0 |
| 2.0 + 2.0 | 2.0 | 1.0035 | 1.0 |
| 2.0 + 1.0 | 1.0 | 0.9784 | 1.0 |
| 2.0 + 2.0 + 2.0 | 1.0 | 1.9800 | 2.0 |
| 2.0 + 2.0 | 1001 | 0.0581 | 0.002 (floors out) |

- **duration_model `expression: indur_min / velocity`** — source-confirmed
  (dev/modify/brapcon.c:92 takes the MINIMUM infile size for ORIG_SMPSIZE) and
  probe-verified on equal and unequal pairs; ±~1% run-to-run wobble on top (clock seed).
  Multi-input → duration_row null; rule pinned here.
- **CLOCK-SEEDED, UNSEEDABLE (first-class):** brapcon.c:80 `initrand48()` =
  `srand(time(0))` (osbind.c); no seed slot. Verified: identical commands 1.2 s apart
  differ in samples AND durations (1.9867 vs 1.9831); `-j0` with all h == base still
  differs (frame counts equalize at 87136, samples differ); two runs launched within the
  same second rendered **byte-identical** (observed collision during the first probe
  batch — `a_v1.wav` == `bad1.wav`).
- **Output ALWAYS STEREO** (2 ch from mono inputs — space/pan baked into the argv;
  space 0 → R RMS 0.0000). Inputs must share one channel count
  (`ERROR: INVALID DATA / ERROR: Incompatible channel-count in input file ...`);
  stereo+stereo accepted. Single input: `Insufficient input files for this process`.
- **BANNER RULE NOT ENFORCED (first-class):** usage says "(name of outfile must NOT end
  with a '1')" — `bad1.wav` ran and rendered normally. Legacy multi-outfile naming rule,
  dead here. Also unenforced: "grainsize must be > 2*splicelen" (9 ms with 5+5 ran);
  space range 0–1 (1.5 accepted silently); `-c` range 1–2 (`-c3` ran).
- **Ranges (verbatim):** velocity `(0.000000 to 32767.000000)`, 0 needs `-l`
  (`Zero VELOCITY found: Outfile length must be specified.`); density/hdensity
  `(0.000023 to 16383.500000)` (quoted from Parameter[4]); grainsize
  `(2.000000 to 2000.000000)` (ST's 2–200 advisory); pitchshift
  `(-133.278752 to 133.278752)` (srate-dependent; +100 in-range but refused at runtime
  `ERROR: CANNOT ACHIEVE TASK: / ERROR: SOURCE POSSIBLY TOO SHORT FOR THIS OPTION: Try
  'Full Monty'`, −100 ran); amp `(0.000000 to 1.000000)`; bsplice/esplice
  `(1.000000 to 1000.000000)`; range `-r` `(0.000000 to 4000.000000)` (Parameter[17]);
  jitter `-j` `(0.000000 to 1.000000)` (Parameter[18], CDP default 0.5).
- **Breakpoints:** ALL 16 positionals + `-r` + `-j` accept brk files (exit 0; banner:
  "All params, except OUTLENGTH and CHANNEL, can vary through time"). `-l` refuses
  (`Cannot read parameter 19 [...]`), `-c` refuses (`parameter 20`). Under the clock seed
  only aggregates are provable: velocity brk 1→2 → 1.1521 s (between and distinct from
  the 1.98/1.00 endpoints); amp brk 0.2→1 → RMS rises 0.123→0.184; space brk 0→1 →
  L/R RMS 0.123/0.196 → 0.018/0.293 (pans across the output).
- h-limit BELOW its base accepted silently (velocity 2 / hvelocity 0.5 → 1.586 s —
  treated as the other end of the range).

## 4. multiosc multiosc, pinned submode 3 (ST's four-oscillator FM stack)

Working argv: `multiosc multiosc 3 out.wav 2.0 440 100 0 200 0 300 0 44100 15` — exit 0.

| dur | frames | note |
| --- | ------ | ---- |
| 2.0 | 88200 | sample-exact |
| 0.7 | 30870 | sample-exact |
| 5.0 | 220500 | sample-exact |

- **duration_model `set_by dur`** — sample-exact. `dur` floor ≈ 2×dovesplice
  (`ERROR: Duration too short for dovetailing splices.` at 0.01; 0.031 ran); **NO CDP
  ceiling** (7201 s rendered 635 MB, exit 0) — engine duration cap is the guard.
- **Content:** all sub-amps 0 → pure 440 Hz sine, peak 0.89996 (FIXED 0.9 output level,
  no master amp param); amp2 0.3 at frq2 100 → dominant energy at 12–13 kHz (fierce
  modulation index; ST caps amps at 0.5).
- **MODE REDUNDANCY (first-class):** mode 1 (440,100,0.2) renders **byte-identical** to
  mode 3 with the same frq2/amp2 and amp3=amp4=0 — modes 1/2 are strict subsets; one
  entry covers the family.
- **Breakpoints:** frq1/frq2/amp2/frq3/amp3/frq4/amp4 ALL capable (each brk render
  differs from both scalar endpoints — 7/7); dur refused (`Cannot read parameter 1`),
  srate (`parameter 9`), dovesplice (`parameter 10`). Banner marks only FRQs "(possibly
  time-varying)" — the amp brk capability is **banner-silent**.
- **Ranges (verbatim):** frq1–4 `(0.001000 to 10000.000000)`; amp2–4
  `(0.000000 to 1.000000)`; srate `(16000.000000 to 96000.000000)` + discrete-set check
  (`ERROR: Invalid sample rate (44000) entered.`, 17000 same; 22050/24000/48000/88200 ok);
  dovesplice `(1.000000 to 50.000000)` ms.
- **Determinism:** identical decoded shas 1.2 s apart. Output mono only.

## 5. phase phase — submode 1 (INVERT) and submode 2 (STEREO ENHANCE)

Working argv: `phase phase 1 n2.wav out.wav`; `phase phase 2 stMS2.wav out.wav [-t0.5]`.

- **Mode 1:** output == −input **sample-exact** (max |out+in| = 0.0), mono AND stereo
  (both channels inverted); duration static/exact at 1 s and 2 s; no parameters;
  deterministic. Channel constraint `any`.
- **Mode 2 stereo-only:** mono refused `ERROR: INVALID DATA / ERROR: File n2.wav is not
  of correct type (must be stereo)`.
- **Mode 2 algorithm (content-verified):** ≈ per-channel `L − t·R` / `R − t·L`, then
  peak-renormalized to the input level (`INFO: Finding maximum input sample / Finding
  maximum output sample / Doing stereo enhancement`; candidate model correlates 0.9997
  at t = 1 and t = 0.5). Width (side/mid RMS) on stMS2: 0.0357 → **57.10** at default
  t = 1 (near-total mid kill, anti-correlated output) and 0.108 at t = 0.5.
- **transfer:** range `(0.000000 to 1.000000)` (1.5/−0.5 refused); `-t0` refused
  `ERROR: INVALID DATA / ERROR: Transfer parameter of ZERO produces no effect on the
  source.`; brk refused (`Cannot read parameter 1 [...]`). Default = 1 (flag-less run).
- Duration static (2 s and 1 s stereo). Both modes deterministic (1.2 s-apart pairs
  identical).

## 6. repitch transpose, pinned submode 3 (semitones)

Working argv: `repitch transpose 3 t9m_tone2.ana out.ana 12` — exit 0.

- **Pitch verified textbook:** +12 st on the 440 Hz analysis → resynthesis peaks at
  exactly 880 Hz. **duration_model `static`:** 2 s ana → 2.0230 via pvoc synth; 1.5 s →
  1.5209 (analysis padding, ~1.2% — inside row tolerance).
- **UNIT-VARIANT MODES (first-class):** mode 1 ratio 2.0, mode 2 octaves 1.0 and mode 3
  semitones 12 render **byte-identical data chunks** — one operation, three unit scales;
  mode 3 pinned (ST). Mode 4 (binary transpos data file) via execute().
- **RANGE-ERROR MISLABEL (first-class):** out-of-range refusals print the frequency
  RATIO under a semitone label: transpos 100 → `ERROR: Transposition [322.539795] out of
  range 0.003830 - 256.000000 semitones`; −100 → `[0.003100]`; +97 → `[271.222565]`.
  Enforced range is ratio 0.00383–256 ≈ −96.3 to +96.0 st. ST's ±24 advisory.
- **Breakpoint:** transpos brk 0→12 exit 0, differs from both scalar endpoints, resynth
  pitch rises 507 → 824 Hz across the file → **capable** (banner-confirmed:
  "frq-ratio, octave or semitone transpositions may vary over time").
- **Flags:** `-l`/`-h` `(5.000000 to 22050.000000)` (−5 and 50000 refused; ceiling =
  Nyquist). Effect verified: `-l300 -h2000` on rich2 cut the sub-300 Hz energy fraction
  0.123 → 0.015 and the 2 kHz+ fraction 0.659 → 0.272. `-x` changes the data chunk.
- Wav input refused `Application doesn't work with this type of infile.`; deterministic
  (identical data chunks 1.2 s apart).

## 7. sfedit excise, pinned submode 1

Working argv: `sfedit excise 1 n2.wav out.wav 0.5 1.0` — exit 0.

| input | start | end | splice | outdur | predicted `indur-(end-start)` |
| ----- | ----- | --- | ------ | ------ | ----------------------------- |
| n2 | 0.5 | 1.0 | (def 15) | 1.5000 | 1.5 |
| n2 | 0.2 | 1.8 | (def) | 0.4000 | 0.4 |
| n1 | 0.3 | 0.5 | (def) | 0.8000 | 0.8 |
| n2 | 0.5 | 1.0 | -w0 | 1.5000 | 1.5 |
| n2 | 0.5 | 1.0 | -w200 | 1.5000 | 1.5 |
| st2 (stereo) | 0.5 | 1.0 | (def) | 1.5000 (2 ch) | 1.5 |

- **duration_model `expression: indur - (end - start)`** — sample-exact; splice never
  changes length. `-w0` output verified a **verbatim sample-exact concatenation** of
  `input[0:start] + input[end:]` (max diff 0.0).
- **Silent swap re-verified:** `1.0 0.5` byte-identical to `0.5 1.0`. start == end →
  `ERROR: endcut = startcut: No cutting possible.`; end 2.5 on 2 s →
  `Parameter[2] Value (2.500000) out of range (0.000000 to 2.000000)`.
- **splice:** `(0.000000 to 5000.000000)` ms (−1/5001 refused); `-w800` around a 0.5 s
  cut → `ERROR: Edited portion is too short for specified splicelen.`
- **Breakpoints (all refused):** start/end/splice `Cannot read parameter 1/2/3 [...]`.
- Deterministic; stereo accepted → `any`.

## 8. sfedit join (multi-input)

Working argv: `sfedit join n1.wav tone1.wav out.wav` — exit 0.

| inputs | splice | outdur | predicted `sum - n_seams*splice/1000` |
| ------ | ------ | ------ | ------------------------------------- |
| 1.0 + 1.0 | 15 (def) | 1.9850 | 1.985 |
| 2.0 + 1.0 | 15 | 2.9850 | 2.985 |
| 1.0 + 1.0 + 2.0 | 15 | 3.9700 | 3.970 |
| 1.0 + 1.0 | -w0 | 2.0000 | 2.0 |
| 1.0 + 1.0 | -w100 | 1.9000 | 1.9 |
| 1.0 + 1.0 | -b -e | 1.9850 | 1.985 (content differs) |
| st2 + stLR2 (stereo) | 15 | 3.9850 | 3.985 |

- **duration_model `expression: indur1 + indur2 - splice / 1000`** — sample-exact; each
  seam consumes exactly one splice. `-w0` output verified a verbatim sample-exact
  concatenation. Multi-input → duration_row null; rule pinned here.
- **Ranges/refusals:** splice `(0.000000 to 5000.000000)` — range refusal quotes
  `Parameter[1]`, brk refusal quotes `parameter 3` (both verbatim); splice 1200 vs 1 s
  file → `ERROR: File 1 too short for specified spliclength.` (CDP's own typo);
  single input → `Insufficient input files for this process`; mixed channel counts →
  `ERROR: INVALID DATA / ERROR: Incompatible channel-count in input file ...`.
- **Breakpoints:** splice brk refused (`Cannot read parameter 3 [...]`).
- `-b`/`-e` change content (shas differ), never duration. Deterministic; variadic
  upstream (3-input verified), entry pins arity 2.

## 9. synspline synspline

Working argv: `synspline synspline out.wav 44100 2.0 220 4 24 5` — exit 0.

- **duration_model `set_by dur` with wavecycle round-UP:** dur 2.0 → 2.0000 exact;
  dur 0.7 at 220 Hz → 0.70295 (31000 frames) — the render loop appends whole wavecycles
  until `thistime >= dur` (source), overshoot < 1/frq s. dur < one wavecycle →
  `ERROR: Duration too short to generate a complete wavecycle.`
- **SEED 0 IS THE CLOCK PATH (first-class ST contradiction):** synspline.c:1530–1532
  `if (seed > 0) srand(seed); else initrand48()` (= `srand(time(0))`, osbind.c).
  Verified: seed 5 twice 1.2 s apart **byte-identical**; seed 5 vs 9 differ; **seed 0
  twice 1.2 s apart DIFFER**; seed 0 != seed 1. SoundThread's seed slider **defaults to
  0** — its default renders are irreproducible. Entry defaults seed to 1.
- **Ranges (verbatim):** frq `(0.001000 to 10000.000000)`; splinecnt
  `(0.000000 to 64.000000)`; interpval `(0.000000 to 4096.000000)` (fractional 0.5
  accepted); seed `(0.000000 to 64.000000)` (−1/65/40000 refused; omission reprints the
  usage); maxspline `-s` `(0.000000 to 64.000000)` (Parameter[7]); maxinterp `-i`
  `(0.000000 to 4096.000000)` (Parameter[8]); pdrift `-d` `(0.000000 to 12.000000)`
  (Parameter[9]); driftrate `-v` `(0.000000 to 1000.000000)` (Parameter[10]) with a 1 ms
  runtime floor; `-d` without `-v` (or `-v0.5`) → `ERROR: If drift transposition set
  (and not 0), vals for drift step must be set (and not less than 1mS).`; srate 11025
  refused `(16000.000000 to 96000.000000)`, 48000 accepted.
- **Breakpoints (at fixed seed 5):** frq (110→880), splinecnt (2→32), interpval (0→512),
  maxspline `-s` (vs `-s2`/`-s32`), maxinterp `-i` (vs `-i0`/`-i512`) — each differs
  from BOTH scalar endpoints → **all capable** (banner PTR-confirmed). seed brk refused
  (`Cannot read parameter 6 [...]`).
- **Content:** splinecnt 0 → harmonic-free near-sine at frq (verified 220 Hz, no
  measurable partials); `-s0` byte-identical to flag-less (banner "Ignored if set to
  zero" verified); `-n` and `-d3 -v100` each change the render. Peak ~0.92 (random
  per-cycle amplitudes; no master amp).
- Output mono. Reproducible for seed 1–64 (stochastic-with-working-seed).

---

## Engine spot-checks (process_impl end-to-end, entries as written)

| entry | predicted | measured | rel err |
| ----- | --------- | -------- | ------- |
| extend baktobak (join 1.0/splice 15, 2 s fixture) | 2.0000 | 2.0000 | 0.00% |
| housekeep extract 4 (shift −0.02) | 2.0000 | 2.0000 | 0.00% |
| modify sausage (defaults, velocity 1, 2 s + 1.5 s inputs) | 1.5 | 1.4872 (2 ch) | 0.85% |
| multiosc multiosc 3 (dur 2.0, arity-0) | 2.0000 | 2.0000 | 0.00% |
| phase phase 1 | 2.0000 | 2.0000 | 0.00% |
| phase phase 2 (stereo fixture, transfer 0.5) | 2.0000 | 2.0000 (2 ch) | 0.00% |
| repitch transpose 3 (+12 st, auto-PVOC from wav) | 2.0000 | 2.0230 | 1.15% |
| sfedit excise 1 (0.5–1.0) | 1.5000 | 1.5000 | 0.00% |
| sfedit join (defaults, 2 s + 1.5 s) | 3.4850 | 3.4850 | 0.00% |
| synspline (dur 2.0, seed 5, arity-0) | 2.0000 | 2.0000 | 0.00% |

Ten entries shipped (phase contributes two); one drop recorded:

- **housekeep extract submode 1** (CUT OUT & KEEP SIGNIFICANT EVENTS): takes NO outfile
  argv and writes one file PER DETECTED EVENT, named from the INPUT stem
  (`syl2.wav` → `syl0/1/2/3.wav`); a generated name colliding with an existing file
  (including the input itself) is **silently skipped** (`4 segments extracted`, 3 new
  files). The engine has no multi-output machinery (single output argv slot, single
  verified output, single lineage record) — reach it via execute() with cwd control.
  The task briefing's "one output per channel" guess was wrong: that behavior belongs
  to `housekeep chans`; extract mode 1 splits by EVENT.
