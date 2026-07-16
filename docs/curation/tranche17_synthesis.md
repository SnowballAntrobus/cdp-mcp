# Tranche 17 — synthesis/generative curation probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build, `-fsigned-char`;
  Groucho programs banner "CDP Release 7.1 2016"; the Release-8 science programs print no
  release banner), Linux x86_64 sandbox. To be re-verified on macOS r8 by the CDP-gated suite.
- **Fixtures:** `/tmp/probe17b` — mono float32 44.1 kHz: enveloped noise `n1/n2/n3` (1/2/3 s),
  sines `tone1/tone2` (440 Hz, 1/2 s), decaying pings `ping/ping2` (0.3 s, 880/660 Hz),
  stereo noise `st2` (2 s), single 100 Hz wavecycle `cycle.wav` (441 frames, starts/ends at 0).
- **Methodology:** tranche-2 verbatim. Breakpoint proof = brk render differs from BOTH scalar
  endpoints (same seed where applicable); determinism pairs > 1.1 s apart; sha256 of decoded
  float64 samples; fresh output names; arity-0 duration models at ≥ 2 parameter settings;
  refusals quoted verbatim (stdout, exit 255 unless noted). All 19 shipped entries were
  additionally run END-TO-END through `process_impl` (loader → validate → argv → run →
  verify) in the sandbox with `CDP_PATH=/tmp/CDP8/NewRelease` — statuses and durations below.
- **Priors:** SoundThread and afta8 cover NONE of these programs (grep-verified — they are
  Release-8 science/new programs). Priors are therefore binary + source (`/tmp/CDP8/dev`)
  + cr8new.htm / cgrosynth.htm only.

---

## 1. synth silence — DROPPED (structural)

`synth silence out.wav 44100 1 2.0` → exit 0, 88200 frames of digital zero.
- Ranges: srate `(16000.000000 to 192000.000000)` gate (11025 refused); chans 1–16 (banner
  says "1, 2 or 4"; 3 verified rendering 3-ch); dur `(0.000002 to 7200.000000)`; dur 0 exits 0
  with `WARNING: Can't close output sf-soundfile : can't truncate SFfile` (header-stub file).
- **Drop:** output is digital silence by definition; `verify_output` marks silent wavs
  `ok=False` and `node_execution.success` requires `verification.ok` — every render fails
  the engine contract. Evidence: `graph.py:518` + `tools/node_execution.py:228`.

## 2. synth spectra — CURATED

Working argv: `synth spectra out.wav 2.0 1000 400 0.9 0.3 0.5 44100` → exit 0.

| dur | outdur | drift |
| --- | ------ | ----- |
| 2.0 | 1.973696 | −1.32% |
| 1.0 | 0.975238 | −2.48% |
| 0.5 | 0.473107 | −5.38% |

- **duration_model:** set_by dur, quantized DOWN to whole blocks; shortfall grows at short dur.
- Output ALWAYS stereo. Deterministic: identical shas 1.2 s apart despite timevar.
- **Breakpoints capable (each differs from both endpoints):** frq (3416b055 vs 970e/b7f8),
  spread (7c39ca01 vs 1128/599b), maxfoc (ef32c379 vs d374/d5f5), minfoc (89d08758 vs
  d5f5/13fc), timevar (19fec1d4 vs be6a/2736). dur refused: `Cannot read parameter 1
  [b_tv.brk]: brkpnt_files not permitted.`
- **Ranges verbatim:** dur `(0.100000 to 32767.000000)`; frq `(10.000000 to 48000.000000)`
  (23000 at 44.1k accepted silently); spread `(0.000000 to 24000.000000)`; maxfoc/minfoc/
  timevar `(0.000000 to 1.000000)` (Parameters 4/5/6); srate `(16000.000000 to 96000.000000)`
  (96000 accepted). maxfoc < minfoc accepted silently. `-p` (spread as ratio) runs.
