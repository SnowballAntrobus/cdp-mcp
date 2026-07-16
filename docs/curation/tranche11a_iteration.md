# Tranche 11a — iteration/sequence family (Phase 6 gesture-construction primitives): probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build; `extend` and
  `texture` banner "CDP Release 7.1 2016"; `iterline`, `iterlinef`, `shrink` print no
  release banner — CDP8-new), Linux x86_64 sandbox. To be re-verified on macOS r8 by the
  CDP-gated suite after integration.
- **Inputs:** fresh fixtures in `/tmp/probe11a` — short distinctive one-shots as the
  task brief requires for iteration ops: `ping3` (0.3 s, 660 Hz sine, 2 ms attack,
  exp(−14t) decay, peak 0.771), `ping6` (0.6 s twin), `tock4` (0.4 s, 220 Hz — a second
  identifiable voice for sequence2), `nburst35` (0.35 s decaying noise, marker file),
  `ping3st`/`tock4st` (stereo variants), `ping3_22k` (22.05 kHz), and `set01..set25`
  (0.3 s pings at semitone-spaced frequencies −12..+12 st around 440 Hz — the iterlinef
  set; file 13 = 440 Hz reference). `syl2.wav` from `/tmp/probe` for shrink modes 5/6.
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. Breakpoint proof =
  brk render differs from BOTH scalar-endpoint renders at a fixed seed; determinism
  pairs launched > 1.2 s apart; shas over decoded float64 samples; fresh output names
  per run; duration models verified at ≥ 2 input durations.
- **Priors:** SoundThread has NO coverage of any target (process_help.json: no
  iterate/iterline/sequence/shrink/texture keys). afta8 covers all six (ranges quoted
  below where they diverge); afta8 flags shrink 5/6 "[Doesn't work - multiple outputs]".
  Source: `/tmp/CDP8/dev/extend/{ap_extend,iterate,extprepro}.c`,
  `/tmp/CDP8/dev/new/{iterline,iterlinef,shrink}.c`, `cdp2k/{tklib1,special}.c`.

Refusal errors quoted verbatim (stdout, exit 255 unless noted).

---

## 1. extend sequence2 (TRANCHE PRIORITY — Phase 6 timeline() empirics)

Working argv: `extend sequence2 ping3.wav tock4.wav out.wav seq1.txt 1.0 [-ssplice]` —
exit 0. No mode digit. seq1.txt:

```
; two-voice test sequence
76 57
1  0.0  76  1.0  0.3
2  0.5  57  1.0  0.4
1  1.0  76  1.0  0.3
```

### 1.1 Sequence-file syntax (source `read_sequence2`, ap_extend.c:1570 + probes)

- **Stream parse:** values are read as a FLOAT STREAM — the whole file on ONE line
  rendered **byte-identical** (sha `ffc68d8b5f0bbffe`) to the line-per-event form. Line
  structure is purely cosmetic; only value ORDER matters.
- **Comments:** lines starting `;` skipped (leading whitespace allowed) — verified
  head and mid-file.
- **First infilecnt values** = notional MIDI pitch per input (order = argv order),
  range 0–127.
