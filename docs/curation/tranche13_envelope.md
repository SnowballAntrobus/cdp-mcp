# Tranche 13 — envelope family curation probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease`, built from ComposersDesktop/CDP8 source
  (banner "CDP Release 7.1 2016") — **Linux aarch64 sandbox** this tranche, and
  that mattered (see the `-fsigned-char` substrate finding below). Re-verified on
  macOS r8 by the CDP-gated suite after integration.
- **Fixtures:** `/tmp/probe` (n1/n2/n3 enveloped noise, tone1/tone2, st2 stereo,
  syl2 = 4 noise-burst syllable train with TRUE digital-zero gaps);
  `/tmp/probe13b` (fresh this tranche): `real4.wav` = 2.5 s, four decaying bursts
  over a **-54 dBFS noise floor, zero exact-zero samples** (the "real recording"
  proxy for the gate→retime chain), `levels.wav` = 0.25/0.005/0.02-amplitude tone
  segments (threshold-semantics probe), `flat1/flat2.wav` = the duration-fixture
  clone (`_write_noise` seed 0, std 0.2), `lead5ms/lead50ms.wav` (topantail2 bug
  matrix), `sylq.wav` (syl2 × 0.35 — headroom for envel attack); `/tmp/probe13b/d`
  for the data-format probes.
- **Methodology:** tranche-2 verbatim. Breakpoint proof = brk render differs from
  BOTH scalar-endpoint renders (sha256 of decoded float64 samples). Determinism
  pairs launched > 1.1 s apart. Duration models checked at ≥ 2 input durations.
  Refusals quoted verbatim (stdout, exit 255 unless noted).

---

## 0. SUBSTRATE FINDING — aarch64 unsigned `char` kills ALL CDP text-file inputs

First-class, discovered when every text-input conversion refused
`ERROR: <name> is not a valid CDP file` — on hand-written 3-line breakpoint
files, on `.txt`, `.brk`, and extensionless names alike, while `submix getlevel`
refused its own mixfile the same way.

- **Mechanism (source-diagnosed):** `dev/cdparse/cdparse.c` /
  `cdparse_other.c`, `initial_parse_textfile()`:
  `char c; while((c = (char)fgetc(fp)) != EOF) { if(!isalnum(c) && !ispunct(c) && !isspace(c)) → "not a valid CDP file" }`.
  On platforms where `char` is unsigned (Linux aarch64 default), `(char)EOF` is
  255, never equal to `EOF`, so the loop consumes the real bytes and then feeds
  255 to the classifiers → every textfile is "invalid". x86_64 Linux and macOS
  (both Intel and Apple Silicon) default to signed `char`, which is why eleven
  tranches on x86_64 never saw it.
- **Fix applied to the substrate:** rebuild with `-fsigned-char`. Note CDP8's
  per-directory `CMakeLists.txt` files each hard-clobber `CMAKE_C_FLAGS`, so a
  top-level `-DCMAKE_C_FLAGS=-fsigned-char` does NOT propagate — every
  `set(CMAKE_C_FLAGS "` occurrence was sed-patched to prepend the flag, then
  full rebuild (211 binaries). After the rebuild all text parsing works
  (`envel gaintodb hand.txt` → correct dB output).
- **Cross-check that the fix changed nothing else:** `gate gate 1` renders
  byte-identical decoded shas before/after the rebuild (no text path involved).
- Recorded in the two curated entries that touch CDP text parsing
  (envtobrk known_issues carries the pin for the family).

---

## 1. gate (program) — modes 1 & 2, and the gate → retime chain (HEADLINE)

Working: `gate gate 1 real4.wav out.wav -40` — exit 0; `gate gate 2 ...` likewise.
Modes 1-2 only (`Program mode value [3] is out of range [1 - 2].`).

**Threshold semantics pinned (absolute, per-sample-run):**

- gatelevel range verbatim: `ERROR: Parameter[1] Value (40.000000) out of range (-96.000000 to 0.000000)`
  (also refused: 0.5, -97).