- **TEMP-FILE QUIRK (first-class):** writes `<outstem>1.wav/<outstem>2.wav/<outstem>3.wav`
  beside the output; killed runs leave them and a same-name re-run refuses
  `ERROR: Cannot open temporary analysis file 'rr3.wav' to generate sound data:Can't create
  SFile, already exists`.
- Engine run: `ok`, dur 1.9737.

## 3. synth chord (submodes 1 = MIDI, 2 = Hz) — CURATED ×2

Working argv: `synth chord 1 out.wav midi.txt 44100 1 2.0` → exit 0; duration sample-exact.
- **AMP DEFAULT DIVERGENCE (first-class):** banner "max & default" 1.0 is FALSE — flagless
  peak 0.2998/0.3000 at 3 and 2 notes; `-a0.5` → 0.4997; `-a1` → 0.9994. Default is 0.3.
- Deterministic (chd1 == chd1b). ';' comments byte-identical. Fractional MIDI 60.5 accepted.
  Data refusals per-value: `ERROR: Value 1 (200.000000) is out of range.` (midi);
  `(30000.000000)` refused / 5 Hz accepted (mode 2). Mode 1 (60/64/67) ≠ mode 2
  (261.63/329.63/392.0) as expected; mode 2 FFT peaks land exactly on the listed Hz.
- **Ranges verbatim:** srate `(16000.000000 to 96000.000000)`; chans `(1.000000 to 16.000000)`
  (banner "1, 2 or 4" false; stereo dual-mono verified); dur `(0.040000 to 7200.000000)`;
  amp `(0.000000 to 1.000000)` (−a0 renders silence); tabsize `(256.000000 to 4096.000000)`
  (−t256 differs from default 4096).
- **No breakpoint-capable params:** amp `Cannot read parameter 5`, dur `Cannot read
  parameter 3` (verbatim).
- Engine runs: both `ok`, dur 2.0 exact.

## 4. synth clicks — CURATED (submode 1); submode 2 + -s/-e DROPPED

Working argv: `synth clicks 1 out.wav clickfile` → exit 0.
- Clickfile grammar pinned: sequential linenos (`Line numbers are not in sequence, at line
  2`); accent string length = beats (`Wrong number of characters in style-string (must be 4
  in this meter)`); `TIME` not first (`'TIME' dataline too soon: You cannot reset the
  Absolute time before you start the clickdata.`); tempo change `0.5=144to90` + `GP 1 2.5`
  verified rendering (11.87 s composite).
- Duration = last beat + ~21 samples (4×4/4@120 → 7.500476; +3/4 block → 13.000476;
  TIME 8.0 + 1 bar → 9.500476).
- **Clock-randomized click shape, unseedable:** clk5 == clk6 (same second) byte-identical;
  clk4 (earlier second) differs; times identical throughout. Peak can hit 1.0000.
- **CRASH (build-pinned):** `-s2 -e5` SIGABRT exit 134 in BOTH modes after writing plausible
  output (mode 1: 3.000476 s = end−start; mode 2: 5.000476 s) — engine sees failure. Flags
  excluded; submode 2 (line-number addressing, only useful with -s/-e) dropped.
- Engine run (sm1): `ok`, dur 3.5005 (2 bars 4/4 @120).

## 5. impulse — CURATED

Working argv: `impulse impulse out.wav 2.0 60 0 10 30 0.7` → exit 0.
- Duration set_by dur, whole-period quantized (2.0 → 1.996190; 1.0 → 0.998095); **dur 0 =
  exactly one impulse** (168 frames). Deterministic (imp1 == imp1b).
- **Breakpoints — six capable, each vs both endpoints:** pitch (673cf810 vs b6d8/803f),
  chirp (2582e2c0 vs 5b4c/3927), slope (9741ff86 vs 60b0/cce1), pkcnt (2b77d0ca vs
  cfb7/a5f0 — NOT in the banner's vary list, banner omission; 'GLIS' in that list names no
  argv slot), level (06e508ca vs 6626/004f), gap (023fa1a2 vs 5b4c/ba18). dur refused
  (`Cannot read parameter 1`). `-g0` == flagless byte-identical.