- **Then 5-value groups:** `sound# time midipitch loudness duration`.
- **Refusals (all verbatim, INVALID DATA exit 255):**
  - decreasing time: `ERROR: Times do not increase at (0.200000) AT LINE 3: OR data not
    grouped as time-transpos-level` (EQUAL times are legal — chords).
  - fractional or out-of-range sound#: `ERROR: Instrument number (1st item) at line 2
    does  not correspond to any input file` (double space verbatim).
  - negative loudness: `ERROR: Level (-0.500000) is less than zero at line 2: OR data
    not grouped as sound-time-pitch-level`. **Loudness 3.0 ACCEPTED** (banner's "0-1"
    advisory) — renders with `OVERLOAD!!` warning.
  - pitch 130: `ERROR: Pitch (130.000000) (2nd item) on line 2 out of range (0.000000 -
    127.000000): OR data not grouped as sound-time-pitch-level`.
  - duration 0.001: `ERROR: Duration (0.001000) at line 2 is too short for splicelen
    (2 ms)` — a FIXED 2 ms reader floor, independent of `-s`.
  - value count ≢ pitches+5k: `ERROR: Sound-number, Time, Pitch, Level, Duration vals
    not grouped correctly: or sound-pitches listed incorrectly`.
- **Time ceiling NOT enforced:** the source declares a 0–7200 s special range but an
  event at t=7300 rendered a 1.29 GB file, exit 0 (deleted). Engine cap is the guard.

### 1.2 Duration rule (headline)

| sequence (last events) | outdur | predicted |
| --- | --- | --- |
| ev3 = `1 1.0 76 1.0 0.3` (unity) | 1.3000 | 1.0 + 0.3 |
| ev = `1 1.0 88 1.0 0.3` (+12) | **1.1500** | 1.0 + 0.3/2 |
| ev = `1 1.0 64 1.0 0.3` (−12, dur 0.3) | 1.3000 | 1.0 + min(0.6, 0.3) |
| ev = `1 1.0 64 1.0 0.7` (−12, dur 0.7) | 1.6000 | 1.0 + min(0.6, 0.7) |
| ev = `1 1.0 76 1.0 0.1` (curtail) | 1.1000 | 1.0 + 0.1 |
| ev = `1 1.0 76 1.0 5.0` (no extend) | 1.3000 | 1.0 + 0.3 |
| ping6 ev1 = `1 0.0 64 1.0 2.0` then ev2 ends 0.55 | **1.2000** | max rule |
| ping6 last = `1 0.5 64 1.0 2.0` | 1.7000 | 0.5 + 1.2 |
| 3-event chord at t=0.1 (longest = tock4) | 0.5000 | 0.1 + 0.4 |

- **duration rule (exact, 4 dp, all 9 probes):**
  `outdur = MAX over events of (time_i + min(indur[snd_i] / 2^((pitch_i − notional_i)/12), dur_i))`
  — NOT the last listed event: an earlier event's long tail IS kept (the
  `sequencer2_preprocess` tempsize is last-event-only, but the writer's `max_write`
  keeps every tail). Listed duration CURTAILS (end-splice) but NEVER EXTENDS.
- **Transposition is sample-rate resampling:** +12 event measured 1314 Hz (≈1320)
  and half length. **Notional pitch is purely relative:** notional 60/event 72 rendered
  byte-identical to notional 76/event 88.

### 1.3 Params, overload, channels, determinism

- attenuation: `ERROR: Parameter[2] Value (1.500000) out of range (0.000000 to
  1.000000)` (−0.5 same). **attenuation 0 accepted → digital silence** (peak 0.0000).
  Brk refused `Cannot read parameter 1 [b_at.brk]: brkpnt_files not permitted.`
- splice `-s`: `Parameter[3] ... out of range (2.000000 to 200.000000)` (1 and 201
  refused). Default 2 (flag-less == `-s2` byte-identical). Splice matters ONLY when an
  event is curtailed (`-s50` == default on an uncurtailed sequence; differs on
  a curtailed one). Brk refused (`parameter 2`).
- **Overload:** 3-note full-level chord → `OVERLOAD!!` printed once, exit 0, decoded
  peak **1.8052** — raw float sums written, no clipping/wrap.
- Channels: mono+stereo refused `ERROR: Incompatible channel-count in input file
  tock4st.wav.`; stereo+stereo OK (2 ch out); mono→mono. Mixed srate refused
  `ERROR: Incompatible sample-rate in input file ping3_22k.wav.` Single input:
  `Insufficient input files for this process`. 3 inputs verified (variadic; 1.4000 =
  1.0 + 0.4).
- Deterministic: identical decoded shas 1.2 s apart. No seed exists.

## 2. extend iterate (modes 1 outduration / 2 repetitions)

Working argv: `extend iterate 1 ping3.wav out.wav 2.0 [flags]` /
`extend iterate 2 ping3.wav out.wav 5 [flags]` — flags real here (`-d -r -p -a -f -g -s`).

### 2.1 Duration models (exact, rand/pshift 0)

Mode 1 (delay defaults to indur):

| indur | outdur | delay | actual | model `delay*(ceil(outdur/delay)−1)+indur` |
| --- | --- | --- | --- | --- |
| 0.3 | 2.0 | (0.3) | 2.1000 | 2.1 |
| 0.3 | 1.5 | (0.3) | 1.5000 | 1.5 |
| 0.3 | 3.0 | (0.3) | 3.0000 | 3.0 |
| 0.3 | 2.0 | 0.2 | 2.1000 | 2.1 |
| 0.3 | 2.0 | 0.5 | 1.8000 | 1.8 |
| 0.6 | 2.0 | (0.6) | 2.4000 | 2.4 |
| 0.6 | 3.0 | 0.25 | 3.3500 | 3.35 |

Mode 2:

| indur | reps | delay | actual | model `reps*delay + indur` |
| --- | --- | --- | --- | --- |
| 0.3 | 2 | (0.3) | 0.9000 | 0.9 |
| 0.3 | 10 | (0.3) | 3.3000 | 3.3 |
| 0.3 | 5 | 0.2 | 1.3000 | 1.3 |
| 0.3 | 5 | 0.5 | 2.8000 | 2.8 |
| 0.6 | 5 | (0.6) | 3.6000 | 3.6 |
| 0.6 | 3 | 0.25 | 1.3500 | 1.35 |
| 0.3 | 1 | (0.3) | 0.6000 | 0.6 |

- **repetitions counts EXTRA copies** (total = reps+1); fractional reps ROUNDED
  (2.5 → 3, duration 1.2000). **Mode equivalence:** mode 1 outdur 1.8 byte-identical
  to mode 2 reps 5 (sha `5eb2ca0b0b95ee8a`).
- `-d0` accepted despite the quoted floor: all copies stack at t=0 (mode 2 output
  0.3000 = indur — unison layer).

### 2.2 Seed hunt (mode 2, reps 5, delay 0.15)

| run | sha (16) | verdict |
| --- | --- | --- |
| `-p2` unseeded ×2, 1.3 s apart | `c98d9f0f...` vs `8b0aae98...` (durs 1.0322/1.0766) | clock path |
| `-p2 -s5` ×2, 1.3 s apart | `0625b927...` == | **seed works** |
| `-p2 -s9` | `e64452c2...` | differs from s5 |
| `-p2 -s0` ×2, 1.3 s apart | differ | **seed 0 = clock** |
| defaults `-s5` / `-s9` / no seed | all `4048245f...` | **seed inert at zero random params** |
| defaults ×2 timed 1.3 s apart | identical | deterministic base |

Source: extprepro.c:1133 `if(RSEED > 0) srand(seed) else initrand48()`.

- **Random-param census (unseeded pairs 1.3 s apart):** `-r0.5` differ (durations
  too — jittered onsets); `-a0.5` differ (same length); **`-f0.3` BYTE-IDENTICAL —
  fade is deterministic** despite the banner's "(average)". fade 0.3 envelope:
  quarter-peaks 0.75/0.55/0.385/0.27/0.19 → gain_n ≈ (1−fade)^n.
- **gain:** `-g1` = unity (overlap sum peak 0.865 from a 0.77 source); default 0 =
  auto ≈ 1/(overlap count) (envelope == `-g0.5` at delay = indur/2).

### 2.3 Ranges (verbatim) and breakpoints

- outduration m1: `Parameter[1] Value (0.200000) out of range (0.300000 to
  32767.000000)` (floor = indur; 32768 refused).
- repetitions m2: `(1.000000 to 32767.000000)` (0 refused).
- delay: `Parameter[2] Value (101.000000) out of range (0.000002 to 100.000000)`.
- rand/ampcut/fade/gain: `(0.000000 to 1.000000)` each (Parameters 3/5/6/7);
  pshift: `(0.000000 to 12.000000)` (Parameter[4]); seed: `(0.000000 to
  32767.000000)` (Parameter[8], −1 and 32768 refused).
- **Breakpoints (at `-s5`):** delay brk 0.1→0.4 → 0.9742 s vs endpoints 0.8/2.3 —
  distinct from both → **capable**; rand brk (1.6045 vs 1.7999/1.2250) → capable;
  pshift brk (1.8647 vs 1.8000/1.9155) → capable; ampcut brk (same frames, distinct
  shas from both endpoints) → capable. **fade brk BROKEN:** accepted syntactically,
  always aborts `ERROR: No significant signal level found` (with and without `-g1`).
  gain brk refused `Cannot read parameter 7`; reps/outdur `parameter 1`; seed
  `parameter 8`.
- Stereo accepted (reps 3 → 1.2000, 2 ch). Overwrite refused (no-clobber verified —
  the early "exit 255" mystery was rerunning onto existing outputs).

## 3. iterline (mode 1 interpolate / mode 2 step)

### 3.1 ARGV DIVERGENCE (first-class)

The banner prints flag syntax (`[-ddelay] [-rrand] ...`) but the CLI refuses it
(`ERROR: Insufficient parameters on cmdline.`). Source (new/iterline.c:529)
`set_param_data(ap,ITERTRANS,8,7,"dDDDD0di")`: **all params are REQUIRED
POSITIONALS** — `iterline iterline mode infile outfile tdata outdur delay rand pshift
ampcut gain seed [-n]`. Only `-n` is a real flag. Working argv:
`iterline iterline 1 ping3.wav out.wav td.txt 2.0 0.3 0 0 0 0 5` — exit 0.

### 3.2 FIRST-EVENT BUG (first-class, source-diagnosed)

With tdata `0 0 / 2 12`, delay 0.3, outdur 2.0 — per-event pitch (FFT of each onset,
st rel. 660 Hz):

- mode 1: events at 0/0.3/…/1.8 s measured **[10.9], 1.8, 3.6, 5.4, 7.2, 9.0, 10.8** —
  events 2..7 = exact linear interpolation of the line at their onsets; event 1 =
  the value at the LAST event's time.
- mode 2: **[12.0], 0, 0, 0, 12, 12, 12** — step switches halfway (1.0 s); event 1 =
  the line's END value again.
- 3-point line `0 0 / 1 5 / 2 10` (step): **[10.0], 0, 5, 5, 5, 5, 10** — ev1 = final
  value; the t=1.5 equidistant event takes the EARLIER value (source
  `read_stepd_transposition_value`: `histep < lostep` strict).
- Mechanism: the two-pass renderer (level pass + write pass) initialises `thistrans =
  trans[1]` ONCE before both passes (iterline.c:1361); pass 1 leaves it at the line's
  end and pass 2's first event renders before the first table read.

### 3.3 tdata rules (all verbatim)

- `ERROR: Initial time in data in file td_bad1.txt must be zero.`
- `ERROR: Times do not advance between 1.000000 and 0.800000 in file td_bad2.txt`
- `ERROR: Data not paired correctly in file td_bad3.txt` (odd count)
- `ERROR: Found transposition value (25.000000) out of range (-24 to +24) in file
  td_bad4.txt` (±24 accepted)
- `ERROR: No data found in file td_bad5.txt` (comments only)
- `;` comments allowed; line HOLDS its final value beyond its last time.

### 3.4 Seed, ranges, breakpoints, landmines

- Seed (pshift 3): s5 ×2 1.3 s apart byte-identical; s5 vs s9 differ; s0 ×2 differ
  (clock); defaults s5 == s9 (inert). `-n` with seed 0:
  `ERROR: NORMALISATION CANNOT BE USED IF SEED VALUE IS ZERO` (verbatim).
- **delay 0 HANGS** (exit 124 timeout kill, 2 KB junk file) — the outdur-based loop
  never advances. **Auto-gain overshoot:** pshift 3 at default gain → peak **1.86**
  (floats unclipped).
- Ranges verbatim: outdur `(0.300000 to 32767.000000)` [Parameter[2], floor=indur];
  delay `(0.000002 to 100.000000)`; rand/ampcut/gain 0–1 (Parameters 4/6/7); pshift
  0–12 (Parameter[5]); seed 0–32767 (Parameter[8]).
- **Mode digits:** mode 3 silently accepted, byte-identical to mode 2
  (`5053a692e2bb45d2` both); mode 0 → exit 249, no message.
- Breakpoints (at seed 5): delay brk 1.8473 vs endpoints 2.0563/1.7734 → capable;
  rand brk 2.1432 vs 2.1035/2.0772 → capable; pshift brk 2.0538 vs 2.1036/2.0493 →
  capable; ampcut brk distinct from both same-length endpoints → capable. gain brk
  refused `Cannot read parameter 7`; outdur `parameter 1`; seed `parameter 8`.
- Duration: 2.0 requested → 1.9618 (+12 line end: last onset 1.8 + 0.3/2^0.9);
  ping6 outdur 3.0 delay 0.5 → 2.8019 (= 2.5 + 0.6/2, line-end hold) — model:
  last onset below outdur + transposed last copy. Stereo accepted (2 ch, same length).
  Defaults pair timed 1.3 s apart byte-identical.

## 4. iterlinef (the 25-sound set version)

Working argv: `iterlinef iterlinef 1 set01..set25 out.wav td.txt 2.0 0.3 0 0 0 0 5` —
exit 0 (2.1035 s from a 2.0 request). Same all-positional argv, seed semantics
(s5 ×2 byte-identical at pshift 3, s9 differs), first-event bug (ev1 = +10.85 on a
0→12 line), delay brk accepted / gain brk refused (`Cannot read parameter 7`).

- **ARITY IS A SILENT CRASH GATE:** 3, 24 and 26 inputs all → **exit 254, NO error
  message at all**; exactly 25 runs.
- **Per-event selection (source iterlinef.c:1824-7 + marker probe):** `filindx =
  lround(transposition) + 12` (0-based; file 13 = 0 st), residual resampled. Planted
  `nburst35` (noise) as set18 (+5): constant +5 line → events are NOISE (flatness
  0.84 — file 18 played verbatim); constant +5.5 → events TONAL at +5.4 (rounded AWAY
  to file 19, resampled −0.5); constant 0 → file 13. Line's ±24 range exceeds the
  set's ±12 — the overflow resamples edge files.
- Unequal durations accepted silently (banner "approx equal" advisory — double-length
  set18 ran); mixed channel counts refused `ERROR: Incompatible channel-count in input
  file setD/set18.wav.`

## 5. shrink (modes 1–4; 5–6 probed for the drop)

Working argv m1–3: `shrink shrink 1 ping3.wav out.wav 0.7 0.4 0.8 3.0 10 [-s -m -r -n -i]`;
m4 adds leading time: `shrink shrink 4 ping3.wav out.wav 0.05 0.7 0.4 0.8 3.0 10`.

### 5.1 Mode content (envelope of repeat 4 on the decaying ping, quarter-peaks)

| mode | quarter-peaks | keeps |
| --- | --- | --- |
| 1 (from end) | 0.771 / 0.554 / 0.386 / 0.27 | **ATTACK** |
| 2 (around midpoint) | 0.175 / 0.14 / 0.097 / 0.068 | middle |
| 3 (from start) | 0.044 / 0.035 / 0.025 / 0.017 | tail |
| 4 (around t=0.05) | 0.693 / 0.554 / 0.386 / 0.27 | around chosen time |

All four rendered the SAME event grid (1.9321 s on the shared settings), different
content shas.

### 5.2 Duration semantics

- shrinkage 0.7 / gap 0.4 / contract 0.8 / dur 3.0 → **1.9321** = Σ gap·0.8^k
  (k=0..13, until gaps hit the shrunken-sound floor) + final event — the series HALTS
  before dur: **the banner's "DUR (Minimum) duration" is FALSE** without `-m`.
- dur 1.0 (same series) → 1.1808 = first cumulative gap sum ≥ dur (truncation).
- dur 10 → 1.9321 (natural end).
- `-m0.1` → 3.0806 (grid regularises at 0.1, runs out to dur). `-s0.08` → 1.7444
  (sound floor reached sooner → earlier halt). Both → 3.0806.
- **contract = 1 (equal spacing) is EXACT: repeats start at multiples of gap strictly
  below dur; output = last start + gap** — probes 3.2000 (0.4/3.0), 2.5000 (0.5/2.2),
  3.5000 (ping6 0.7/3.0), 3.2000 (shrinkage 0/0.4/3.0), 6.0000 (2 s ping, 2.0/6.0 —
  the duration-row pair, exact-multiple boundary included), 8.0000 (2.0/6.5), and
  mode 4 6.0000 (time 0.5, 2.0/6.0). Curated expression
  `gap * (((dur - 0.000001) // gap) + 1)`; over-predicts (safe) when contract < 1.
  **FLOAT BORDERLINE:** dur an exact decimal multiple of a NON-binary-exact gap gains
  one extra gap (0.3/0.9 rendered **1.2000**, not 0.9 — 3×float(0.3) accumulates just
  under 0.9); binary-exact pairs (2.0/6.0) sit on the predicted side.

### 5.3 Randomisation (headline: fixed-sequence, seedless)

- `-r0.5` WITHOUT `-m`: **byte-identical to no `-r` at all** (sha
  `3b1d6f2016b1783d` = base) — rnd only acts after the `-m` floor is reached.
- `-r0.5 -m0.1 -s0.05` ×2, 1.3 s apart: **byte-identical** (`1fe748b5fce121b1`);
  differs from `-m -s` without `-r` (`3efe500d...`) and from `-r0.9`
  (`6f71d0d5...`) — the jitter is real but the SEQUENCE IS FIXED: source has no
  srand/initrand48 call anywhere in new/shrink.c; the osbind drand48 shim runs from
  rand()'s default seed. stochastic: false; no seed exists; version_sensitive.

### 5.4 Ranges (verbatim), flags, crash

- shrinkage: `Parameter[1] Value (1.100000) out of range (0.000000 to 1.000000)`
  (0 legal = pure repeats); gap: `Parameter[2] Value (0.200000) out of range (0.300000
  to 60.000000)` (floor = indur); contract: `(0.000000 to 1.000000)` + runtime
  `ERROR: Contraction of inter-events distance can't be less than shrinkage of
  sounds.`; dur: `Parameter[4] ... out of range (0.600000 to 32767.000000)` (floor =
  2×indur); spl: `(2.000000 to 50.000000)`; m4 time: `Parameter[1] Value (0.400000)
  out of range (0.000000 to 0.300000)` (0..indur); `-m11`: `ERROR: Minimum event
  separation must be less than initial event separation.`; `-r1.5`: `(0.000000 to
  1.000000)` (Parameter[8]).
- **CRASH: `-s0.5` (> indur 0.3) → exit 139 SEGFAULT, no message.**
- Breakpoints: ALL EIGHT params refuse — `Cannot read parameter 2..9 [...]:
  brkpnt_files not permitted.` (shrinkage 2, gap 3, contract 4, dur 5, spl 6,
  small 7, min 8, rnd 9 — each probed).
- `-n` (equalise event levels) byte-identical to base in mode 1 (attack kept in every
  repeat); `-i` (reverse each segment) differs. Stereo accepted.

### 5.5 Modes 5/6 — multi-output evidence (DROPPED)

`shrink shrink 5 syl2.wav gen5 0.7 50 0.8 0.1 10` → exit 0, wrote **gen50.wav,
gen51.wav, gen52.wav, gen53.wav** (one per found peak, shrinking 0.4644/0.4087/
0.3269/0.2140 s) **plus `gen54`** — an extensionless ASCII CDP MIXFILE
(`gen50.wav 0.000000 1 1.0 …`). Mode 6 (`peaktimes` textfile `0.35/1.0/1.55`) same
shape: gen60–62.wav + gen63 mixfile. N+1 self-named outputs, no output argv
verification possible — dropped with record (afta8 concurs: "[Doesn't work -
multiple outputs]").

## 6. texture decorated, submode 5 (RETRY — first landing)

Pre-check: grep of tranche 5/6/7 transcripts + findings shows **no texture-decorated
record at all** — planned in Phase 5 wave 2 but never probed; no prior drop to honor.

Working argv: `texture decorated 5 ping3.wav out.wav ndec.txt 5 1.5 1 1 60 64 0.1 0.3
0 1 1 0 0 2 5 20 80 3 8 0 -r5` — exit 0 (6.2559 s, 2 ch from mono). ndec.txt:
`60 / #2 / 0 1 60 64 0.5 / 1 1 62 64 0.5`.

- **Notedata error surface (verbatim):** pitch line only →
  `ERROR: Incorrect number [0] of motifs in notedata file (expected 1).`; missing `#`
  → `ERROR: '#' missing before datacount in notedata file: motif 1 (or more notes
  listed than indicated by #N)`; short count → `ERROR: Note data line for note 2,
  motif 1 missing in notedatafile`; reversed times → `ERROR: Notes in reverse time
  order: notedata file : motif 1: notes 2 & 1`. A line starting at t=1 runs (exit 0).
- **Seed:** `-r5` ×2 1.3 s apart byte-identical (`c48ec72b4d1d4e2d`); `-r9` differs;
  unseeded ×2 differ; `-r0` ×3 all differ → 0/omission = clock.
- **Duration (set_by outdur):** 2-note 1.5 s line, skiptime 1.5: outdur 5 → 6.2559
  (+25.6%), 8 → 9.0342 (+13%). 1-note 0.2 s line, skiptime 0.5, small groups
  (2–4 events, 20–60 ms, maxdur 0.15): 5 → 5.7132 (+14.3%), 8 → 8.6012 (+7.5%),
  3 → 3.7449 (+25%) — overshoot ≈ line span + last ornament tail. Row pinned on the
  small-line settings, tol 0.2.
- **Banner divergences (first-class):** centring refused
  `Parameter[21] Value (8.000000) out of range (0.000000 to 6.000000)` — banner says
  "Range 0-7"; pos refused `Parameter[23] Value (-1.000000) out of range (0.000000 to
  1.000000)` — banner says "-1(Left) 1(Right): default 0". contour 0–8 confirmed
  (`Parameter[14] Value (9.000000) out of range (0.000000 to 8.000000)`; decorated
  extras 7/8 vs grouped's 0–6). gpspace `Parameter[11] ... (0.000000 to 5.000000)`;
  amprise `Parameter[13] ... (0.000000 to 127.000000)`; atten `Parameter[22]
  (0.000002 to 1.000000)`; spread `Parameter[24] (0.000000 to 1.000000)`; sndfirst 2 →
  `ERROR: FIRST SND-IN-LIST TO USE > count of files entered: cannot proceed.`
- **SKIPTIME 0 HANGS** (exit 124 timeout); skiptime −1 refused `Parameter[3] ...
  (0.000002 to 100.000000)`.
- **Breakpoints (all 20 positionals + 4 flags probed):** outdur (`Cannot read
  parameter 1`), gpspace (`parameter 14`), contour (`parameter 17`), centring
  (`parameter 26`) and seed (`parameter 30`) REFUSE; skiptime, sndfirst, sndlast,
  mingain, maxgain, mindur, maxdur, phgrid, gpsprange, amprise, gpsizlo, gpsizhi,
  gppaklo, gppakhi, gpranglo, gpranghi and `-a`/`-p`/`-s` all exit 0.
- **Flag order enforced:** `-r5 -a0.5` → `ERROR: option flag -a out of order on
  cmdline.` (banner order -a -p -s -r then switches).
- **Switches:** `-w` (+0.18 s, differs), `-d` (differs), `-k` (differs, same length);
  `-i`, `-h`, `-e` byte-identical no-ops here (single input, chordless line).
- Stereo input refused `Application doesn't work with this type of infile.`;
  output always 2-channel.

---

## Engine spot-checks (process_impl end-to-end, entries as written, CDP_PATH=/tmp/CDP8/NewRelease)

| entry | params | predicted | measured | verdict |
| --- | --- | --- | --- | --- |
| extend iterate sm2 | reps 5, delay 0.15, seed 5 (0.3 s ping) | 1.05 | 1.0500 | exact |
| extend sequence2 | seq.txt (3 events, +12 last), atten 1 | 1.15 (rule) | 1.1500 | exact |
| iterline sm1 | line.txt 0→12, outdur 2.0, delay 0.3, seed 5 | 2.0 (set_by) | 1.9618 | −1.9% |
| shrink sm1 | 0.7/0.4/contract 1.0/dur 3.0/spl 10 | 3.2 | 3.2000 | exact |
| texture decorated sm5 | ndec 1-note line, outdur 5, skiptime 0.5, seed 5 | 5.0 (set_by) | 5.6147 (2 ch) | +12.3% (tol 0.2) |

Negative check: extend iterate sm2 WITHOUT delay → structured
`predicted_duration_evaluation_failed` naming `delay` (documented in the entry:
always pass delay).

Nine entries shipped; one family drop recorded (shrink modes 5/6, multi-output).
Multi-input duration rules pinned here: extend sequence2 (max-rule above, duration_row
null) and iterlinef (set_by outduration + last transposed copy, duration_row null —
25-input entry cannot run on the shared single-input fixture).