- ABSOLUTE dBFS, not peak-relative: `levels.wav` (peak 0.25) at -40 dB (= 0.01
  linear): the 0.005-amplitude segment zeroed (99.7% zeros), the 0.02 segment
  fully kept — peak-relative would have kept 0.005 (0.02 rel) too.
- Per-sample contiguous runs, not envelope windows (source `dev/standalone/gate.c`,
  `gate()` line 1098ff): a below-threshold run becomes a cut region only if
  `len > splicelen*2` interior / `len > splicelen` at file edges, with
  `splicelen = 1 ms` hardcoded (line 1107); 1 ms down/up splices at each region
  boundary. Consequence verified: a full-scale sine refuses
  `ERROR: No signal is gateable` (its near-zero crossings are ~µs long) instead
  of distorting.
- `ERROR: Entire signal would be gated.` at gatelevel 0 on an in-range file.
- Mode 1 zeroes the regions **in place**: 110250 frames in → 110250 out
  (sample-exact static), 5 zero-runs totalling 43.8% of real4 at -40.
- Mode 2 EXCISES them: real4 2.5 → 1.4062 s; syl2 2.0 → **1.1924 s ≈ the sum of
  the four 0.30 s bursts** — duration = sum of kept regions (content-dependent,
  row null).
- gatelevel brk: `ERROR: Cannot read parameter 1 [b_gl.brk]: brkpnt_files not permitted.`
- Stereo refused: `ERROR: File stmix.wav is not of correct type (must be mono)`
  (the multichannel scan code in source sits behind the refusal, dead, next to a
  `**** THIS NEEDS TO BE FIXED ****` comment).
- Determinism: pairs > 1.1 s apart identical (both modes).
- Duration rows: **null** — the shared flat-noise fixture refuses
  `No signal is gateable` (nothing under any usable threshold for ≥ 2 ms).

**THE CHAIN (Phase 6 wants this):** retime detects events by literal zeros
(tranche 11b). On `real4.wav` (noise floor, no exact zeros):

| step | result |
| ---- | ------ |
| `retime retime 4 real4.wav … 120 50 1` (ungated) | `WARNING: WARNING: only 1 event found: Change inter-event silence ??` → 2.5 s near-passthrough |
| `gate gate 1 real4.wav g1b.wav -40` then `retime retime 4 g1b.wav … 120 50 1` | **`INFO: 4 events found`** → 1.9506 s correctly retimed to the 120 MM grid |
| `envel warp 8 real4.wav w8.wav 20 0.05 0` then retime 4 | **`INFO: 4 events found`** — the envelope-window gate is a second, stereo-capable enabler |

`gate gate 1` is the per-sample/dB tool (mono); `envel warp 8` the
window-resolution/linear tool (stereo, breakpointable gate). Both curated.

## 2. housekeep gate — DROPPED (multi-output, outfile argv ignored)

`housekeep gate <in> <out>` first refuses `Cannot read mode of program.` — the
banner omits the required mode digit. With it, `housekeep gate 1 syl2.wav
hgout.wav` exits 0 having written **`syl0.wav`, `syl1.wav`, …** — numbered
segment files named from the INPUT basename (trailing digit stripped), in the
input's own directory; the declared outfile is NEVER created. It stops on
collision: `WARNING: Soundfile syl2.wav already exists.` (the input itself!).
Source: `dev/houskeep/clean.c` HOUSE_CUTGATE — `setup_naming`/
`create_outfile_name` loop over `ccnt` cut segments. Cuts happen at zero-runs
(≥ zerocnt consecutive zero samples). Textbook multi-output drop per the
standing decision — and doubly hazardous (input-collision naming). The engine's
declared-output verification can never pass. Use `gate gate 2` (excise) or
sfedit for engine-visible alternatives.

## 3. envel warp — 15-mode table; submodes 8 (GATE) and 11 (CORRUGATE) curated