- **CHANS RELABEL BUG (first-class):** `-c2` → 44016 frames @2ch, `-c4` → 22008 @4ch, decoded
  sha IDENTICAL to mono (5b4cc64d) — dur consumed as total samples, header relabels the same
  stream. chans excluded from the entry.
- **Ranges verbatim:** dur `(0.000000 to 7200.000000)`; pitch `(1.000000 to 1000.000000)`
  (128 accepted); chirp `(0.000000 to 30.000000)`; slope `(1.000000 to 20.000000)`; pkcnt
  `(1.000000 to 200.000000)`; level `(0.000000 to 1.000000)`; gap `(-0.990000 to 10.000000)`;
  srate `(16000.000000 to 96000.000000)`; chans `(1.000000 to 16.000000)`.
- Engine run: `ok`, dur 1.99619.

## 6. motor (mode 1) — CURATED. The tranche prize: duration model + seed pinned.

Working argv: `motor motor 1 in.wav out.wav 2.0 20 1 0.5 0.7 0.5` → exit 0.

| dur | pulse | pratio | outdur | model ceil(dur·pulse)/pulse − (1−pratio)/pulse |
| --- | ----- | ------ | ------ | ---------------------------------------------- |
| 2.0 | 1 | 0.7 | 1.700000 | 1.7 |
| 3.0 | 1 | 0.7 | 2.700000 | 2.7 |
| 4.0 | 1 | 0.7 | 3.700000 | 3.7 |
| 2.0 | 1 | 0.5 | 1.500000 | 1.5 |
| 2.0 | 2 | 0.7 | 1.849977 | 1.85 |
| 2.0 | 2 | 0.5 | 1.750000 | 1.75 |
| 3.0 | 0.5 | 0.7 | 3.400000 | 3.4 |
| 2.0 | 1 | 0.9 | 1.900000 | 1.9 |

- **duration_model (sample-exact, input-length-independent):** whole outer pulses covering
  dur minus the last off-time. Curated expression
  `(dur*pulse - dur*pulse % 1 + (dur*pulse % 1 > 0) - (1 - pratio)) / pulse` —
  SimpleEval-verified (3.4 at the md4 point).
- **SEED (first-class):** deterministic at every setting — unseeded pairs 1.3 s apart
  byte-identical; `-s0` == unseeded; with `-f0.5 -j2`: seed 5 twice identical, 5 vs 9 differ;
  seed INERT at zero randomisation (`-s5` == `-s9` == unseeded). No clock path.
- **Breakpoints:** freq/fratio/pratio/frand(-f)/jitter(-j) capable (each vs both endpoints;
  jitter -j0 == flagless). sym refused (`Cannot read parameter 6`). **PULSE
  accepted-but-inert:** brk 0.5→3 renders byte-identical to pulse=0.5 scalar (26adaf0e both).
  dur brk: range-checked inside the file — `Value (0.500000) out of range (1.000000 to
  7200.000000) in brkpntfile b_pls.brk.`
- **Ranges verbatim (Parameters 1–15):** dur 1–7200; freq 2–100; pulse 0.1–10; fratio/pratio/
  sym 0–1; frand/prand 0–1; jitter 0–3; tremor/shift 0–1; edge 0–20; bite 0.1–10; vary 0–1;
  seed 0–256.
- Runtime: `Min outerpulse dur (1/rate(10.000000) = 0.100000) less max-offtime (shorten by
  0.03) = 0.070000` / `is less than or equal to 2 * max innerpulse dur (1/rate(2.000000) =
  0.50    X2=   1.00).` (INVALID DATA). `-c` = `Unknown variant flag -c` in mode 1.
  `-v0.5 -a` = `Fixed step and varying step in src-read cannot both be used.` Stereo in →
  stereo out (1.7 s, 2 ch).
