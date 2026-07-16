# Tranche 15 — gesture/time-domain programs: probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build, -fsigned-char
  rebuild per forensics P6-1; `extend`/`sorter` banner "CDP Release 7.1 2016";
  `hover`, `hover2`, `shifter`, `repeater`, `verges`, `phasor`, `grainex`, `sfecho`
  print no release banner), Linux x86_64 sandbox. To be re-verified on macOS r8 by the
  CDP-gated suite after integration.
- **Inputs:** fresh fixtures in `/tmp/probe15b` — `ping3`/`ping6`/`tock4` (decaying
  sine pings, 0.3/0.6/0.4 s), `ev4` (2.0 s, 4 events with distinct levels
  0.15/0.60/0.35/0.80 AND durations 0.20/0.45/0.10/0.30 — the sorter fixture),
  `swp2` (2.0 s exponential sweep 200→2000 Hz with slow AM — position-distinctive for
  hover/drunk/repeater), `nz1`/`nz2` (1/2 s enveloped noise), `gtrain2` (2.0 s,
  16-grain train — grainex), stereo twins, plus `/tmp/probe/syl2.wav` (3.5 s syllable
  train) and `/tmp/probe/tone2.wav`/`st2.wav`.
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. Breakpoint proof =
  brk render differs from BOTH scalar-endpoint renders (at a fixed seed where one
  exists); determinism pairs launched > 1.2 s apart; shas over decoded float64
  samples; fresh output names per run; duration models at ≥ 2 input durations.
- **Priors:** afta8 covers most targets; SoundThread covers strans-like speed ops via
  modify speed. Source: `/tmp/CDP8/dev/extend/{ap_extend,iterate,extprepro}.c`,
  `dev/standalone/freeze.c`, `dev/science/repeater.c` (+ `include/science.h`).

Refusals quoted verbatim (stdout, exit 255 unless noted).

---

## 1. sorter modes 2 / 3 / 4 (siblings of curated 1/5 — re-verified per submode)

Working argv: `sorter sorter <m> ev4.wav out.wav 0.1 [-ssmooth]` — exit 0.

- **Same duration across modes 1–4:** all four rendered 1.8054 s / 79616 frames from
  ev4 (distinct shas). Flat-noise 2.0 s at esiz 0.1 → 1.9533 (−2.3%, the duration
  rows); nz1 1.0 s → 0.9005; esiz 0 on the sweep → 1.9995 (−0.03%).
- **Content proofs:** mode 2 third-RMS **0.343 / 0.310 / 0.062** (decrescendo; mode 1
  same fixture 0.107/0.209/0.403). Mode 3 element-group lengths at esiz 0.1:
  [0.45, 0.086, 0.194, 0.168]; mode 4 = the EXACT reverse — mirror pair. At esiz 0
  (wavesets) on `swp2`: mode 3 dominant frequency q1→q4 **268 → 1472 Hz** (longest
  wavesets first — "may rise in pitch" confirmed); mode 4 **1424 → 270 Hz**.
- **Determinism:** modes 2/3/4 pairs 1.3 s apart byte-identical (per submode).
- **Mono only:** `ERROR: File ev4st.wav is not of correct type (must be mono)` (each mode).
- **Ranges (verbatim, re-verified):** esiz `(0.000000 to 2000.000000)` (−1/2001);
  oversize `ERROR: Elementsize too big for infile. (If meant to be frq, set flag).`;
  smooth `(0.000000 to 50.000000)`; smooth brk → `Cannot read parameter 3 [...]:
  brkpnt_files not permitted.`; smooth changes render, never duration.
- **BUILD DIVERGENCE (first-class):** an **esiz brk file is ACCEPTED and LIVE on this
  rebuild**: constant-0.1 brk rendered **byte-identical** to scalar 0.1 (sha
  `344ea16605b9f1fd` both — positive control); `0.0 0.05/2.0 0.3` → 1.6507 s distinct
  sha; reversed ramp → 1.912 s. The macOS-r8-pinned sibling outcome
  (tests/test_breakpoint_curation.py) is refusal. Entries curated scalar-only,
  `version_sensitive: true`.

## 2. extend freeze, modes 1 / 2 (+ the standalone `freeze` drop)

Working argv: `extend freeze 1 nz2.wav out.wav outduration delay rand pshift ampcut
start end gain [-sseed]` / mode 2 replaces outduration with repetitions — exit 0.
Source: ap_extend.c:1149 maps `freeze` → ITERATE_EXTEND (iterate.c:303
`do_iteration_extend`; `out_sampdur -= insams − CHUNKEND` at iterate.c:352).