Mode table (banner): 1 NORMALISE, 2 REVERSE, 3 EXAGGERATE, 4 ATTENUATE, 5 LIFT,
6 TIMESTRETCH, 7 FLATTEN, **8 GATE**, 9 INVERT, 10 LIMIT, **11 CORRUGATE**,
12 EXPAND, 13 TRIGGER (extra rampfile argv), 14 CEILING, 15 DUCKED. Shared shape:
`envel warp N snd out wsize various_params`. Modes 3/6 probed working (exit 0;
mode 6 "timestretch" leaves the AUDIO duration unchanged — it stretches the
envelope only). 13 modes recorded, deferred with the table (not force-curated).

**warp 8 (GATE):**
- `envel warp 8 real4.wav w8.wav 20 0.05 0` → 56494 literal zeros; retime finds
  4 events (chain above).
- Threshold ABSOLUTE 0-1: on levels.wav (peak 0.25) gate 0.05 zeroed BOTH the
  0.005 and the 0.02 segments (peak-relative 0.02/0.25 = 0.08 > 0.05 would have
  survived); kept segment passes through bit-exact (peak 0.2500).
- OVER-FULL-SCALE RENORMALIZATION: real4 peaks at 1.128 (float); every kept
  sample came back × 0.887 = 1/1.128, output peak exactly 1.0 (1 sample). In-range
  sources untouched.
- gate brk → exit 0 and differs from both endpoint renders → **capable**
  (banner: "Gate may vary over time"). wsize brk:
  `ERROR: Cannot read parameter 1 [bw.brk]: brkpnt_files not permitted.`;
  smoothing brk: `... parameter 4 ...`.
- Ranges verbatim: wsize `(5.000000 to 2500.000000)` (= indur ms, input-dep);
  gate `(0.000000 to 1.000000)`; smoothing `(0.000000 to 32767.000000)`.
- No-gateable-content case: flat noise passes through (2.0 s, no refusal —
  contrast the gate program).
- Duration static (2.5→2.5, 1.0→1.0); deterministic; stereo accepted.

**warp 11 (CORRUGATE):**
- `envel warp 11 n2.wav w11.wav 20 2 6` → 7692 literal zeros punched at envelope
  troughs (retime-compatible by construction).
- peak_separation range verbatim: `Parameter[3] Value (1.000000) out of range (2.000000 to 32767.000000)`.
  Banner's `trofdel < PEAK_SEPARATION` NOT enforced (trofdel 8 / peaksep 6
  accepted silently).
- trofdel brk and peak_separation brk each differ from both endpoints →
  **both capable** (banner-confirmed). wsize refuses (parameter 1).
- Static (2.0→2.0, 1.0→1.0); deterministic; stereo accepted.

## 4. envel swell

`envel swell n2.wav sw.wav 1.0 1` — exit 0 (NO mode digit). Static, exact at 1 s
and 2 s. Edge/mid RMS ratio vs source: 0.037 / 0.918 / 0.029 (arch verified,
unity only at peaktime). Ranges verbatim: peaktime
`(0.005000 to 1.995000)` (input-dep), peaktype
`Parameter[2] Value (5.000000) out of range (0.000000 to 1.000000)` — the
dovetail-family 2/3 shapes do NOT exist here. Both brks refused (parameters 1
and 3). Deterministic; stereo accepted.

## 5. envel attack — mode 3 curated (exact time), all 4 modes probed

- HEADROOM GATE (content-dependent, verbatim):
  `ERROR: CANNOT ACHIEVE TASK: / ERROR: The attack may distort with this gain level.`
  — syl2 (peak 0.917) refused gain 1.5 in modes 1 & 3; the same material × 0.35
  accepted it. **MODE 4 SKIPS THE CHECK:** gain 2.0 on the peak-0.917 file
  rendered a 1.833-peak float without complaint (inconsistency recorded).
- Mode 3 boost locality verified: gain 1.5 at time 0.55 lifts only ~0.55-0.58 s
  (10 ms windows); mode 1 boost at its gate-crossing (0.05-0.08 s); mode 4 at
  the file max.
- Ranges verbatim: time `(0.000000 to 1.995000)` (input-dep); gain
  `(1.000000 to 32767.000000)` (boost only!); onset `(5.000000 to 32767.000000)`;
  decay `(5.000000 to 1995.000000)` (input-dep); envtype -t
  `Parameter[5] ... (0.000000 to 1.000000)`.