- Engine run: `ok`, dur 2.700000 exactly (model 2.7).

## 7. ceracu — CURATED

Working argv: `ceracu ceracu ping.wav out.wav cyc.txt 0 1 0 0 0` (counts "3 4 5") → exit 0.

| src | mincycdur | outdur | model mincyc·max(cnt) + max(0, indur−mincyc) |
| --- | --------- | ------ | -------------------------------------------- |
| ping 0.3 | 0 (=indur) | 1.500680 | 1.5 |
| ping 0.3 | 0.5 | 2.500680 | 2.5 |
| ping 0.3 | 0.15 | 0.900816 | 0.9 |
| n2 2.0 | 0.5 | 4.000544 | 4.0 |
| ping, outdur 5 | 0 | 6.002721 | 4 cycles × 1.5 |

- Aux-name duration expression (`cyclcnts`) — pre-flight skips; model documented.
- Deterministic (cer1 == cer6, 1.3 s apart). Auto-normalised peak 0.95 every run
  (`INFO: Output will be normalised by 0.40 secs` — units misprint).
- Counts: `Must be more than 1 cycle value` (single); `Invalid cyclecnt (0.0) (must be >=1)`;
  fractional 4.5 ROUNDED (render length equals counts 3/5).
- **Ranges verbatim (input-dependent):** mincycdur `(0.000000 to 9.600000)` = 32×indur on the
  0.3 s src; chans `(1.000000 to 16.000000)`; outdur `(0.000000 to 3600.000000)`; echo
  `(0.000000 to 4.800000)` = 16×indur; echo 0.5 extends output (1.8005). Stereo refused
  `File st2.wav is not of correct type (must be mono)`.
- Engine run: `ok`, dur 4.000544 on the 2 s fixture (matches model 4.0).

## 8. newsynth (mode "synthesis") — CURATED submodes 1 and 5

Mode 1 argv: `newsynth synthesis 1 out.wav spec.txt 44100 2.0 220` → exit 0, dur sample-exact,
peak 0.85, mono, deterministic.
- Spectrum-file refusals verbatim: `First time in partials data (1.000000) must be zero.`;
  `Invalid first partial (2.000000) (must be 1 in this tone-generation mode)`; `Partial
  numbers do not increase through line 1.`; `Line 2 has different number of entries (3) to
  previous lines which have (5)`; `Partial 200.000000 at time 0.000000 (frq 220.000000) is
  above the nyquist (22050.000000)`. **DIVERGENCE:** non-ascending TIMES accepted silently.
  dur 0.01 accepted (manual floor 0.04). frq brk capable (2327b1b5 vs a984/136b).
  frq range `(0.001000 to 10000.000000)`; srate gate `(16000.000000 to 96000.000000)`.
- Mode 5 (Duffing) argv: `newsynth synthesis 5 out.wav 44100 2.0 80 0.2 5 30` → exit 0,
  dur exact, **peak 1.0 FULL SCALE**, deterministic.
  **MANUAL DIVERGENCE (first-class):** cr8new says damping "seemed to have no effect" —
  damping 0.2 vs 1.5 differ, AND damping brk 0.2→1.8 differs from both endpoints (capable).
  frq brk capable (e056acaf vs 137d/a408; brkfile values range-checked verbatim:
  `Value (440.000000) out of range (0.100000 to 200.000000) in brkpntfile b_nsf.brk.`).
  Ranges: frq `(0.100000 to 200.000000)`; damping `(0.150000 to 2.000000)`; k `(-10.000000
  to 10.000000)`; b `(20.000000 to 50.000000)`. Banner's "amplitude can vary" names no slot.
- Engine runs: both `ok`, dur 2.0 exact.

## 9. pulser — pulser 1 CURATED; pulser synth DROPPED

