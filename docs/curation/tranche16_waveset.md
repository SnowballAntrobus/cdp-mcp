# Tranche 16 — waveset/distort extensions probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build, `-fsigned-char`;
  distort banners self-report "CDP Release 7.1 2016"; the standalone programs print no
  release banner), Linux x86_64 sandbox. Source consulted at `/tmp/CDP8/dev`.
- **Inputs:** `/tmp/probe` reused (tone1/tone2 440 Hz sines 1 s/2 s, n1/n2 enveloped noise,
  st2 stereo noise) plus fresh fixtures in `/tmp/probe16a`: `fn1/fn2` flat noise matching the
  duration-row fixture (`np.random.default_rng(0).standard_normal * 0.2`), `sw1/sw2` 220→880 Hz
  linear sweeps, `tb2/tb3` 330 Hz tone-burst trains (5/s, exp decay), `ct2` **unipolar** click
  train (positive-only, zero crossings touch but never cross — the P5-4 trap detector).
- **Methodology:** tranche-2 verbatim. Breakpoint proof = brk render differs from BOTH scalar
  endpoint renders (sha256 of float64-decoded samples); determinism pairs launched > 1.1 s
  apart; fresh output names every run; duration models at ≥ 2 input durations; refusals quoted
  verbatim (exit 255 unless noted). For the clock-seeded program (distort pitch) breakpoint
  proofs use **seed-matched same-second triplets** (two identical-argv runs colliding
  byte-identically proves the shared seed; the brk render in the same second differing from
  both endpoints is then a valid proof).

All 22 curated entries below were spot-checked or row-verified; 7 end-to-end
`process_impl` runs pass (see §Verification).

---

## 1. distort replim — CURATED

Working argv: `distort replim tone2.wav out.wav 3 -f800` — exit 0.

| input | mult | flags | outdur | predicted `indur*mult` |
| ----- | ---- | ----- | ------ | ---------------------- |
| tone2 2.0 | 3 | -f800 | 5.9932 | 6.0 |
| tone2 2.0 | 3 | (none) | 5.9932 (byte-identical to -f800) | 6.0 |
| tone2 2.0 | 2 | -f800 | 3.9955 | 4.0 |
| tone2 2.0 | 12 | -f800 | 23.9728 | 24.0 |
| tone1 1.0 | 3 | -f800 | 2.9932 | 3.0 |
| sw2 2.0 | 3 | -f440 | 5.9966 | 6.0 |
| fn2 2.0 | 3 | (none) | 5.9971 | 6.0 |

- **SEMANTICS (source-settled):** hilim is NOT a filter. `distrpt.c:490 distort_rpt_frqlim`
  ("don't count too-short cycles"): `mincyclen = srate/hilim`; zero-crossing cycles accumulate
  into one counted unit until ≥ mincyclen. Everything is repeated — a 220→880 sweep at
  `-f440` still stretches ×3 in full. Duration model = `indur * multiplier`, worst 0.11%.
- hilim range HARDCODED 440–nyquist (`tklib1.c: ap->lo[DISTRPT_CYCLIM] = 440.0`, CONCERT_A;
  refusal `Parameter[4] Value (200.000000) out of range (440.000000 to 22050.000000)`);
  default 1000 (`CYCLIM_DFLTFRQ`, distcon.h:70) — flag-less == `-f800` byte-identical on a
  440 Hz tone (both group identically).
- **Breakpoints:** multiplier brk (2→12) → 13.9727 s, differs from both endpoints →
  **capable**. cyclecnt `-c` brk (2→8) → 5.9659, differs from both `-c2`/`-c8` → **capable**.
  skip `-s` / hilim `-f`: `Cannot read parameter 3/4 ... brkpnt_files not permitted.`
- ct2 unipolar refused `CANNOT ACHIEVE TASK / source sound too short to attempt this process.`
  Stereo refused (`Application doesn't work with this type of infile.`). Deterministic.

## 2. distort reverse — CURATED

`distort reverse tone2.wav out.wav 4` — exit 0.

- **Static, sample-exact** (88200/44100 frames) on tone2/tone1/n2/fn2 at cyclecnt 1–30.
- cyclecnt range 1–32767 (0 refused verbatim); cyclecnt 1 legal (per-cycle flip).
- Brk (2→30) differs from both endpoints → **capable**. Deterministic (1.2 s pair identical).
- ct2 refused (`source sound too short`); stereo refused → mono.