- All 4 params + -t refuse brks (parameters 1-5). Static, exact at both indurs.
  Deterministic; stereo accepted. Modes 1/2/4 dropped as siblings (exemplar 3).

## 6. envel curtail — mode 2 curated; mode 5 BROKEN; 4/6 = 1/3 + envtype 3

- Duration = fade end, TRUNCATING: mode 1 (start+end 0.8/1.4) → 1.4000; mode 2
  (start+dur 1.0/0.5 → 1.5000 on 2 s; 0.3/0.4 → 0.7000 on 1 s); mode 3
  (start only) → full 2.0; overshoot clips: mode 2 at 1.5+1.5 on 2 s → 2.0000.
  Model `(fadestart + fadedur) if (fadestart + fadedur) < indur else indur`.
- **BINARY BUG:** `envel curtail 5 n2.wav out 1.0 0.5` dies EVERY time:
  `ERROR: MEMORY ERROR / ERROR: INSUFFICIENT MEMORY to reallocate level array.`
  Modes 4 and 6 work.
- Mode equivalences byte-verified: curtail 1 + envtype 3 == curtail 4; curtail 3
  + envtype 3 == curtail 6 (so the doubly-exponential trio needs no entries, and
  broken mode 5 is reproducible as mode 2 + envtype 3).
- envtype accepts undocumented 2 (steep) and 3 (dbl-exp; distinct outputs);
  envtype 5 → `ERROR: INTERNAL ERROR: (Bug?) / ERROR: Unknown case in create_envelope()`.
- fadestart out of bounds → `ERROR: Start of fade time : out of range.` (runtime,
  no Parameter[N]). fadestart brk: `Cannot read parameter 1`; fadedur brk:
  `Cannot read parameter 2`. Deterministic; stereo accepted.

## 7. envel scaled (aux brkfile between input and output — pre_output)

`envel scaled n2.wav env4.txt out.wav` — exit 0. Envelope TIME-SCALED to the
input: shape peaking at 1 on a 0-4 axis peaks at 0.275 s on a 1 s file and
0.525 s on a 2 s file (both ≈ dur/4). Static, exact at both indurs. Values > 1
amplify (peak gain 1.23 from a 2.0-level shape, no clamp). 1-pair file refused
`ERROR: Not enough data in brkpnt file env1.txt`. Deterministic; stereo accepted.

## 8. tremolo / tremenv / envel tremolo — overlap resolved by byte-proof

- **`envel tremolo 1 f d g` == `tremolo tremolo 1 f d g 1` BYTE-IDENTICAL**
  (decoded shas equal) → envel tremolo dropped, tremolo curated as the superset
  (fineness = squeeze).
- `tremolo tremolo 2` (log frq interp) == mode 1 at SCALAR frq (byte-identical);
  differs with a frq BREAKPOINT (sha differs) → dropped with the note "use via
  execute() for pitch-like sweeps".