### 2.1 Duration models (exact, 4 dp)

Mode 1 (nz2 = 2.0 s unless noted), seg = [start,end]:

| outdur | delay | seg | actual | model `delay*(floor((outdur−indur+end−start)/delay)+1)+indur−512/sr` |
| --- | --- | --- | --- | --- |
| 4.0 | 0.5 | 0.5–1.0 | 4.9884 | 4.9884 |
| 3.0 | 0.5 | 0.5–1.0 | 3.9884 | 3.9884 |
| 4.0 | 0.25 | 0.5–1.0 | 4.7384 | 4.7384 |
| 4.0 | 0.25 | 0.2–0.5 | 4.4884 | 4.4884 |
| 3.0 (nz1 1.0 s) | 0.25 | 0.2–0.5 | 3.4884 | 3.4884 |
| 4.0 stereo | 0.3 | 0.5–1.0 | 4.6884 (2 ch) | 4.6884 |

Mode 2: `indur + reps*delay − 512/sr` exact on reps 5/2 (delay 0.5), reps 5 (0.25),
seg 0.2–0.5 (segment-independent!), fractional reps 2.5 → 3 (2.8884), delay 0
(1.9884 = indur − 512/sr — copies stack, terminates). The 512-sample deficit =
ITX_SPLICELEN, confirmed by the reversed-segment refusal quoting "needs 512 samples".

### 2.2 Content (swp2 sweep, mode 2 reps 3 delay 0.5 seg 0.5–1.0)

Pre-section = source × constant **0.6361** (std 0.0 — the 2-pass auto-level scales the
WHOLE output); original segment in place at 0.5; copies at start + k·delay − 512/sr
(xcorr onsets 0.9884/1.4884/1.9884, score 1.000); tail = source[end:] (corr 1.0).

### 2.3 Seed hunt (mode 2, rand 0.5)

`-s5` ×2 1.3 s apart → byte-identical; `-s9` differs; `-s0` ×2 → differ (clock);
unseeded ×2 → differ (clock); rand/pshift/ampcut all 0 → seed 5 == seed 9 == unseeded
byte-identical (inert). Durations drift 3.3066–3.7645 around 3.4884 with rand 0.5.

### 2.4 Breakpoints (mode 1, seed 5) and ranges

- delay brk 0.2→0.45 → 4.8091 vs endpoints 4.5884/4.6884 → **capable**; rand brk →
  4.699 vs 4.6884/4.6094 → **capable**.
- **SILENT-IGNORE BUG (first-class):** pshift brks 0→8 AND 8→0 both rendered
  **byte-identical to pshift 0** (sha `be16806182c5dede`; scalar 8 = `d9aa...`);
  ampcut brks 0→0.9 and 0.9→0 the same. Accepted syntactically, never applied.
- Refusals: outduration `Cannot read parameter 1`; start `6`; end `7`; gain `8`;
  seed `9`.
- Ranges (verbatim): gain `(0.250000 to 4.000000)` (5 and 0.2 refused); rand 0–1
  (Parameter[3]); pshift 0–12; ampcut 0–1; end `(0.000000 to 2.000000)` (= indur);
  outduration `(2.000000 to 32767.000000)` (floor = indur); reps
  `(1.000000 to 32767.000000)`; seed 0–32767. delay > seglen →
  `ERROR: FROZEN SEGMENT (13230 samples) TOO SHORT FOR (MINIMUM) DELAY TIME SPECIFIED
  (22050 samples)`; start > end → `ERROR: FROZEN SEGMENT (-22050 samples) TOO SHORT
  FOR SPLICING (needs 512 samples)` (no silent swap).

### 2.5 standalone `freeze` — DROPPED (source-diagnosed)

`freeze freeze 1 nz2.wav out.wav ...` → `ERROR: INTERNAL ERROR: (Bug?)` /
`ERROR: Failed to parse input file 1` — the "1" is the MODE DIGIT (mode 2 says
"input file 2"): freeze.c's CLI path never consumes the mode (dz->mode is only read in
`parse_sloom_data`, line 668 — Sound Loom only), so `parse_infile_and_check_type`
cdparse()s the digit. Without a digit: `ERROR: Unknown mode for ITERFREEZE: in
setup_freeze_param_ranges_and_defaults()`. PCM16 input identical. No working argv.

## 3. extend drunk, modes 1 / 2