## 3. distort envel, submode 2 — CURATED

`distort envel 2 tone2.wav out.wav 20` — exit 0. Falling envelope per cyclecnt-group.

- **Static, sample-exact** everywhere (tone2/tone1/fn2/ct2 — note ct2 unipolar is ACCEPTED,
  whole file = few giant wavesets, full-length output).
- Ranges verbatim: cyclecnt `(1.000000 to 1000.000000)`; troughing `-t` `(0.000000 to
  1.000000)`; exponent `-e` `(0.020000 to 50.000000)` (omitted = linear).
- **All three brk-capable** (each differs from both endpoints): cyclecnt 5→60; troughing
  0→0.9 (vs -t0-default and -t0.9); exponent 0.5→4.
- Submode 4 argv order pinned: `envel 4 in OUT envfile cyclecnt` (envfile before outfile
  fails `Cannot open output file uenv.txt`). Submodes 1/3 verified distinct renders.
- Stereo refused verbatim; deterministic.

## 4. distort harmonic — CURATED

`distort harmonic tone2.wav out.wav harm1.txt` (harm1.txt `2 0.5\n3 0.3\n`) — exit 0.

- **Static, sample-exact** (tone2/tone1/fn2). Deterministic (1.2 s pair identical).
- Harmonics file range verbatim: `Error in harmonics file - harmonic number [1030] out of
  range 2 - 1024`. `-p0.5` exactly halves output peak (0.3652 vs 0.7304); `-p` brk refused
  (`Cannot read parameter 1`). No time-variable parameter.
- ct2 refused: `WARNING: Program assumes maximum wavelength is 0.500000 secs. / WARNING:
  Wavelength too long at infile time 0.000000 secs. / ERROR: CANNOT ACHIEVE TASK:`.
- Stereo refused → mono.

## 5. distort pitch — CURATED (clock-seeded stochastic)

`distort pitch tone2.wav out.wav 0.5` — exit 0.