- tremolo brk proofs: frq (2→16), depth (0.2→1.0), gain (0.2→1.0) each differ
  from both endpoints → **all three capable**; fineness brk refused
  (`Cannot read parameter 4`). Ranges verbatim: frq `(0.000000 to 500.000000)`,
  depth/gain `(0.000000 to 1.000000)`, fineness `(1.000000 to 100.000000)`
  (banner's ">= 1" unbounded claim wrong). Fineness narrows pulses: 25 ms RMS
  minima 0.029 (f=1) → 0.000 (f=4).
- **tremenv**: distinct render from tremolo at identical settings (sha differs);
  NO time-variable params — ALL FOUR refuse brks (parameters 1-4 verbatim);
  winsize `(1.000000 to 40.000000)` (0.5 and 50 both refused); fineness
  `(1.000000 to 100.000000)`. No gain slot.
- Both static & exact at 2 indurs, deterministic (probed at fineness 4), stereo
  accepted.

## 9. spike

`spike spike n2.wav out.wav 1.0 4 4` — exit 0, static & exact (both indurs);
envelope profile verified (rise to the 1.0 s peak, collapse after).

- **Banner lies about -m:** `ERROR: Unknown variant flag -m` (maxup does not
  exist). -d (maxdown) works, range `Parameter[5] ... (0.000000 to 1.000000)`.
- **-n CORE-DUMPS at teardown** (`timeout: the monitored command dumped core`)
  AFTER writing a full-size output — broken exit contract (specfnu-21 family);
  not exposed.
- Multi-peak: the peaks slot accepts a DATAFILE of trof-peak-trof triplets
  (6-time file → 2 spikes verified; plain 3-time file → 1 triplet = ONE spike);
  extra inline argv times refused. Pinned scalar single-peak; file form via
  execute().
- upslope brk and downslope brk each differ from both endpoints → **capable**.
  upslope range verbatim `Parameter[2] Value (200.000000) out of range (1.000000 to 100.000000)`.
  Peak beyond EOF: `ERROR: MEMORY ERROR / ERROR: Invalid peak time (2.500000) at or beyond sound end (2.000000), 2.5`
  (spurious MEMORY banner).
- Deterministic; stereo accepted.

## 10. topantail2 — with a pinned DOUBLING BUG

`topantail2 topantail syl2.wav out.wav 0.1 0.1` → 1.7131 s (trims quiet edges).
Ranges verbatim: startgate/endgate `(0.000000 to 1.000000)` (Parameters 1/2),
splicelen -s `(2.000000 to 200.000000)` (P3), backtrack -b
`(0.000000 to 1000.000000)` (P4). All four brks refused (parameters 1-4).

**DOUBLING BUG (trigger pinned):** when the first above-gate sample lies within
one splicelen of the file start (0 < startsamp < splicesamps):

| fixture | gates 0.1 | outcome |
| ------- | --------- | ------- |
| lead50ms (50 ms silence, > splicelen) | 1.9499 s | correct trim (2.0 - 0.05) |
| lead5ms (5 ms silence, < default 15 ms splice) | **3.99 s** | file DOUBLED (garbage) |
| flat2 @ 0.01 (startsamp = 0) | 2.0000 s | exact passthrough |
| flat2 @ 0.1 (startsamp small ≠ 0) | 3.9999 s | DOUBLED |

Source: `top_and_tail()` (dev/standalone/topantail2.c) clamps
`startsplice = startsamp - splicesamps` to 0 while startsamp stays > 0; the
subsequent seek/write pass emits the content twice. Whole-file-quiet refusal
exists in source (`At this gate level, entire file will be removed.`).
Deterministic; stereo accepted; static row pinned at gates 0.01 (2.0000 exact).

## 11. envnu expdecay

`envnu expdecay n2.wav out 0.5 2.0` — exit 0. TRUNCATES at endtime:
endtime 1.0 on 2 s → 1.0000; 0.8 on 1 s → 0.8000; endtime ≥ indur (0.3/5.0 on
1 s; 0.5/90000 on 2 s accepted silently) → full duration, tail RMS 0.00006.
Model `endtime if endtime < indur else indur`, exact. Ranges: starttime
`(0.000000 to 2.000000)` (input-dep); endtime ≤ starttime →
`ERROR: Endtime of decay must be greater than starttime. 1.500000  1.000000`.
Both brks refused (parameters 1-2). Deterministic; stereo accepted.

## 12. envnu peakchop — mode 1 (audio) + mode 2 (.txt envelope) curated

**Mode 1** `envnu peakchop 1 syl2.wav out 50 20 10 120 1` — exit 0, 1.54 s from
the 4-peak source at 120 MM; 3.04 s at 60 MM; 5.04 s from 2 s flat-ish bed
(more envelope peaks) → duration = f(peak count, tempo), row null.
- Brk probes: wsize refused (P1); pkwidth/risetime/tempo/gain accepted; -g gate
  refused (P6); -q skew refused (P7); -s scatter/-r repeat/-m miss accepted —
  exactly the banner's "All parameters may vary in time, EXCEPT wsize, gate and
  skew". **All seven accepted ones then PROVED capable** (each brk render
  differs from both scalar endpoints: tempo 40→240, pkwidth 10→60, risetime
  5→30, gain 0.3→1.0, scatter 0→1, repeat 0→3, miss 0→2).