- **pulser synth (arity-0 partials mode) BROKEN:** `pulser synth 1 out.wav part.txt 4.0 60
  0.01 0.05 0.0 0.05 0.1 0.5 0.25 0.2` → SIGSEGV exit 139 (twice, incl. -s1); other param
  sets exit 0 but write **0-frame files** (three probes). Mode-1 data parser is one
  "pno level" pair per line (source: pulser.c handle_the_special_data — only the first value
  per line is a pno; multi-pair lines refuse `Partial levels must lie between -1.0 and 1.0`).
  Drop with evidence.
- **pulser pulser 1** works: `... in.wav out.wav 3.0 60 0.02 0.05 0.01 0.05 0.1 0.5 0.25 0.2`.
  Durations: dur 3 → 3.333583 unseeded / 3.236757 seed 5 / 3.332154 seed 9; dur 6 seed 5 →
  6.379320; **input-length-independent** (ping 0.3 s and n2 2.0 s → identical 3.236757 at
  seed 5). Model `dur + (minrise+maxrise+minsus+maxsus+mindecay+maxdecay)/2` → +3.96% on the
  pinned row.
- **SEED:** `-s0` == `-s1` == flagless, ALL byte-identical (60ce768a); unseeded pairs 1.2 s
  apart identical (no clock path); seeds 5/9 distinct + reproducible. `-s257` accepted
  (no ceiling).
- **Breakpoints capable (vs both endpoints, seed 5):** pitch (150412aa vs 5f91/3211),
  speed (dec4342a vs 6812/2a4f), pscat (1f48fe41 vs e12b/0d56; -p0 == flagless).
- **Ranges verbatim (Parameters 2–14):** pitch 24–96; minrise/maxrise 0.002–0.2; maxsus 0–0.2;
  mindecay/maxdecay 0.02–2; speed 0.05–1; scatter 0–1; expr/expd 0.25–4; pscat/ascat 0–1.
  **octav/bend: banner 0–1 is advisory (−o1.5/−b1.5 accepted).** maxrise < minrise accepted
  silently. dur 0.05 accepted. Stereo refused `File st2.wav is not of correct type: must be
  MONO`. pulser pulser 2 refused `COMBO OF TRANSPOSITION, GLISS AND SCATT...`; pulser multi 1
  works (uncurated sibling).
- Engine run: `ok`, dur 3.236757 (model 3.365, +3.96%).

## 10. synfilt (submode 1) — CURATED

- **BANNER ARGV WRONG (first-class):** usage lists `dur` and `gain` — neither exists. Real
  argv `synfilt synfilt 1 out.wav data srate chans Q hcnt rolloff seed` (source: science.h
  SYNFLT_ indices 0–5; a dur arg refuses as `Parameter[2] Value (2.000000) out of range
  (44100.000000 to 96000.000000)`).
- Duration = last datafile time + Q-dependent ring-out: last-time 1/2/3 → 2.587/3.981/5.150 at
  Q 50; **Q 200 pins at exactly 262144 frames (5.944 s)** — the filter-bank buffer constant.
- **Seed:** 0 == 1 byte-identical; seed 5 differs; seed-1 pairs 1.2 s apart identical.
- **Q brk capable** (11becaae vs 68e2/424b — duration itself moves with Q).
- **Ranges verbatim:** chans `(1.000000 to 2.000000)`; Q `(0.001000 to 10000.000000)`; hcnt
  `(1.000000 to 200.000000)` + runtime `Filter Harmonic 43 of 523.3Hz = 22499.8Hz beyond
  filter limit 22050.0.` (exit 253); rolloff `(-96.000000 to 0.000000)`; seed `(0.000000 to
  32767.000000)`. `-d` verified live (differs + longer); **`-n` = `Unknown flag '-n'`**
  (banner phantom); `-o` unprobed.
- Engine run: `ok`, dur 3.981043.

## 11. ts oscil — CURATED