Working argv m1: `extend drunk 1 swp2.wav out.wav outdur locus ambitus step clock
[-ssplicelen] [-cclokrand] [-ooverlap] [-rseed]`; m2 adds mindrnk maxdrnk (+ -l/-h).

- **Duration m1:** `outdur + splicelen/1000` EXACT — 3.015 from outdur 3 (132962
  frames, identical across seeds/walks/two indurs), 5.015 from 5, 3.005 at `-s5`.
  Broken by clokrand > 0 (1.0 → 3.0983) and by a clock brk (0.05→0.3 → 3.1967);
  overlap 0.9 → 3.005.
- **Seed (-r):** 5 ×2 → identical; 9 differs; **-r0 ×2 → differ (clock)** and an -r0
  run collided **byte-identically** with an unseeded run launched in the same second;
  unseeded ×2 1.3 s apart differ.
- **Breakpoints (all vs both endpoints at seed 5):** locus ✓, ambitus ✓, step ✓,
  clock ✓, clokrand ✓, overlap ✓ — banner's "all params EXCEPT outdur, splicelen and
  seed" confirmed slot-by-slot. Refusals: outdur `parameter 1`, splicelen
  `parameter 8`, seed `parameter 11`.
- **Ranges (verbatim):** locus/ambitus 0–indur; overlap `(0.000000 to 0.990000)`;
  clokrand 0–1; `-s50` at clock 0.1 → `ERROR: (minimum) clock value <= splicelen * 2
  [100.0 MS]: cannot proceed.` **BANNER DIVERGENCE:** step "> 0.002" NOT enforced —
  0.001 and 0 both exit 0. Stereo accepted (2 ch, model holds).
- **Mode 2:** outdur 4 → 4.109 / 4.6187 (seed 5, reproducible ×2) / 4.325 (seed 9) —
  set_by with sober-play overshoot; `-l0.2 -h0.5` → 4.4213 (row, tol 0.2). mindrnk 0 →
  `(1.000000 to 32767.000000)`; mindrnk 10 > maxdrnk 5 accepted (4.0449); `-l3.0` →
  `Parameter[12] Value (3.000000) out of range (0.000002 to 2.000002)`.

## 4. extend sequence (1-input sibling of curated sequence2)

Working argv: `extend sequence ping3.wav out.wav seq.txt attenuation` — exit 0.

- **Score format pinned vs sequence2:** 3-value rows `time semitone-transposition
  loudness`; NO sound-number, NO duration column (events never curtailed), NO
  notional-pitch line; transposition RELATIVE ±48 st:
  `ERROR: Pitch-ratio (130.000000) out of range (-48.000000 - 48.000000): OR data not
  grouped as time-transpos-level`.
- **Duration rule (sample-exact, 4 probes, 2 indurs):** `max_i(time_i +
  indur/2^(st_i/12))` — ping3 seq (0/+12/−12 at 0/0.5/1.0) → 1.6000; ping6 → 2.2000;
  3-note chord at t=0 → 0.3000.
- Stream parsing (one-line file byte-identical), `;` comments, decreasing times →
  `ERROR: Times do not increase at (0.200000): ...` (count%3≠0 fails with the SAME
  message — stream-parse side effect); negative loudness →
  `ERROR: Level (-0.500000) is less than zero: ...`; loudness 3 accepted (chord peak
  **2.229**, floats unclipped).
- attenuation `(0.000000 to 1.000000)` (1.5 refused); **0 = digital silence** (peak
  0.0000); brk refused `Cannot read parameter 1`. Deterministic ×2 ✓; stereo ✓ (2 ch).

## 5. hover / hover2 (compared; NEITHER subsumes — both curated)

hover argv: `hover hover swp2.wav out.wav frq loc frqrand locrand splice dur`;
hover2 drops splice, adds `[-s] [-n]`.

- **hover:** dur 3 → 3.0142, dur 2 → 2.0245 (set_by, +0.5–1.2%). frq brk 5→40 →
  3.0185/`76ca...` vs endpoints → ✓; loc brk 0.2→1.8 ✓; frqrand brk ✓; locrand brk ✓;
  splice/dur refuse (parameters 5/6). **frqrand/locrand 0.5 pairs 1.3 s apart
  BYTE-IDENTICAL** — fixed-sequence, no seed slot. MONO only (verbatim). frq
  `(0.250000 to 22050.000000)`; loc 0–indur; splice at frq 200 →
  `ERROR: Splicelen incompatible with maximum frequency: must be less than 2.494331 mS`.