- **CLOCK-SEEDED, UNSEEDABLE:** no seed argv. Runs in different seconds differ (content AND
  length: 2.0828 vs 1.9882 at octvary 0.5); runs in the SAME second byte-identical (observed
  both directions across several trials — modify shred's `srand(time(0))` construction).
- **Duration static-with-spread:** flat noise at octvary 0.1: 1.9994/1.9982/1.9987 (≤0.1%);
  octvary 0.5: ±4%; octvary 2 on tone: +30% (2.5947). Row pinned at octvary 0.1.
- **Seed-matched brk proofs (same-second triplets):** octvary brk 0.1→2 differs from both
  scalar endpoints while flanking identical-argv runs collide (sha q1==q4) → **capable**;
  cyclelen `-c` brk 4→100 same construction (c1==c4 collision; c3 differs from c1/c2) →
  **capable**. skip `-s` brk refused (`Cannot read parameter 3`).
- Ranges verbatim: octvary `(0.000002 to 8.000000)` — but **0 is accepted** (near-passthrough
  1.9977, undocumented); cyclelen `(2.000000 to 32767.000000)` (1 and 1.5 refused; default 64).
- ct2 refused `Cycle too large for buffer at 1.486077`; stereo refused → mono.

## 6. distort telescope — CURATED

`distort telescope tone2.wav out.wav 4` — exit 0.

| input | cyclecnt | flags | outdur | predicted `indur/cyclecnt` |
| ----- | -------- | ----- | ------ | -------------------------- |
| tone2 | 2 | | 1.0000 | 1.0 |
| tone2 | 4 | | 0.5011 | 0.5 |
| tone2 | 16 | | 0.1237 | 0.125 |
| tone2 | 30 | | 0.0664 | 0.0667 |
| tone1 | 4 | | 0.2494 | 0.25 |
| fn2 | 4 | | 0.7729 (**+55%**) | 0.5 |
| fn2 | 4 | -a | 0.5158 (+3.2%) | 0.5 |
| fn1 | 4 | -a | 0.2577 (+3.1%) | 0.25 |

- Default telescope-to-LONGEST runs long on noise; `-a` (average) rescues the model — row
  pinned with `average=1`.
- cyclecnt 2–32767 (1 refused); brk (2→30) → 0.1968, distinct from both endpoints →
  **capable**. `-s` brk refused (`parameter 2`); `-s100` DROPS material (0.5011→0.4439 =
  −100cyc/4 at 440 Hz).
- ct2 refused; stereo refused verbatim; deterministic.

## 7. distort filter, submode 1 — CURATED (zero-output trap)

`distort filter 1 sw2.wav out.wav 440` — exit 0.

| input | mode | freq | outdur | note |
| ----- | ---- | ---- | ------ | ---- |
| tone2 | 1 | 300 | 1.9977 | all kept |
| tone2 | 1 | 600 | **0 frames, exit 0** | ALL cycles below freq |
| sw2 | 1 | 440 | 1.3344 | = time above 440 (crossing 0.667 s) |
| sw2 | 1 | 250 | 1.9054 | |
| sw2 | 1 | 800 | 0.2567 | |
| sw2 | 2 | 440 | 0.6758 | = time below 440 |
| sw2 | 3 | 300 600 | 0.9124 | = time in band (0.242–1.152) |
| fn2 | 1 | 440 | 1.9999 | noise cycles ~all high |
| fn2 | 2 | 440 | **0 frames, exit 0** | |
| ct2 | 1 | 300 | **0 frames, exit 0** | unipolar |

- **ZERO-OUTPUT TRAP (P5-4 confirmed for this program):** total filtering → exit 0, 0-frame
  file, sole symptom `WARNING: Can't close output sf-soundfile : can't truncate SFfile`.
- **No silent swap in mode 3:** `600 300` → the trap output, not the band (contrast sfedit cut).
- freq brk (250→800 on sw2) → 1.8780, distinct from both endpoints → **capable**;
  `-s` brk refused (`parameter 3`). freq range verbatim `(10.000000 to 22050.000000)`.
- Duration = time-in-band (content-dependent); entry pins `static` as documented upper bound,
  row on flat noise mode 1 freq 440 (1.9999). Deterministic; stereo refused.

## 8. distort overload, submodes 1 & 2 — CURATED (clip/gate brk broken)

`distort overload 1 tone2.wav out.wav 0.3 0.5` / `distort overload 2 ... 0.3 0.5 880` — exit 0.

- **Static, sample-exact** both modes (tone/flat noise/**ct2 accepted** — level-domain).
  Deterministic BOTH modes (mode 1's "noise" fill is unseeded → byte-identical pairs).
- **CLIP_LEVEL/GATE BRK BROKEN (first-class):** brk in slot 1 exits 0 but renders a fixed
  near-silent buzz (peak 0.0099, uniform RMS 0.0075) REGARDLESS of values — ramps 0.2→0.8
  and 0.3→0.30001 byte-identical to each other, unlike any scalar. → capable=false.
- depth brk healthy (0.1→1.0 differs from both endpoints; near-constant brk ≈ scalar but
  distinct path, sane). freq brk healthy (200→2000 differs from both; near-constant
  880→880.01 **byte-identical to scalar 880**). → depth/freq **capable**.
- clip 0 accepted → **digital silence** (88200 frames, peak 0.0000). Output peak scales
  ~clip/(1+clip) (0.2308 at 0.3, 0.1667 at 0.2).
- Ranges verbatim: clip/depth `(0.000000 to 1.000000)`; freq `(0.010000 to 22050.000000)`
  (0.05 accepted). Stereo refused → mono.

## 9. distort pulsed, submode 1 — CURATED

`distort pulsed 1 tone2.wav out.wav ienv.txt 0 2.0 5 0 0 0 trz.txt 0` — exit 0
(ienv.txt `0 0/0.3 1/1 0`; trz.txt `0 0/1 0`).

| stime | dur | frq | flags | outdur | model |
| ----- | --- | --- | ----- | ------ | ----- |
| 0 | 2.0 | 5 | | 1.8002 | 2−1/5 = 1.8 |
| 0 | 2.0 | 2 | | 1.5000 | 1.5 |
| 0 | 2.0 | 3 | | 1.6667 | 1.6667 |
| 0 | 2.0 | 10 | | 1.9000 | 1.9 |
| 0 | 2.0 | 20 | | 1.9500 | 1.95 |
| 0 | 1.0 | 5 | | 1.0000 | dur (fits) |
| 0.5 | 1.0 | 5 | | 1.0000 | dur (fits) |
| 0.5 | 1.0 | 5 | -s | 1.5012 | +stime |
| 0.5 | 1.0 | 5 | -s -e | 2.0058 | +tail |
| 0 (tone1) | 1.0 | 5 | | 0.8001 | 1−1/5 |
| fn2/ct2 | 2.0 | 5 | | 1.8002 | content-independent |

- **Model:** `(dur if stime + dur < indur else dur − 1/frq)`; keep_start adds stime,
  keep_end adds indur−(stime+dur) (documented, additive, ~0.3% splices).
- frq brk (3→20) → 1.9553, distinct from both endpoint renders → **capable**. frand brk
  refused (`Cannot read parameter 4`).
- **All randomisation deterministic:** frand 6/trand .5/arand .5/tranrand .5 pairs 1.2 s
  apart byte-identical (unseeded generator; no seed argv).
- Ranges verbatim: frq `(0.100000 to 50.000000)`; frand `(0.000000 to 12.000000)`; trand
  `(0.000000 to 1.000000)`; stime `(0.000000 to 2.000000)` (=indur). **tranrand 1.5 ACCEPTED**
  despite banner 0–1 (unenforced). ct2 accepted; stereo refused → mono. Modes 2–3 (cyctime
  loop-grab variants) left to execute().

## 10. distort repeat2 — CURATED

`distort repeat2 tone2.wav out.wav 3` — exit 0.

- **Static:** 1.9976 (×3), 2.0005 (×2), 2.0182 (×12, +0.9%), 1.0021 (tone1), 1.9880 (n2),
  2.0038 (fn2), 1.9908 (-c4).
- multiplier 2–32767 (1 refused); brk (2→12) differs from both endpoints → **capable**.
  cyclecnt `-c` brk (2→8) differs from both `-c2`/`-c8` → **capable**. `-s` brk refused
  (`parameter 3`); `-s100` drops 0.227 s (→1.7727).
- ct2 refused (`source sound too short`); stereo refused verbatim; deterministic (pair
  identical 1.2 s apart).

## 11. distrep (mode 1 CURATED; mode 2 DROPPED — hang)

`distrep distrep 1 tone2.wav out.wav 3 1` — exit 0.

- Mode 1 duration `indur*multiplier`: 5.9931 (×3), 3.9818 (×2 c4), 2.9931 (tone1),
  **5.9998 flat noise**, brk (2→12) 13.9727. multiplier brk **capable** (differs both);
  cyclecnt brk (2→8) 5.9659 differs from both scalars → **capable**.
- **MODE 2 HANG (drop evidence):** `distrep 2 tone2.wav out 3 1` — killed at BOTH 30 s and
  40 s timeouts (exit 124), 0-frame output; same argv fine at mult 2 (2.0005), on tone1
  (1.0020), on fn2 (2.0003), sw2, tb2. Input-dependent infinite loop.
- `-k100` skip drops material (5.3114 ≈ (2−0.227)×3). **Splice geometry quirk
  (source-settled):** `-s5/-s30/-s50` byte-identical at cyclecnt 1 on 440 Hz — distrep.c:1174
  clamps the splice to half the repeated group when the group < 2 splices; at cyclecnt 40 the
  same flags render distinct (same length 5.7272, different shas). Default 15 ms.
- Ranges verbatim: multiplier `(2.000000 to 32767.000000)`; cyclecnt `(1.000000 to ...)`.
- ct2: `CANNOT ACHIEVE TASK / No output created.`; stereo: `File st2.wav is not of correct
  type (must be mono)`. Deterministic. Splices attenuate small groups (peak 0.5→0.4207 at c1).

## 12. distshift (mode 1 CURATED; mode 2 DROPPED — corrupt output)

`distshift distshift 1 tone2.wav out.wav 1 1` — exit 0.

- Mode 1 **static, sample-exact** (tone2/tone1/fn2; fn2 peak normal 0.79). Deterministic.
- **MODE 2 CORRUPTION (drop evidence):** exit 0 but flat noise renders contain astronomically
  corrupt samples — peak **1.143e+17** (fn2, 59 samples = 0.07%, first at t=0), peak
  **3.8e+26** (fn1). Tones (peak 0.5) and tb2 (0.888) clean — input-dependent memory bug.
- grpcnt/shift both 1–32767 (0 refused verbatim); both refuse brks (`Cannot read parameter
  1/2`). ct2: `Failed to find any half-wavesets.` Stereo: must-be-mono verbatim.

## 13. distortt repeat — CURATED (offset-0 bug, source-diagnosed)

`distortt repeat tone2.wav out.wav 1 3 100 4` — exit 0 → **4.0000 sample-exact**.

- **Duration:** exactly `dur` when reachable (4.0000 tone2+fn2; 2.0000 tone1) else the
  material bound `offset/1000 + (indur−offset/1000)*rpt` (5.7943 vs 5.8 predicted, dur 8).
  gpcnt doesn't change it (4.0000 at gpcnt 4).
- **OFFSET 0 BROKEN:** `1 3 0 4` → `ERROR: CANNOT ACHIEVE TASK: / ERROR: Failed to find start
  of wavesets (1).` after writing dur-seconds of... nothing; `1 3 0 8` exits 0 with the FIRST
  4.0055 s DIGITAL SILENCE. Source: science/distortt.c — with startsamp 0 the pre-offset copy
  loop never reads input, so `get_initial_phase` scans an unread buffer and zeros stream out.
  offset ≥ 1 ms (even 1) behaves perfectly (4.0000 from `1 3 1 4`). Entry floors offset at 1 ms.
- `-t` telescope: 2.0035 ≈ indur (model suspended; documented). ct2 + offset: exit 0 but
  output = offset prefix only (0.1050 s) — truncation trap, documented.
- Ranges verbatim: gpcnt `(1.000000 to 256.000000)`; rpt `(2.000000 to 16.000000)`; offset
  `(0.000000 to 2000.000000)` (=indur ms). gpcnt/rpt brks refused (`parameter 1/2`).
- Stereo must-be-mono verbatim. Deterministic (identical re-runs).

## 14. distmark, mode 1 — CURATED

`distmark distmark 1 sw2.wav out.wav marks4.txt 40` (marks 0.25/0.75/1.25/1.75) — exit 0.

| variant | outdur | rule |
| ------- | ------ | ---- |
| base (sw2) | 1.7589 | ≈ mark1 + span×1 = 1.75 |
| 2 marks 0.25/1.75 | 1.7863 | 1.75 |
| tone2 | 1.7647 | 1.75 |
| -s2 | 3.2661 | 0.25+1.5×2 = 3.25 |
| -s1.5 | 2.5326 | 2.50 |
| -t (sw2) | 1.9676 | ≈ indur |
| -t (fn2) | 1.9420 | ≈ indur (row) |
| -r0.5 | 1.5858 | rand shrinks (−10%) |

- Duration ≈ firstmark + (lastmark−firstmark)×tstretch (+tail with -t); aux-dependent → entry
  pins `static`, row with keep_tail=1.
- unitlen brk (30→100) differs from both endpoints → **capable**. Constraint verbatim: `Max
  dur of waveset-units (0.300000 secs) greater than 1/2 of min step between marks (0.250000
  secs).` tstretch range `(1.000000 to 256.000000)`; ~100 dies `INTERNAL ERROR: (Bug?) /
  Memory store for sizes of intermediate waveset-groups (104), not large enough (1221
  needed).` rand `(0.000000 to 1.000000)`; `-r0.5` pairs byte-identical (deterministic rand).
- ct2 refused `No waveset-group start found (2) at time 0.250000 (Buffer too short?)`;
  stereo must-be-mono. Mode 2 (alternate blocks) probed: 2.0128, distinct render.

## 15. distmore suite (bright / double / segsbkwd / segszig)

### double — CURATED
- `distmore double tone2.wav out 1` → 1.9977; **FFT-verified 440 → exactly 880 Hz** (mult 1);
  mult 2 → 1696 Hz ≈ ×4, duration +3.6%. fn2 1.9999 (row). mult range verbatim `(1.000000 to
  4.000000)`; brk refused. **SEGFAULT on ct2 (unipolar): exit 139, no message, no output.**
  Stereo must-be-mono. Deterministic.

### segszig, mode 2 — CURATED
- repets 4 → 15.8949 (2 s); 8 → 31.7748; 2 → 7.9550; sw1 4 → 7.8949; **fn2 identical
  15.8949** → model `indur * 2 * repets * prop` (worst −1.3%; prop 0.2 → 3.0949 vs 3.2).
- **BANNER DIVERGENCE:** repets and prop both labelled "(timevariable)" but brks REFUSED
  (`Cannot read parameter 1/4 ... brkpnt_files not permitted.`).
- **MODE 3 dur INERT:** `segszig 3 sw2 out 4 5.0` byte-identical to `segszig 2 sw2 out 4`
  (sha 4dcba82d..., 15.8949) — the duration-targeting positional does nothing.
- `-s100` (shrinkto) shortens below model (17.5272 at repets 8). Deterministic; must-be-mono.

### segsbkwd, mode 3 — CURATED
- Static **sample-exact** (2.0000: sw2, fn2, ct2 — unipolar ACCEPTED, mark-based cutting).
  Modes 1 and 3 render distinct. `Insufficient data (1 values) in file m1.txt : Need at least
  4` verbatim; must-be-mono; deterministic (fn2 pair identical).

### bright — probed, not curated (attrition)
- `distmore bright 2 sw2 out marks4.txt` exit 0 → 1.7500; `-d` changes render. Head/Tail
  pairing semantics + brightness sort left for a later tranche; no blocking defect found.

## 16. distcut — DROPPED (multi-output, no outfile argv)

`distcut distcut 1 sw2.wav cutx 50 1` — exit 0 → wrote **cutx0.wav … cutx21.wav** (22
numbered files from the generic name; first 0.0045 s, rest ~0.2 s). No single-output form
exists — per standing precedent (multi-output programs with no outfile argv), dropped.

## 17. partition — DROPPED (multi-output, no outfile argv)

`partition partition 1 sw2.wav party 3 30` — exit 0 → **party0/1/2.wav** (each 2.0000 s,
block-interleaved with silence). Same precedent, dropped.

## 18. distort shuffle — DROPPED (engine free-string gap, blur-shuffle precedent)

CLI verified working: `distort shuffle tone2.wav out ab-abab` → 3.9909 (≈ indur×imgcnt/dmncnt);
`ab-a` → 0.9980; `ab-ba -c50` → 1.8182 (trailing incomplete block dropped). Validation
verbatim: `Bad string for shuffle data: separator missing` (`abab`). The domain-image mapping
is a REQUIRED free-string positional parsed straight from argv (`cdp2k/tklib3.c:646
read_shuffle_data` via the DISTORT_SHUF case) — exactly blur shuffle's shape, which was
withdrawn at spot-check because the engine's `_check_type` accepts strings only for `.brk`
paths and `aux_file` params. Dropped with the same evidence; probe findings retained here for
the eventual unblocking (plain-string parameter support). Reachable today via execute().

## 19. splinter, mode 2 — CURATED (modes 1/3/4 via execute; mode 4 -d segfault)

`splinter splinter 2 tb2.wav out 0.42 4 16 8 10 10` — exit 0.

| args | outdur | model `target+(shr+ocnt+ecnt)(1/p1+1/p2)/2` |
| ---- | ------ | ------------------------------------------- |
| p 10/10 | 2.8220 | 2.82 |
| p 10/10 shr8 ocnt4 | 1.6220 | 1.62 |
| p 10/10 -e8 | 3.6220 | 3.62 |
| target .9 | 3.3007 | 3.30 |
| p 10/40 | 1.8844 | 1.92 (+1.9% — pcv curve) |
| -I (no source) | 2.4239 | train only |

- Mode 1 (lead-in): 1.8571 from tb2, 2.8571 from tb3 (train + indur − target). Mode 3: 3.8784;
  mode 4: 2.8267. **Mode 4 with `-d40`: SEGFAULT exit 139.**
- p2 range verbatim `(0.000000 to 50.000000)` (60 refused); target `(0.000000 to 2.000000)`
  (=indur). rand `-r` brk (0→0.8) differs from both `-r0.8`/`-r0.0001` → **capable**.
- **Deterministic randomisation:** `-r0.5` pairs 1.2 s apart byte-identical (no seed exists).
- **Flat-noise refusal (row impossible):** `ERROR: INVALID DATA / ERROR: Targeted-wavesets frq
  (c. 17454.55) >= goal frq (6000.00): Cannot shrink.` (fn1 and fn2; -f can't exceed nyquist/2)
  → duration_row null with this evidence.
- ct2: `No wavesets found after time 0.500000`; stereo must-be-mono.

## 20. crumble, mode 1 — CURATED (8-channel out; row null)

`crumble sound 1 tb2.wav out 0.3 0.5 0.7 1 0.1 0.3 0.3 0.3 1 2 5` — exit 0, **8 channels**.

| variant | outdur |
| ------- | ------ |
| base (seed 5) | 1.6879 |
| seed 5 rerun (1.2 s later) | 1.6879 byte-identical |
| seed 9 | 1.6728 |
| tb3 (3 s) | 2.6668 |
| fn2 | 1.6879 |
| zero-scatter, size .1, stt .3 | 1.7000 |
| zero-scatter, stt .6 | 1.7000 (stt-independent) |
| size .05 | 1.7000 |
| size .2 | 1.5000 |
| ostrch 2 | 3.0876 |
| -t100 | 1.5100 |

- **No closed duration form** (size/seed-dependent tail loss, −8…−25%; ostrch extends) →
  duration_row null; entry pins `static` with the envelope documented.
- **Seed REQUIRED 1–256** (0 refused `(1.000000 to 256.000000)`) and always live (zero-scatter
  seeds 5/9 still differ). Reproducible (same-seed byte-identical).
- Constraint verbatim: `Sum of durations of splitting processes extends beyond end of input
  file.` orient `(1.000000 to 8.000000)`.
- **Brk proofs:** size brk (.05→.3) 1.1965, differs from both scalars → **capable**; pscat brk
  (0→6) differs from both → **capable**. Mode 2 = 16 channels (verified, extra dur3).

## 21. cascade, mode 3 — CURATED (mono→stereo; ALL brks silently inert)

`cascade cascade 3 tb2.wav out 0.25 4 0` — exit 0, 2 channels.

| clipsize | echos | outdur | model `indur + clipsize*echos` |
| -------- | ----- | ------ | ------------------------------ |
| 0.25 | 4 | 2.9749 | 3.0 |
| 0.25 | 8 | 3.9549 | 3.955 |
| 0.25 | 2 | 2.4850 | 2.5 |
| 0.25 | 10 | 4.4449 | 4.5 |
| 0.5 | 4 | 3.9749 | 4.0 |
| tb3 0.25 | 4 | 3.9749 | 4.0 |
| fn2 0.25 | 4 | 2.9749 | 3.0 (row) |

- **BRK FILES SILENTLY IGNORED (first-class):** clipsize brk (.1→.5) **byte-identical** to
  scalar 0.1; echos brk (2→10) **byte-identical** to scalar 2; rand brk (0→1, with -s5)
  **byte-identical to the flag-less base**. Banner's "Time-variable" claims are dead on this
  build → every param capable=false.
- **Seed semantics:** `-r0.5 -s5` pairs byte-identical; `-s5` vs `-s9` differ; **unseeded
  `-r0.5` pairs also byte-identical** (never clock-seeded). Seed range verbatim `(0.000000 to
  64.000000)`; clipsize `(0.005000 to 60.000000)`; echos `(1.000000 to 64.000000)`.
- clipmax 0.5: duration seed-dependent (3.0712 seed 5 / 3.7227 seed 9) — model suspended.
  Shred `-N4 -C2` works (render change, same duration). ct2 ACCEPTED. Mode-3 stereo input
  refused `File st2.wav is not of correct type for Mode 3`. Mode 1 on mono: 1 ch out, same
  duration (2.9749). Modes 6–10 take a cuts textfile (execute()).

## 22. fracture, mode 1 — CURATED (seed-hunt: banner's -h is really -S)

`fracture fracture 1 tb2.wav out etab.txt 2 4 0.25 0.8 0` — exit 0, 2 channels.

- **Static, sample-exact** with rands off: 2.0000 (tb2, fn2, **ct2 accepted**), 3.0000 (tb3),
  2.0000 at chns 8. With `-r0.5 -p0.5 -d0.5`: 1.7583 (seed-dependent 1.76–1.94; last fragment
  lands early).
- **SEED-HUNT RESULT (banner bugs, source-verified):** usage advertises `[-hseed]` and
  `[-imax]` but `-h`/`-i` are refused verbatim (`Unknown variant flag -h` / `-i`). Source
  `fracture.c` set_vflgs `"rpdvestSmM"` → seed = **-S** (0–32767, default 0; `srand(seed)` if
  >0 feeds the drand48 shim), max = **-M**, min = -m. Empirical: `-S5` pairs byte-identical;
  `-S5` vs `-S9` differ; `-S0` == flag-less byte-identical. **Unseeded runs deterministic even
  with rands on** (no clock path).
- pulse brk (0.1→1.0) differs from both endpoint scalars → **capable**. Ranges verbatim: chns
  `(2.000000 to 16.000000)`; strms `(4.000000 to 512.000000)`; pulse `(0.050000 to 8.000000)`;
  edpth `(0.000000 to 8.000000)`. etab validation verbatim: `Invalid number of entries (13) on
  line 1: should be 15 (1 time plus 7-etime-level pairs`.
- `-m0.05 -M0.15` at edpth 0.8 byte-identical to base (min/max INACTIVE below depth 1,
  banner-consistent). Mode 2 (stereo surround projection, 4 extra positionals) left to
  execute(). Stereo input must-be-mono verbatim.

---

## Verification

- Loader: `KnowledgeIndex.load()` → 377 entries, zero malformed warnings; all 22 tranche-16
  triples resolve exactly; overload 1/2 resolve to distinct entries.
- `process_impl` spot-checks (flat-noise input, CDP_PATH=/tmp/CDP8/NewRelease), all status ok
  with durations matching the pinned probes: telescope -a 0.5158; repeat2 2.0038; distortt
  4.0000; distmark(-t, aux marks) 1.9420; cascade 3 2.9749 (stereo); fracture 1 (aux etab)
  2.0000; overload 1 2.0; pulsed 1 (aux env+transp, ternary model) 1.8002; repeat2 with a
  relative-time multiplier breakpoint ok (2.0112).

## Final row confirmations (flat-noise fixture, exact pinned params)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| distort replim, mult 3 | 6.0 | 5.9971 | 0.05% |
| distort reverse, cyclecnt 4 | 2.0 | 2.0000 | 0.00% |
| distort envel 2, cyclecnt 20 | 2.0 | 2.0000 | 0.00% |
| distort harmonic, harm16.txt | 2.0 | 2.0000 | 0.00% |
| distort pitch, octvary 0.1 | 2.0 | 1.9994/1.9982/1.9987 | ≤0.1% (stochastic) |
| distort telescope, cyclecnt 4 + average | 0.5 | 0.5158 | 3.2% |
| distort filter 1, freq 440 | 2.0 | 1.9999 | 0.005% |
| distort overload 1, 0.3/0.5 | 2.0 | 2.0000 | 0.00% |
| distort overload 2, 0.3/0.5/880 | 2.0 | 2.0000 | 0.00% |
| distort pulsed 1, dur 2/frq 5 (aux) | 1.8 | 1.8002 | 0.01% |
| distort repeat2, mult 3 | 2.0 | 2.0038 | 0.19% |
| distrep 1, mult 3/cyclecnt 1 | 6.0 | 5.9998 | 0.003% |
| distshift 1, 1/1 | 2.0 | 1.9999 | 0.005% |
| distortt repeat, 1/3/100/4 | 4.0 | 4.0000 | 0.00% |
| distmark 1, marks16/40/-t (aux) | 2.0 | 1.9420 | 2.9% |
| distmore double, mult 1 | 2.0 | 1.9999 | 0.005% |
| distmore segszig 2, repets 4 | 16.0 | 15.8949 | 0.66% |
| distmore segsbkwd 3, marks16 (aux) | 2.0 | 2.0000 | 0.00% |
| cascade 3, 0.25/4/0 | 3.0 | 2.9749 | 0.84% |
| fracture 1, etab16/2/4/0.25/0.8/0 (aux) | 2.0 | 2.0000 | 0.00% |

splinter 2 and crumble 1 ship with null rows (flat-noise refusal / no closed form — evidence
in §19–20). 22 curated; dropped: distort shuffle, distcut, partition, distrep 2, distshift 2
(+ distmore bright deferred without defect).