- `ts oscil data.txt out.wav 4` → 8000 values ×2⁴ ≈ 127984 frames (2.902 s); downsample 0 →
  exactly N frames; **downsample 8 → exactly 10.000000 s: UNDOCUMENTED default 10 s curtail.**
- **maxdur enforced 1–60, banner '1 - 600' WRONG** (`Parameter[2] Value (700.000000) out of
  range (1.000000 to 60.000000)`; 0.5 refused). `-f -d20` loops to exactly 20.0 s; `-f`
  without `-d` accepted silently (banner says invalid).
- **`-c` (cubic spline) BROKEN:** renders a 1-frame silent file.
- downsample brk capable (4f67e694 vs 34d7/7f72); range `(0.000000 to 16.000000)`.
  Values outside ±1 accepted. Deterministic.
- **ARGV LAYOUT:** indata precedes the output (`ts oscil indata outsnd ...`) — the entry
  declares `position: "pre_output"`; without it the engine put the output first and ts
  failed with `ERROR: Failed to parse input file graphs/...wav` (caught in engine
  verification, fixed, re-verified).
- Engine run: `ok`, dur 1.45088 (4000 values ×2⁴/44100 = 1.4512).

## 12. chirikov — CURATED submode 1; modes 3–4 DROPPED

- `chirikov chirikov 1 out.wav 2.0 440 0.5 44100 15` → exit 0, dur sample-exact, deterministic;
  mode 2 (circle map) same argv, distinct render, deterministic (uncurated sibling).
- **damping range is 4π:** `Parameter[3] Value (100.000000) out of range (0.000000 to
  12.566371)` — the standard map's K. Level rises with K (peak 0.56 → 0.90) and with frq.
- frq brk capable (7d517111 vs db52/4b46); damping brk capable (626c5ffd vs 4729/5904).
- Ranges: frq `(0.001000 to 10000.000000)`; srate `(16000.000000 to 96000.000000)`;
  dovesplice `(1.000000 to 50.000000)`; dur floor `Duration too short for dovetailing
  splices.`; **dur 7201 ACCEPTED (no ceiling — engine cap is the guard).**
- **Modes 3–4 drop:** output extension STRIPPED — `chirikov chirikov 3 ch3.txt ...` writes
  `ch3` (no .txt; valid time/MIDI breakpoint text inside). Engine's expected output file
  never exists.
- Engine run: `ok`, dur 2.0 exact.

## 13. newtex (mode 1) — CURATED

- `newtex newtex 1 n2.wav out.wav ntx.txt 4.0 2 2 0.5 0` → exit 0, dur sample-exact 4.0.
- **Deterministic unseeded** (1.2 s pairs byte-identical; NO seed parameter exists).
- step brk capable (a4da6cc3 vs 038e/9713).
- **Ranges verbatim:** chans `(2.000000 to 16.000000)` — **NO MONO OUTPUT**; maxrange
  `(1.000000 to 8.000000)`; step `(0.004000 to 100.000000)`; spacetype `(0.000000 to
  14.000000)` + `Special Spatialisation types Only available for 8-channel output.`;
  runtime `(max) Rate (0.500000) must be less than half duration (0.050000).`; input
  `File st2.wav is not MONO`.
- Banner only prints on a tty (usage2 ends in a getch() loop — silent hang under pipes).
- Engine run: `ok`, dur 4.0 exact.

## 14. strands — DROPPED (all modes)

`strands strands 2 str1.wav 3.0 3 3 50 48 84 0.5 0 0 0 0 0 0 1` → exit 0 but writes
**`str10.wav`** (stem + stream index), never the argv name; re-verified with a second stem
(`strX.wav` → `strX0.wav`, also with -s). Modes 1/3 are declared "generic_outdatafilename"
multi-file data outputs. Engine's expected output never exists → structural drop
(multi-output generic-name precedent).

## 15. brownian (mode 2) — CURATED