- **hover2:** dur 3 → 3.0486, dur 2 → 2.0491 (+1.6–2.5%). frq brk ✓, loc brk ✓ (both
  vs both endpoints). **-s STEP semantics verified:** loc brk 0.2→1.8 WITH -s rendered
  byte-identical to scalar loc 0.2 (`e2f397edf07e1829` both — the step at t=3.0 never
  plays); without -s the interpolating read differs from both endpoints. -n changes
  render, same length. Fixed-sequence rand; mono-only; deterministic ×2 ✓.

## 6. strans vs modify speed → vibrato curated as modify speed 6; strans DROPPED

- Twin comparison on tone2: strans 1 (×1.5) vs modify speed 1: 58800 frames both,
  different shas; strans 2 (−5 st) 117733 vs speed-2 117732 frames; strans 3 vs
  speed 5: 55336 both, different shas; strans 4 vs speed 6: 88181 vs 88182. Same
  processes, ±1-frame rounding — near-duplicates of curated entries.
- **STEREO CORRUPTION (the decisive drop evidence):** `strans multi 4 st2.wav` (2.0 s
  stereo) → **2.9711 s** (131026 frames); `modify speed 6` same fixture → 1.9996 ✓;
  `strans multi 2` stereo → 2.6697 ✓ (mode-4-specific interleave bug).
- **modify speed 6 (curated):** deterministic ×2; depth 0 → 2.0000 exact; 0.5 →
  1.9996 (−0.02%); 1.5 → 1.9962; **24 → 1.2377 (−38%)** — resampling asymmetry.
  vibfrq brk 2→10 → `d283...` vs `506c/93de` ✓; vibdepth brk 0→1.5 → 2.0011/`09ae...`
  vs 2.0000/1.9962 ✓. Ranges: vibfrq `(0.000000 to 120.000000)`; vibdepth
  `(0.000000 to 96.000000)`.

## 7. sfecho

Working argv: `sfecho echo ping3.wav out.wav delay attenuation totaldur [-rrand]
[-ccutoff]` — exit 0.

- **Duration (exact ×3):** `delay*floor((totaldur−indur)/delay) + indur` — 0.5/0.5/5 →
  4.8; totaldur 3 → 2.8; atten 0.9/totaldur 20 → 19.8. Cutoff engaged: `-c-40` →
  3.5 s. Engine spot-check: delay 2/totaldur 7 on 2 s → 6.0000 exact.
- **delay floor = indur:** `Parameter[1] Value (0.200000) out of range (0.300000 to
  3600.000000)`; enforced INSIDE brks: `ERROR: Value (0.100000) out of range
  (0.300000 to 3600.000000) in brkpntfile b_bad.brk.`
- Brk proofs vs both endpoints: delay (4.796/`02b9...`) ✓; attenuation (`5102...`) ✓;
  rand (`ece6...` vs `c398`/`eacb`) ✓. totaldur refused (`parameter 3`).
- **rand fixed-sequence:** `-r0.5` ×2 1.3 s apart byte-identical (4.9613 both) — no
  seed. atten 1.5 / rand 1.5 refused 0–1; cutoff 5 → `(-96.000000 to -6.000000)`.
  Deterministic ×2 ✓; stereo ✓.

## 8. verges

Working argv: `verges verges swp2.wav out.wav vt1.txt [-ttransp] [-eexp] [-ddur]
[-n] [-b|-s]` (vt1.txt = `0.4/1.0/1.6`) — exit 0.

- **Duration static-with-drift:** base (transp default 5) 1.9497 (−2.5%); `-t-8` →
  2.0554 (+2.8%); `-t9` → 1.8976 (−5.1%).
- Brk proofs vs both endpoints: transp 2→9 ✓ (`e26b...`); exp 2→7 ✓; glissdur 50→250 ✓.
- Ranges: transp `(-24.000000 to 24.000000)`; exp `(1.000000 to 8.000000)`; glissdur
  `(20.000000 to 1000.000000)`. Times file: decreasing →
  `ERROR: Times (1.000000 & 0.400000) not in increasing order at line 1 in file
  vtbad.txt.`; too near the end → `WARNING: Ignoring data at and after this time.` +
  `ERROR: Gap between last verge time and end of src insufficent (gap -77 samps reqd
  5150)` (at `-d400`: `gap 17575 samps reqd 20595`).