- "Times in breakpoint files are times in the output" (banner verbatim) —
  OUTPUT-time axis, recorded in the entry.
- **scatter is DETERMINISTIC:** two `-s0.5` runs 1.3 s apart byte-identical; no
  seed slot exists (unseeded fixed-sequence generator — the osbind drand48-shim
  family from tranche 2).
- Ranges verbatim: wsize `(1.000000 to 1000.000000)` (banner "1-64" advisory);
  tempo `(20.000000 to 3000.000000)`; gain P5, gate P6, skew P7, scatter P8,
  norm P9 all `(0.000000 to 1.000000)`; repeat P10 `(0.000000 to 256.000000)`;
  miss P11 `(0.000000 to 64.000000)`. pkwidth 600 ACCEPTED in mode 1 (banner
  constraint unenforced there).
- Stereo accepted — but the stereo envelope changes the peak count (same
  content as dual-channel → 3.54 s vs 1.54 s mono).

**Mode 2** (`envnu peakchop 2 in out.txt 50 20 10`) writes the peak-isolating
envelope as TEXT: 18 lines of `time\tlevel` (0/1 alternation) on syl2 — a valid
gain brkfile. `.wav` output name refused
`ERROR: Cannot open a textfile (pc2.wav) with a reserved extension.` — .txt data
output. pkwidth IS enforced here: 600 →
`ERROR: New peakwidth too wide for the input data.` Deterministic byte-identical.

## 13. envelope DATA formats — pins and the conversion layer

**Format pins (all binary-verified):**

| kind | container | key numbers |
| ---- | --------- | ----------- |
| `.evl` from `envel create 1` (wsize 20) | RIFF/WAVE, FLOAT, 1 ch | srate **50 = 1000/wsize**, 101 frames for a 2.0 s envelope |
| `.evl` from `envel cyclic 3` (wsize 10) | same | srate 100; values span trough..1.0; **duration rounds UP to whole cells** (2.0 requested / celldur 0.25 → 2.25 s, 225 frames) |
| `.evl` from `envel brktoenv` (wsize 20) | same | 102 frames from a 2.0 s brk list |
| text brk from `envtobrk` | `time\tlevel` lines | one per window; datareduce -d thins |
| text from `envtodb` | `time\tdB` lines | silence floors at `-96.000000` |

- argv orders pinned: `envel create 1 OUTFILE createfile wsize` (output FIRST —
  the createfile is a plain positional aux after the output);
  `envel cyclic 3 OUTFILE wsize totaldur celldur phase trough expo`;
  `envel envtobrk IN.evl OUT [-d]` and `envel brktoenv IN.txt OUT.evl wsize`
  (input first → pre_output aux).
- create rules verbatim: `ERROR: timegap 0.005000 - 0.000000 is too small.`
  (< 0.01 s steps); `ERROR: Level value 1.500000 out of range` (plain > 1);
  `-6dB`/`0dB` forms accepted; wsize `(5.000000 to 10000.000000)`.
- cyclic verbatim: wsize P1 `(5.000000 to 10000.000000)`; celldur P3
  `(0.010500 to 32767.000000)` (floor tied to wsize); phase P4 `(0 to 1)`,
  brk refused; expo P6 `(0.020000 to 50.000000)`. celldur brk and trough brk
  each differ from both endpoints → **capable** (compiled against the set_by
  totaldur axis in the engine).