- `brownian motion 2 ping.wav out.wav 1 3.0 48 84 60 1 2 0 0.25 5` → exit 0.
- **Seed:** 5 reproducible; 9 differs; **0 == 1 byte-identical** (c3ce9951 ×3) and seed-0
  pairs 1.2 s apart identical — glibc srand default-state, no clock path.
- **Duration:** dur + last-event ring-out; source-pinned reference = PSTART
  (brownian.c:1622 `tabincr = current_pitch - pstart`; max event dur line 1352–1354 =
  indur·2^((pstart−plo)/12)). Near-flat band (plo 60/phi 60.13/pstart 60): n2 → 4.8656
  (model dur+indur = 5.0, −2.7%); n1 → 3.8728 (model 4.0, −3.2%). Wide band (plo 48,
  pstart 60, n2): 4.611 vs bound 7.0 — bound over-predicts (safe direction).
- **Breakpoints:** tick capable (3e383535 vs f529/a94a). plo: brk 55→70 differs from
  same-params scalar-55 (6d3cb554 vs d0db); strict both-endpoint proof impossible (scalar
  plo 70 forces pstart ≥ 70 — different params). Marked capable with caveat.
- **Ranges verbatim (Parameters 1–10):** chans 1–16; dur `(0.300000 to 7200.000000)`;
  plo/phi 0–127; step `(0.125000 to 24.000000)`; sstep 0–1; tick `(0.002000 to 4.000000)`;
  seed 0–255. pstart outside range: `START PITCH LI[ES...]`; plo == phi:
  `RANGE (60.0000 TO 60.0000) TOO NARROW FOR PITCH-STEPS (0.1250) AT TIME 0.000000`;
  `WARNING: Output array must be LINEAR if output-channel count IS LESS THAN 3.`
- Engine run: `ok`, dur 4.86562 (model 5.0).

## 16. fractal / frfractal

- **frfractal DROPPED:** `frfractal fractal ping.wav out.wav 2` → SIGABRT exit 134 +
  0-frame output on EVERY valid-layer run (ping layers 2, n2 layers 4, repeat 1.2 s apart).
  Layer validation works (`INFO: Maximum number of fractal cuts for this file = 2` then
  refusal at 3) — synthesis crashes. Drop with evidence.
- **fractal wave: 2-POINT SHAPE HANG (first-class landmine):** shape `0 0 / 0.5 7` sends
  BOTH wave modes into an infinite loop (no output; killed by timeout only). 3-point shapes
  work. Mode 1 output duration is shape-dependent and extreme (1 s tone → 0.187937 s;
  2 s → 0.375828 — ×0.188 both) → mode 1 deferred. **Mode 2 CURATED:** wavecycle in
  (cycle.wav), `fractal wave 2 cycle.wav out.wav shape3.txt 3.0` → 3.007710 s (+0.26%,
  set_by dur). fractal spectrum unprobed (deferred).
- Engine run (wave 2): `ok`, dur 3.00771.

## 17. multisynth — DROPPED

Every score refused with a bare `ERROR: INVALID DATA` (no diagnostic): flute/violin/pianoRH+LH
scores at MM 60/120, durations 3/4, levels .7/0.7. The one score that got past validation
(trumpet, two 4-sets) crashed with **heap corruption**: `corrupted size vs. prev_size`,
SIGABRT (exit 134, core dump). Score-format checks that do work: `Bad duration (2) (must be
multiples of 3 or 4) on line 1 (trumpet).` Unusable on this build; drop with evidence.

## 18. spectrum — format + fixed CURATED; varying/lines deferred

- Chain verified: dense 5000-point `frq amp` graph → `spectrum format out.txt graph 64 44100`
  → exactly 33 lines (= pointcnt/2 + 1; 129 at pointcnt 256; **sparse 200-point graph at
  pointcnt 1024 under-produced (111 lines) and broke the downstream count check**) →
  `spectrum fixed out.ana fmt.txt 64 44100 2.0` → exit 0, .ana of 2.026306 s (sfprops -d;
  2.074020 at pointcnt 256), **pvoc synth round-trip renders real audio (peak 1.0 — full
  scale; -a atten verified running)**.