- Flags: -n / -b change render (same length); **-s keeps only verge material**
  (1.668 s). Deterministic ×2 ✓; stereo accepted (2 ch, same frames).

## 9. grainex

Working argv: `grainex extend syl2.wav out.wav wsiz trof plus stt end` — exit 0.

- **Duration:** syl2 (3.5 s): plus 2.0 → **5.4998**, plus 1.0 → **4.4999** (indur +
  plus, exact). gtrain2 (2.0 s, 16 grains): plus 1.5 → **5.2622** (+1.76 beyond),
  plus 0.5 → 4.2051 (+1.71) — grid-rounded overshoot, content-dependent → row null.
- **Content refusal:** `INFO: Number of grains found = 0` →
  `ERROR: Insufficient grains to proceed.` (single sustained event, trof 0, trof 1,
  plus 0, reversed zone). trof 0.3 == 0.9 byte-identical on gtrain2 (detector
  saturates).
- ALL FIVE params refuse brks (`Cannot read parameter 1..5`). Mono only (verbatim).
  wsiz `(0.181406 to 666.666667)`; end 0–indur; plus `(0.000002 to 3600.000000)`.
  Deterministic ×2 ✓.

## 10. repeater, modes 1 / 3 (mode 2 rule pinned, execute())

Working argv: `repeater repeater 1 swp2.wav out.wav rp1.txt [-rrand] [-prand]`
(rp1.txt = `0.5 0.7 3 0.25`); mode 3 appends `accel warp fade`.

### 10.1 Duration rule (exact ×6 incl. 2-element file)