- envtobrk datareduce `(0.000000 to 1.000000)`; brktoenv wsize
  `(5.000000 to 2020.000000)` (tracks the brk list's span); brktoenv accepts
  levels > 1 (1.8 converted silently).
- Extension typing: the .evl input renamed `.dat` refuses
  `ERROR: out1.dat is not a valid CDP file` — extension-driven detection.
- **Consumers verified:** `envel impose 2 tone2.wav out1.evl imp2.wav` → 2.0 s;
  `envel impose 3 tone2.wav hand2.txt imp3.wav` → 2.0 s.
- Determinism: .evl outputs differ by exactly ONE byte across runs (offset 113,
  inside the RIFF `LIST` date chunk at offset 38; the FLOAT data chunk is
  array-equal) — envel extract precedent. Text outputs byte-identical.

**Curated:** create 1, cyclic 3, envtobrk, brktoenv (+ peakchop 2 above).
**Dropped (probed working, evidence in findings):** create 2 (text twin),
cyclic 1/2/4 (siblings; 4 = userenv aux, verified exit 0), envtodb / dbtogain /
gaintodb / dbtoenv (dB text kind has no curated consumer; round-trip
dbtogain(envtodb(x)) == envtobrk(x) verified), replot (brk→brk through the
15-mode warp table; exemplar `replot 3 hand2.txt rp.txt 20 2` exit 0), reshape
(evl→evl same table; exemplar `reshape 3 out1.evl rs1.evl 2` exit 0, 2474 bytes).

## 14. Other drops (full evidence)

- **envel timegrid** `envel timegrid n2.wav tg.wav 3 0.1 5` — exit 0 but writes
  `tg_0.wav tg_1.wav tg_2.wav` (gridcnt files); the declared outfile is never
  created → multi-output drop.
- **envcut** `envcut envcut 1 n2.wav eco.wav 0.01 0.5 1` — exit 0, writes
  **199 files** `eco0.wav … eco198.wav` (`INFO: Writing File N` spam), declared
  outfile never created → multi-output drop. Bonus divergence: attack is
  seconds, not the banner's mS (`Parameter[1] Value (10.000000) out of range (0.001000 to 2.000000)`).
- **envel pluck** — mono only (`Application doesn't work with this type of
  infile.` on st2); works on tone2 (`pluck tone2 out 44100 100` → 1.07 s from
  2.0 s = indur − startsamp/srate + attack), but the duration model needs
  srate-domain sample arithmetic the expression vocabulary cannot express, and
  the startsamp-at-zero-crossing precondition is unverifiable engine-side → drop.
- **envel tremolo 1/2** — byte-identical to `tremolo tremolo` at fineness 1 (§8).
- **tremolo tremolo 2** — scalar-identical to mode 1; distinct only under frq brks (§8).
- **envel attack 1/2/4, curtail 1/3/4/5/6** — sibling/equivalence/broken analysis in §§5-6.
- **housekeep gate** — §2.

## 15. Duration-model verification matrix (both indurs, flat fixtures)

| entry | 1 s pred/actual | 2 s pred/actual |
| ----- | --------------- | --------------- |
| envel swell (1.0/0.5 peaktime) | 1.0 / 1.0000 | 2.0 / 2.0000 |
| envel attack 3 | 1.0 / 1.0000 | 2.0 / 2.0000 |
| tremolo 1 | 1.0 / 1.0000 | 2.0 / 2.0000 |
| tremenv | 1.0 / 1.0000 | 2.0 / 2.0000 |
| spike | 1.0 / 1.0000 | 2.0 / 2.0000 |
| envel warp 8 | 1.0 / 1.0000 | 2.0 / 2.0000 |
| envel warp 11 | 1.0 / 1.0000 | 2.0 / 2.0000 |
| envnu expdecay (0.3/0.8; 0.5/1.0) | 0.8 / 0.8000 | 1.0 / 1.0000 |
| envel curtail 2 (0.3+0.4; 1.0+0.5) | 0.7 / 0.7000 | 1.5 / 1.5000 |
| envel scaled | 1.0 / 1.0000 (n1) | 2.0 / 2.0000 |
| topantail2 (0.01/0.01) | — | 2.0 / 2.0000 |
| gate 1 (real4/levels) | 1.5 / 1.5000 (levels) | 2.5 / 2.5000 (real4, frames exact) |

Determinism sweep (12 programs, pairs > 1.1 s apart, decoded float64 shas):
swell, curtail 2, attack 3, expdecay, topantail2, tremolo (f=4), tremenv (f=4),
warp 8, spike, peakchop 1, scaled, peakchop 1 -s0.5 — **all identical**.

19 entries shipped; 14 drop groups recorded (see findings JSON).