- **Contracts verbatim:** `Data count (222) should be just 2 more than analysis-points
  parameter (1024)`; `ANALYSIS POINTS PARAMETER MUST BE A POWER OF TWO.`; srate
  `(44100.000000 to 96000.000000)`; dur `(0.100000 to 3600.000000)`.
- **Determinism:** .ana bytes differ between identical runs (header timestamp, byte ~179)
  but the RESYNTHESES decode byte-identical (sha 51dd6761 both) — content-deterministic.
  `spectrum format` itself byte-deterministic.
- Engine runs: fixed `ok` (spectral .ana path through arity-0 verified); format `ok`
  (data .txt output).

## 19. waveform (make 2) — CURATED

- `waveform make 2 tone2.wav out.wav 1.0 20` → 1806 frames = 40.95 ms ≈ 2×dur (zero-crossing
  quantized); 100 ms → 0.200000 exact on tone, 0.200045 on noise (+0.02%). Deterministic.
  Peak normalized 0.95.
- Ranges: time runtime `(0.000000 to 2.000000)` (input-dependent); dur `(1.000000 to
  10000.000000)` ms; fit check `Cannot cut duration 20.000000 mS, after time 1.990000 in
  infile.`; stereo refused `File st2.wav is not of correct type (must be mono)`.
- Modes 1 (half-waveset count; 402 frames from cnt 4 — data-dependent) and 3 (sinusoid
  blend) work but are uncurated siblings.
- Engine run: `ok`, dur 0.2000454.

## 20. tsconvert — DROPPED

`tsconvert in.txt out.txt 0 100` writes a correct rescaled file **but exits 1** (verified
twice, no error text, output valid). The engine requires exit_code == 0 for success
(`node_execution.py:228`) — every run reports subprocess_error. Broken exit contract; drop.

---

## Final row confirmations (all via process_impl, engine-emitted argv incl. defaults)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| synth spectra, dur 2.0 | 2.0 | 1.973696 | −1.32% |
| synth chord 1, dur 2.0 (aux midi) | 2.0 | 2.000000 | 0.00% |
| synth chord 2, dur 2.0 (aux frq) | 2.0 | 2.000000 | 0.00% |
| impulse, dur 2.0 | 2.0 | 1.996190 | −0.19% |
| motor 1, dur 3/pulse 1/pratio 0.7, indur 2.0 | 2.7 | 2.700000 | 0.00% |
| newsynth 1, dur 2.0 (aux spectrum) | 2.0 | 2.000000 | 0.00% |
| newsynth 5, dur 2.0 | 2.0 | 2.000000 | 0.00% |
| pulser 1, dur 3, seed 5, indur 2.0 | 3.365 | 3.236757 | +3.96% |
| chirikov 1, dur 2.0 | 2.0 | 2.000000 | 0.00% |
| newtex 1, dur 4.0, indur 2.0 (aux transposes) | 4.0 | 4.000000 | 0.00% |
| spectrum fixed, dur 2.0, pointcnt 64 (aux sp64) | 2.0 | 2.026306 | +1.32% |
| waveform make 2, dur 100 ms, indur 2.0 | 0.2 | 0.200045 | +0.02% |
| brownian 2, dur 3, flat band, seed 5, indur 2.0 | 5.0 | 4.865624 | −2.69% |

Null rows (aux-name duration expressions / data output / fixture-incompatible): synth
clicks 1, ceracu, synfilt 1, ts oscil, spectrum format, fractal wave 2 — each with reason
in the findings JSON; all six verified `ok` end-to-end through process_impl anyway.

19 entries shipped; 8 hard drops with evidence (synth silence, synth clicks sm2 flags,
pulser synth, strands, multisynth, frfractal, tsconvert, chirikov 3–4).