added per element (len = end−start): **delay ≤ len → cnt·delay** (0.5–0.7 cnt 3
delay 0.1 → 2.3; boundary delay 0.2 → 2.4); **delay > len → cnt·delay − (len +
0.005)** (delay 0.25 → 2.545; nz1 len 0.2 cnt 2 delay 0.3 → 1.395; len 0.3 cnt 2
delay 0.4 → 2.495 predicted & rendered). 0.005 = REPSPLEN 5 ms (science.h:439).
2-element file → 3.04 = 2.0 + 0.545 + 0.495 ✓. **Mode 2 (offset):** added =
cnt·(len+offset+0.005) − (len+0.005) — 3.16 and 2.405 both exact. **Mode 3:** accel 2
→ 2.3575 (< mode-1's 2.545) — accel-dependent, no closed form.

### 10.2 Banner lie + fixed sequence + landmines

- `[-sseed]` printed in usage; ANY -s placement → `Unknown flag -s on command line.`
- `-r1.5` ×2 and `-p3` ×2 (1.3 s apart) byte-identical — **fixed-sequence**.
- **delay 0** (documented "= segment length") → `ERROR: INTERNAL ERROR: (Bug?)` /
  `ERROR: segment buffer too short to contain repeated overlapping segments (1).`;
  `-p5`/`-p6` on the 0.2 s element → same crash.
- Datafile refusals: `Segment on line 1 in file "rpbad1.txt", dur 0.005000, too short
  for splicing (min dur 0.010068).` (end<start reports dur −0.2 the same way);
  `Too few values (3) on line 1 in file "rpbad3.txt": Need 4.`;
  `Repeat value less than 2 on line 1 in file "rp8.txt".` Overlap/backtrack legal ✓.
- Brk proofs: rand 1.0→1.9 → 2.6206/`d21d...` vs 2.545/2.999 ✓; prand 0→3 →
  `50e5...` vs `3895`(0)/`c66b`(3) ✓; in-brk range check verbatim (`Value (0.000000)
  out of range (1.000000 to 2.000000) in brkpntfile b_h1.brk.`).
- Ranges: rand m1 `(1.000000 to 2.000000)` / m2 `(1.000000 to 8.000000)`; prand 0–12;
  m3 accel `(1.000000 to 10.000000)`, warp/fade `(0.100000 to 10.000000)`. Mode 3
  deterministic ×2 ✓ (fade 2 changes render). Stereo accepted.

## 11. phasor

Working argv: `phasor phasor tone2.wav out.wav streams phasfrq shift ochans
[-ooffset]` — exit 0.

- Duration: 2.0005 from 2 s (offset 0); `-o200` → 2.2005 (**indur + offset/1000**);
  nz1 → 1.0003. Deterministic ×2 ✓. ochans 1 ✓ and 2 ✓.
- Brk proofs vs both endpoints: phasfrq 1→8 → 2.0071/`bfd5...` ✓; shift 0→6 →
  `9e7b...` ✓.
- Ranges: streams `(2.000000 to 8.000000)`; shift 0–12; offset `(0.000000 to
  500.000000)`; ochans 5 > streams 4 → `ERROR: INVALID DATA` / `ERROR: Number of
  output channels exceeds number of streams.` Stereo input refused (must be mono).

## 12. shifter, mode 1 (mode 2 verified variadic — execute())

Working argv: `shifter shifter 1 ping3.wav out.wav cyc1.txt cycdur dur ochans subdiv
linger transit boost [-z|-r] [-l]` (cyc1.txt = `3 4`) — exit 0.

- Duration: dur 6 / cycdur 1 → **6.0000 exact** (0.3 s source); dur 4 → 4.05; 25-beat
  cycle → 6.26. **SOURCE-LENGTH OVERHANG:** 2 s source at 0.25 s beats → **7.6875**
  from dur 6 (≈ last onset + indur) — row pinned at indur 0.3.
- Deterministic ×2 ✓. **-r random order ×2 1.3 s apart byte-identical** (fixed
  sequence, no seed). **-z no-op with 2 cycles** (byte-identical — orders coincide).
- Constraints verbatim: `Found cyclelength value 0 in file cycbad.txt: Cyclelength
  values must be >= 2`; subdiv 5 → `ERROR: Neat subdivision is not a multiple of 2 or
  3.`; linger 0 + transit 0 → `ERROR: Linger and Transit parameters must add to >= 1.`;
  boost −1 → `(0.000000 to 10.000000)`; boost 0 legal (distinct render). cycdur/boost
  brks refused (parameters 1/7). ochans 1/2/3 all run; mono input only (verbatim).
- Mode 2: 2 inputs + 2 cycles → 6.0875 ✓; count mismatch → `ERROR: Number of
  cyclelengths (1) found in file cyc0.txt does not tally with number of src sounds (2)`.

## 13. Drops (see findings JSON for the full evidence)

- **freeze** (standalone): CLI never parses the mode digit (Sound Loom-only path) — §2.5.
- **packet:** output argv is a stem — single time 0.8 wrote `pk30.wav`, times file
  wrote `pmulti0.wav`+`pmulti1.wav`; documented centring −1 unreachable (parses as a
  flag, exit −11 segfault); mode 1 content-refuses on smooth material
  (`Insufficient local minima found in inital search.`).
- **stretcha:** stdout calculator (`Stretchfactor = 0.857143`, exit 0, no outfile).
- **strans:** near-duplicate of modify speed 1/2/5 (±1 frame) + mode-4 stereo
  corruption — §6.
- **unknot:** textfile-in/textfile-out pattern transformer (`Cannot open a textfile
  (uo3.wav) with a reserved extension.`); sync constraints
  (`ALL EVENTS BUT ONE ARE SYNCHRONOUS: CANNOT PROCEED`); mode 3 = count-only.

---

## Engine spot-checks (process_impl end-to-end, entries as written, CDP_PATH=/tmp/CDP8/NewRelease)

| entry | params | predicted | measured | verdict |
| --- | --- | --- | --- | --- |
| extend freeze sm1 | outduration 6, delay 0.4, seg 0.5–1.0, gain 1, seed 1 | 6.7884 | 6.7884 | exact |
| extend drunk sm1 | outdur 4, locus 1, ambitus 0.5, step 0.1, clock 0.1, splice 15, seed 1 | 4.015 | 4.0150 | exact |
| sfecho | delay 2, atten 0.5, totaldur 7 | 6.0 | 6.0000 | exact |
| sorter sm3 | esiz 0.1 | 2.0 (static) | 1.9518 | −2.41% (tol 0.05) |
| verges (aux vt3.txt) | defaults | 2.0 (static) | 1.9497 | −2.51% (tol 0.05) |
| shifter sm1 (aux cyc1.txt) | cycdur 1, dur 6, 0.3 s fixture | 6.0 | 6.0000 | exact (aux-datafile check) |

(The first shifter spot-check on the 2.0 s fixture measured 7.6875 — the
source-length overhang; the entry and row were amended to pin a 0.3 s source.)

Eighteen entries shipped; five programs dropped with evidence (freeze, packet,
stretcha, strans, unknot). Aux-file duration rows reference `cyc1.txt` (`3 4`) and
`vt3.txt` (`0.4/1.0/1.6`) — contents above for `_AUX_FILES`. Datafile-driven duration
rules pinned here for repeater modes 1/2/3 and extend sequence (rows null).
