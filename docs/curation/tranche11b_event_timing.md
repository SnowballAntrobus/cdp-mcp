# Tranche 11b — event-timing surgery, timefile glue, Phase 6b channel machinery: probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build; `housekeep`
  banners "CDP Release 7.1 2016"; `retime`/`peakfind`/`clicknew`/`sorter`/`stutter`/
  `refocus`/`repair` print no release banner — CDP8-new/standalone family), Linux x86_64
  sandbox. To be re-verified on macOS r8 by the CDP-gated suite after integration.
- **Inputs:** shared fixtures `/tmp/probe` (`flat2` flat noise 2.0 s — no silences;
  `syl2` syllable train 2.0 s, 4 events at 0.100–0.400/0.601–0.900/1.101–1.400/
  1.601–1.900, 0.2 s zero gaps; `n1` 1 s noise). Fresh fixtures in `/tmp/probe11b`
  (numpy/soundfile, float32, true digital-zero gaps — the 4-syllable recipe from
  `tests/test_generalization.py::_synth_vocal`):
  - `ev4.wav` 2.5 s, 4 vocal-formant events at onsets 0.05/0.70/1.30/2.00 (lens
    0.50/0.45/0.55/0.42; 0.15 s zero gaps; 0.05 lead; 0.08 tail).
  - `ev3.wav` 1.8 s, 3 events at 0.05/0.60/1.10 (lens 0.40/0.35/0.45).
  - `ev4st.wav` stereo ev4 (R = 0.7×L); `ev4lv.wav` ev4 with event gains
    1.0/0.3/0.6/0.15 (level-adjust probes); `ev4q.wav` 4-channel ev4.
  - `burst4.wav` 2.2 s, sharp decaying noise bursts at 0.10/0.60/1.20/1.90.
  - `nozero2.wav` 2 s noise with NO exact-zero samples anywhere (detector floor probe).
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. Breakpoint proof =
  brk render differs from BOTH scalar-endpoint renders (at fixed seed where one exists);
  determinism pairs > 1.1 s apart; shas over decoded float64 samples; fresh output names
  per run; duration models at ≥ 2 input durations.
- **Priors:** SoundThread `process_help.json` has NO keys for any tranche-11b target
  (checked: retime/peakfind/clicknew/sorter/stutter/refocus/repair/housekeep chans).
  afta8 covers `peakfind` and `retime` modes 1/6/7/9/10/11/12/13/14 (channels "any"
  claims); nothing else. Source: `dev/standalone/retime.c`, `dev/standalone/peakfind.c`,
  `dev/standnew/clicknew.c`, `dev/standnew/repair.c`, `dev/science/sorter.c`,
  `dev/science/stutter.c`, `dev/science/refocus.c`.

Refusal errors quoted verbatim (stdout, exit 255).

---

## 1. retime — event-detection semantics (the tranche's material-sensitivity axis)

**Silence = literal digital zeros.** Source (`retime.c count_events()`, line 3903, and
the per-mode counters at 2272/3450/3820): a sample belongs to a silence iff
`ibuf[i] == 0.0` — there is NO threshold, configurable or otherwise. A "silence-separated
event" is a run of not-all-zero samples bounded by ≥ minsil ms of *exact* zeros
(`minsil` converted to samples × chans). Real-world recordings with any noise floor have
no exact zeros; retime's event modes see them as ONE event. `pregain` cannot help
(scaling never creates zeros). Gate/edit material first (e.g. sfedit, envel) to create
true zeros.

**Material with NO silences — behavior differs BY MODE (all pinned on `flat2`/`nozero2`):**

| mode | behavior on no-silence material |
| ---- | ------------------------------- |
| 1 | N/A — mode 1 detects nothing; user supplies refpoints; works on any material |
| 4, 5 | exit 0 + `WARNING: WARNING: only 1 event found: Change inter-event silence ??` (doubled WARNING verbatim) → near-passthrough: 2 s in → 1.9999773 s out, one frame short, max residual 3.5e-4 vs input (NOT byte-exact) |
| 3, 6, 7, 8, 9, 10 | refused `ERROR: INVALID DATA / ERROR: NO SILENCE-GAPS FOUND IN FILE.` |

- minsil range verbatim (all event modes): `(0.045351 to 10000.000000)` ms — floor =
  2 samples at 44.1k (`(2.0/srate)*SECS_TO_MS`, srate-dependent).
- `retime.c` contains NO rand of any kind — every curated mode verified deterministic
  (identical decoded shas > 1.1 s apart: modes 1, 3, 4, 5, 6, 7, 8, 9, 10).
- Stereo accepted by modes 1/3/4/5/6/7/8/9/10 (2-ch outputs, durations match mono
  predictions) → `any`. Mode 12 has a stereo BUG (below) → pinned mono.

### mode 1 (user-specified peaks → regular pulse)

Working: `retime retime 1 ev4.wav out.wav refpts.txt 120` (refpts = peak times
0.30/0.925/1.575/2.21, newline-separated) — exit 0, 2.09 s.

- refpoints is a REQUIRED DATAFILE (scalar refused
  `ERROR: Failed to open file 0.3 for input.`). Times must ascend:
  `ERROR: TIME (0.500000) OUT OF SEQUENCE OR INVALID, IN FILE bad_order.txt.`;
  ≥ 2 times required: `ERROR: TOO FEW ENTERED TIMES (MUST BE AT LEAST 2).` — times past
  EOF are discarded first (a 2-time file with one time at 3.5 s on a 2.5 s input refuses
  with the same TOO FEW message).
- Events are aligned by their PEAK (refpoint), not onset, onto the grid
  `first_refpoint + k*beat`. Duration on ev4 fits
  `first_ref + (n−1)*beat + (indur − last_ref)` at both tempi (2.09 @120, 3.59 @60)
  but NOT on flat2 (predicted 2.0, got 1.5 — inter-peak segments truncate when they
  collide) — duration is data-dependent, no closed form curated.
- tempo range `(0.000000 to 400.000000)` + runtime rule
  `ERROR: Output tempo vals must be > 0 AND less than 1 (beat duration) OR >= 20 (MM)`
  (tempo 10 refused). **Dual-unit verified byte-exact:** tempo 0.5 (beat secs) renders
  byte-identical to tempo 120 (MM).
- tempo brk refused (`Cannot read parameter 1 [...]: brkpnt_files not permitted.`).
- Deterministic; stereo accepted (2.09 s, 2 ch).

### mode 3 (shorten events)

Working: `retime retime 3 ev4.wav out.wav 50 100 80 10` — exit 0,
`INFO: 4 of 4 events will be shortened`, 2.0900 s.

- Events shortened IN PLACE to outevwidth(+splice): onsets stay at 0.05/0.70/1.30/2.00;
  output = last_onset + (outevwidth + splicelen)/1000, exact on ev4 (2.09 = 2.00+0.09)
  and ev3 (1.19 = 1.10+0.09) and at outev 200/splice 15 (2.215). Trailing silence
  dropped; gaps between events widen.
- Ranges: inevwidth/outevwidth/splicelen `(1.000000 to 1000.000000)` (Parameters 2/3/4);
  all 4 params refuse brks (parameters 1–4). Flat noise refused (NO SILENCE-GAPS).
- Deterministic; stereo accepted.

### mode 4 (events → regular MM)

Working: `retime retime 4 ev4.wav out.wav 120 50 1` — exit 0, `INFO: 4 events found`,
1.97 s.

- Event ONSETS placed at `lead_silence + k*beat`; output duration =
  `lead + (n−1)*beat + last_event_len`, 4-dp exact on ev4 @120/@60/@0.7-beat, ev3 @120,
  syl2 @120 (5/5). Events longer than the beat overrun/merge (no gap in output).
- Zero-run proof (beat 1.0): onsets at 0.05/1.05/2.05/3.05.
- tempo `(0.000000 to 6000.000000)` + the same >0/<1-or-≥20 runtime rule; minsil
  `(0.045351 to 10000.000000)` (P2); pregain `(0.000000 to 1.000000)` (P3), pregain 0
  refused `ERROR: Pregain parameter of zero, will produce silent output.`
- All 3 params refuse brks (parameters 1–3). Deterministic; stereo accepted.
- Flat noise: WARNING + near-passthrough (1.9999773 s) → static duration_row pinned on
  the shared fixture.

### mode 5 (speed-change events)

Working: `retime retime 5 ev4.wav out.wav 2 50` — exit 0, 1.4450 s.

- Inter-onset intervals scaled by 1/factor, event content untouched (silence edited):
  factor 2 → onsets 0.05/0.375/0.675/1.025 (+0.42 last len = 1.445 exact); factor 0.5 →
  0.05/1.35/2.55/3.95 (4.37 exact); ev3 factor 2 → 1.025 exact. Duration =
  `lead + (last_onset − first_onset)/factor + last_len` — data-dependent.
- **factor is breakpoint-capable** (banner: "can vary over time"): brk 0.5→2 renders
  2.057 s, differs from BOTH scalar-endpoint renders. minsil brk refused (parameter 2).
- factor `(0.010000 to 100.000000)`; factor 1 refused
  `ERROR: INVALID DATA / ERROR: No change in tempo.`; -s start `(0.000000 to 2.500000)`
  (Parameter[3], runtime = indur). -s/-e zone and -a sync verified live (renders and
  durations change: 1.77 s with -s0.6 -e1.9).
- Flat noise: WARNING + passthrough. Deterministic; stereo accepted (1.4450, 2 ch).

### mode 6 (events at specified beats, aux retempodata) / mode 7 (at specified times)

Working: `retime retime 6 ev4.wav out.wav beats4.txt 120 0.2 50 1` → 2.12 s;
`retime retime 7 ev4.wav out.wav times4.txt 0.2 50 1` → 2.22 s.

- Onsets verified at `offset + beat_k*beatdur` (mode 6; swing file 0/1.5/2/3 → onsets
  0.2/0.95/1.2/1.7) and `offset + time_k` (mode 7; 0/0.4/0.8/1.6 → 0.2/0.6/1.0/1.8).
  Duration = offset + last_entry(*beatdur) + last_event_len — exact on both.
- **Datafile-count contract (contrast grain reposition's silent drop):** FEWER entries
  than events → refused
  `ERROR: Found 4 events, but only 2 out-event-beat-placements specified.`; MORE →
  `WARNING: Found 4 events : 6 out-event-beat-placements specified.` + surplus ignored.
- Ranges: mode 6 tempo `(0.010000 to 1000.000000)` (P2), offset `(0.000000 to
  1000.000000)` (P3); mode 7 offset `(0.000000 to 1000.000000)` (P2). Pregain ≈ 0
  refused `ERROR: Pregain is (effectively) zero: output will be silence.`
- All numeric positionals refuse brks (mode 6: parameters 1/3/4 probed = tempo/minsil/
  pregain, offset param 2 by family; mode 7: parameters 1/2/3 = offset/minsil/pregain).
- Flat noise refused (NO SILENCE-GAPS). Deterministic (mode 6 pair verified; mode 7 pair
  verified); stereo accepted both.

### mode 8 (repeat marked event at tempo)

Working: `retime retime 8 ev4.wav out.wav 120 0.9 1 3 50` — exit 0, 4.00 s
(`INFO: Repeating Events.`).

- Copies of the marked event(s) are INSERTED at beat spacing within the original;
  duration fits `indur + repeats * cnt * 60/tempo` on 5/5 probes (ev4 @120 r3 → 4.0;
  @60 r2 → 4.5; ev3 @120 r3 → 3.3; beat-dur 0.8 r2 → 4.1; cnt 2 @120 r2 → 4.5).
  Zero-run proof @120 r3: inserted copies at 1.2/1.7/2.2.
- Ranges: tempo `(0.010000 to 1000.000000)` (P1); eventtime `(0.000000 to 2.500000)`
  (P2, runtime = indur); cnt `(1.000000 to 24.000000)` (P3); repeats
  `(1.000000 to 1000.000000)` (P4). eventtime inside a gap refused
  `ERROR: Time indicating event position does not lie within a sounding event.`
- All 5 params refuse brks (parameters 1–5). Flat noise refused (NO SILENCE-GAPS).
  Deterministic; stereo accepted (4.0, 2 ch).

### mode 9 (silence-pattern mask, aux maskdata)

Working: `retime retime 9 ev4.wav out.wav mask10.txt 50` (mask `1 0 1 0`) — exit 0, 2.5 s.

- Verified textbook: masked events replaced by silence IN PLACE (per-event RMS →
  0.0000), kept events untouched; duration STATIC sample-exact (2.5 → 2.5).
  **Pattern CYCLES** (banner-confirmed): 2-entry mask `0 1` on 4 events masks 1&3,
  keeps 2&4 (verified per-event RMS).
- Mask values only 0/1: `ERROR: MASK VALUE (2.000000) INVALID IN FILE mask2.txt.`
  All-zero mask exits 0 and writes an ALL-SILENT full-length file (engine RMS
  verification is the only guard).
- minsil brk refused (parameter 1). Flat noise refused (NO SILENCE-GAPS).
  Deterministic; stereo accepted (2.5, 2 ch).

### mode 10 (level equalize / accent)

Working: `retime retime 10 ev4lv.wav out.wav 50 1` — exit 0, 2.5 s (static,
sample-exact; `INFO: Extracting events envelope / INFO: Adjusting events loudness`).

- **METER path verified exact:** `-m3` on gains 1.0/0.3/0.6/0.15 → unaccented events
  scaled to exactly evening × accent level (peaks 0.68/0.204/0.204/0.68; 0.204/0.68 =
  0.3 = evening). Accents every meter-th event starting at event 1.
- **EVENING (meter 0) path CLIPS (first-class):** evening 1 on the same fixture drives
  event peaks to 1.0/3.35/1.43/6.45 — up to 6.4× OVER full scale in the float output
  (loudness equalization boosts quiet events with no headroom management, no warning).
  evening 0.5 still 3.28×. Stage attenuation after it, or use the meter path.
- **pregain `-p` is a NO-OP (first-class):** `-p0.5` and `-p0.1` render byte-identical
  to flag-less. Banner usage line reads `[-mmeter] [-mpregain]` — the second flag is
  actually `-p` (source `set_vflgs(ap,"mp",...)`, int meter + double pregain), and it
  does nothing in this mode.
- Ranges: evening `(0.000000 to 1.000000)` (P2); evening brk refused (parameter 2);
  meter brk refused (parameter 3). Flat noise refused (NO SILENCE-GAPS).
  Deterministic; stereo accepted (2.5, 2 ch).

### mode 12 (find start of sound → textfile)

Working: `retime retime 12 ev4.wav out.txt` — exit 0. Output: one line,
`0.050023\tev4.wav` (time of first non-zero sample, TAB, input filename as given).

- Extension enforced: `ERROR: Output textfile (r12b.wav) must have a '.txt' extension,
  or none.` If the file EXISTS the line is APPENDED (verified: two runs → two lines;
  source opens `"a"` "permits bulk-processing of files to same outfile") — moot under
  the engine's fresh-name contract.
- **STEREO BUG (first-class):** on ev4st (first nonzero frame 0.05) it reports
  0.100045 — the first nonzero INTERLEAVED-SAMPLE index divided by srate without
  channel correction; stereo times are 2× wrong. Entry pinned MONO.
- No parameters. Deterministic (identical text content).

### retime modes NOT curated (recorded)

- **mode 2:** `Mode only accessible via Sound Loom Properties Files` (verbatim, exit 255).
- **mode 11:** info mode, NO outfile argv (`retime retime 11 infile minsil`); prints
  `INFO: Shortest event = 0.419977 secs :: = 419.977324 mS / Longest event = 0.549977
  secs` to stdout (ev4, minsil 50). No output-file contract → engine-incompatible;
  reachable via execute().
- **modes 13/14** (move peak to time): outside this tranche's event-timing scope;
  banners recorded, unprobed.

## 2. peakfind

Working: `peakfind peakfind burst4.wav out.txt 50` — exit 0.

- **Output format (Phase 6 contract):** plain text, ONE peak time per line, C `%lf`
  (6 decimals), no header, newline-separated, ascending. burst4 (bursts at
  0.10/0.60/1.20/1.90) → `0.106871 / 0.601043 / 1.202993 / 1.902336`. Reserved
  extensions refused: `ERROR: Cannot open a textfile (pk_o.wav) with a reserved
  extension.` → data output `.txt`.
- windowsize `(1.000000 to 500.000000)` ms (P1); threshold `-t` `(0.000000 to 1.000000)`
  (P2); both refuse brks (parameters 1/2). Default threshold 0 = adaptive: windows below
  1/5 of the local max (over 10 windows) ignored (banner).
- Short-file rule: < 10 windows without a threshold →
  `ERROR: File too short to scan peaks without a threshold value (> 0.0) being
  entered.`; same file with `-t0.1` runs (one peak).
- Stereo: accepted, and times are CHANNEL-CORRECT (ev4 mono vs ev4st stereo → identical
  4 times) — unlike retime 12. → `any`.
- Deterministic (byte-identical text 1.2 s apart).

## 3. clicknew (mode name 'clicks') — and the peakfind round-trip

Working: `clicknew clicks out.wav pk_a.txt 44100` — exit 0, arity-0 (no audio input).

- **ROUND-TRIP VERIFIED:** peakfind's output fed VERBATIM as clicktimes renders a click
  train whose click onsets sit within 2 samples of each peakfind time (0.106871 →
  0.106916 etc., 4/4). Formats are directly compatible (both plain ascending seconds,
  whitespace/newline separated; clicknew also allows `;` comment lines — verified).
- Output: mono wav, dur = last time + click tail (~21 samples: 1.902336 → 1.902812);
  clicks ~18 samples wide, peak ~0.96.
- **CLOCK-SEEDED, UNSEEDABLE (first-class):** the CLICK WAVESHAPE is randomized per run
  (`generate_clicktable()`: `initrand48()` = `srand(time(0))` + two drand48 calls shaping
  the click); no seed argv. Verified: identical commands > 1.2 s apart differ in decoded
  samples (same duration); two runs in the SAME second byte-identical (collision trap).
  Click TIMES are deterministic; only the shape jitters.
- **BANNER SRATE LIST IS FALSE (first-class):** banner says "LEGAL SRATES are 16000,
  22050, 32000, 44100, 88200, 48000, 88200 and 96000" (88200 listed twice). Enforced:
  range gate `(44100.000000 to 96000.000000)` (16000/22050/24000/32000 refused) THEN
  `LEGAL_SRATE()` (globcon.h:94 = {16000,24000,22050,32000,44100,48000}) →
  88200 and 96000 refused `ERROR: Illegal Sampling Rate.` **Intersection = 44100 and
  48000 only.**
- Datafile rules: times ascend and ≥ 0 — `ERROR: Times do not advance at time
  -0.500000` — BUT the check resets per LINE (source: `lasttime = -1.0` inside the
  fgets loop): newline-separated non-ascending times are ACCEPTED and the render
  silently truncates at the out-of-order point (file `1.0\n0.5\n` → 0.50 s output).
  Same values space-separated on one line refuse. Max time 32767 s
  (`ERROR: Maximum time is excessive : 40000.000000`); a 32766-s time is ACCEPTED and
  renders a ~1.9 GB file — the engine duration cap/watchdog is the only guard.
- Single time works (0.5 → 0.5005 s).

## 4. sorter

Working: `sorter sorter 1 ev4lv.wav out.wav 0.1` / `sorter sorter 5 in out 0.1 42` —
exit 0. MONO ONLY: `ERROR: INVALID DATA / ERROR: File ev4st.wav is not of correct type
(must be mono)`.

- **Content verified:** mode 1 crescendo — output RMS thirds 0.037/0.065/0.161 (rising);
  mode 2 exact mirror 0.161/0.065/0.037. Modes 3/4 (accel/rit) run, same duration,
  distinct shas. esiz 0 = wavesets (verified, 2.419 s from 2.5).
- **SEED (mode 5) — banner's "zero = different each run" is FALSE (first-class):**
  source `if(mode==RAND && seed > 0) srand(seed)` — seed 0 never calls srand → glibc
  default state ≡ srand(1). Verified: seed 42 twice 1.2 s apart byte-identical; 42 vs 43
  differ; **seed 0 twice 1.3 s apart byte-identical AND identical to seed 1**. No clock
  path — sorter is ALWAYS reproducible; distinct-seed space is 1–256.
- Duration: NOT reliably static on event material — 2.5 → 2.3023 (−7.9 %) at esiz 0.1;
  ev3 1.8 → 1.4029 (−22 %, long tail silence + element quantization); n1 1.0 → 0.9012
  (−9.9 %); flat2 2.0 → 1.9518 (−2.4 %, inside row tolerance — row pinned on the flat
  fixture). Same duration across all 5 modes on the same input.
- Ranges: esiz `(0.000000 to 2000.000000)` (P1); esiz too big for file →
  `ERROR: Elementsize too big for infile. (If meant to be frq, set flag).`; seed
  `(0.000000 to 256.000000)` (P2); smooth `-s` `(0.000000 to 50.000000)` (quoted
  `Parameter[2]` — CDP numbering quirk); smooth changes render, not duration.
- Brk refusals: esiz (mode 1) `Cannot read parameter 2`; seed (mode 5)
  `Cannot read parameter 2` (same number quoted for both — quirk recorded).
- `-f`/opch/pch/meta (frequency-trace element sizing + pitch mapping) left to execute().
- Mode 1 deterministic (pair verified). Durations/shas: modes 1–5 on ev4lv all 2.3023 s,
  5 distinct shas.

## 5. stutter

Working: `stutter stutter ev4.wav out.wav slices.txt 4 1 0.3 0.05 0.2 5` — exit 0,
4.0001 s (slices.txt = `0.62/1.22/1.92`, the ev4 gap midpoints).

- **Duration = dur param (set_by) + up-to-one-segment overshoot:** dur 4 seed 5 →
  4.0001; dur 2.5 → 2.854; dur 6 → 6.257; seed 9 at dur 4 → 4.238 (overshoot is
  seed-dependent; the render finishes the segment in flight).
- **SEED WORKS, no clock path:** `srand(seed)` unconditional (stutter.c:1235). Seed 5
  twice > 1.2 s apart byte-identical; 5 vs 9 differ (samples AND duration);
  **seed 0 ≡ seed 1** (byte-identical, glibc srand(0)==srand(1)); range
  `(0.000000 to 256.000000)` (Parameter[7]).
- **Datafile (slice times) is material-agnostic** — flat noise works (4.007 s); slicing
  is by user times, not silence detection. Times: floor quoted
  `ERROR: Invalid time (0.001000) (closer to start than 2 splicedurs = 0.006) at line 1
  in file slbad.txt.` — the banner's "MT = 0.016 secs" is NOT the enforced rule (0.01
  step accepted; real rule 2×splicedur = 0.006 s); non-increasing refused
  `ERROR: Times (0.630000 & 0.620000) not increasing by 2 splicedurs (0.006) line 1 in
  file slord.txt.`; a time BEYOND EOF (2.6 on a 2.5 s file) is ACCEPTED silently and
  changes the render (5.84 s — landmine).
- Ranges (verbatim, param numbers): segjoins `(1.000000 to 8.000000)` P3; silprop
  `(0.000000 to 1.000000)` P4; silmin/silmax `(0.000000 to 10.000000)` P5/P6 —
  silmin > silmax accepted SILENTLY (runs, 4.08 s); trans `-t` `(0.000000 to 3.000000)`
  P8 (banner gives no bound — enforced 0–3 semitones); atten `-a` `(0.000000 to
  1.000000)` P9; bias `-b` `(-1.000000 to 1.000000)` P10; mindur `-m` `(8.000000 to
  250.000000)` P11 ms.
- **Breakpoints: trans and atten CAPABLE** (at seed 5: `-t` brk 0→3 → 4.321 s, differs
  from -t0 and -t3 renders; `-a` brk 0→1 differs from -a0 and -a1); `-t0`/`-a0`
  byte-equal flag-less. dur/segjoins/silprop/silmin/silmax/seed refuse brks (parameters
  1/2/3/4/5/6); `-b` and `-m` refuse (both quoted `parameter 10` — numbering quirk).
- `-p` permute switch live (render + duration change). Stereo accepted (4.0001, 2 ch) →
  `any`.

## 6. refocus — DROPPED (engine-incompatible multi-output; question answered)

- **bandcnt=1 does NOT yield a single file — it is REFUSED:**
  `ERROR: Parameter[2] Value (1.000000) out of range (2.000000 to 900.000000)` —
  bandcnt floor is 2; refocus is multi-output by construction.
- Naming: outname `rf_c` + bandcnt 3 → `rf_c0.txt rf_c1.txt rf_c2.txt`; outname WITH
  extension `rf_m.txt` → `rf_m0.txt rf_m1.txt` (index inserted before `.txt`; source
  `open_the_outfile`/`create_next_outfile` append index + ".txt"). The argv name itself
  is never created → no single verified output.
- Output content: breakpoint text (time TAB level pairs at tstep intervals; focratio 3 →
  in-focus 1.000000 vs 0.333333 — verified in rf_d0.txt). Consumable by envel-family
  and brk params.
- Seed: `-s5` twice → identical file sets; seedless (default 0, `if(seed>0)srand`)
  1.2 s apart → identical (glibc default state, ≡ seed…1); no clock path.
- Argv note: with defaults, `-o`/`-e` interact — offset 0/end 0 on a 4 s dur refused
  `ERROR: Refocus offset is beyond start of refocus end.` until `-e` ≤ dur set
  explicitly (probes used `-e3.9`).
- Reachable via execute() with cwd control; Phase 6 can harvest `<outname><i>.txt`.

## 7. housekeep chans

Banner: mode 1 extract channo (NO outfile argv), 2 extract ALL, 3 zero one channel,
4 mix to mono, 5 mono→stereo.

- **mode 1 (dropped):** `housekeep chans 1 ev4st.wav 1` → writes `ev4st_c1.wav`
  (INPUT stem + `_c<channo>`) in cwd; no outfile argv slot. Content verified == L,
  sample-exact. Same class as housekeep extract 1.
- **mode 2 (dropped):** `housekeep chans 2 ev4st.wav` → `ev4st_c1.wav` + `ev4st_c2.wav`
  (one per channel, self-named, multi-output).
- **mode 3 (curated):** stereo in, channo 2 → output 2 ch, L bit-equal to input L,
  R all-zero (verified). channo range = input channel count (`(1.000000 to 2.000000)`
  stereo; `(1.000000 to 1.000000)` mono). MONO input accepted with channo 1 → STEREO out,
  ch1 zeroed, mono signal on ch2 — **with a BUG: one sample is dropped to 0.0 every
  16384 frames** (verified zeros at frames 16384/32768/49152/65536/98304 where the
  source is nonzero; stereo input has NO such artifact). Static duration; deterministic.
- **mode 4 (curated):** stereo → mono, verified `(L+R)/2` sample-exact (maxdiff 3e-8);
  `-p` verified `(L−R)/2` exact. Mono input refused `ERROR: CANNOT ACHIEVE TASK: /
  ERROR: This file is already mono!!`. 4-channel input ACCEPTED → mono at sum/2 with
  automatic renormalization when that clips (fit ×0.357 = peak-matched to input peak
  0.7918 on ev4q). Static; deterministic (pair verified).
- **mode 5 (curated):** mono → dual-mono stereo, both channels bit-equal to source
  (verified). Stereo input refused `ERROR: This file is already stereo!!`. Static;
  deterministic (pair verified).

## 8. repair — DROPPED (self-naming even for a single output)

- `repair repair ev4.wav ev4b.wav rp_out.wav 2` → exit 0, writes **`rp_out_0.wav`** —
  the argv name is never created (source `open_the_outfile`: insert `_` + index before
  the extension, index from 0). Even the minimal 2-inputs/channels-2 single-output case
  is renamed → engine-incompatible.
- Content verified: `rp_out_0.wav` = sample-exact interleave (ch1 = infile1,
  ch2 = infile2). 4 inputs + channels 2 → `rp4_0.wav` + `rp4_1.wav` (all ch-1 sources
  listed first: files 0,1 = ch1 of outputs 0,1; files 2,3 = ch2).
- Constraints (verbatim): `ERROR: INVALID CHANNEL COUNT (2,4,5,7,8,16 only)` (3
  refused!); `ERROR: NUMBER OF INPUT FILES IS NOT A MULTIPLE OF 2`;
  `ERROR: FILES 0 AND 1 ARE NOT THE SAME SIZE`; inputs must be mono
  (`File ev4st.wav is not of correct type (must be mono)`).
- The curated stereo-merge path remains **submix interleave**; repair via execute()
  with cwd control for >2-channel merges.

---

## Duration-row confirmations (shared flat-noise fixture semantics)

| row | fixture behavior | pinned |
| --- | ---------------- | ------ |
| retime retime 4 (tempo 120, minsil 50, pregain 1) | WARNING only-1-event, 1.9999773 s from 2.0 | static row, tol 0.05 |
| retime retime 5 (factor 2, minsil 50) | WARNING only-1-event, 1.9999773 s | static row, tol 0.05 |
| sorter sorter 1 (esiz 0.1) | 1.9518 s from 2.0 (−2.4 %) | static row, tol 0.05 |
| sorter sorter 5 (esiz 0.1, seed 5) | element count identical to mode 1 | static row, tol 0.05 |
| housekeep chans 3 (channo 1, mono fixture) | 2.0000 (2 ch out) | static row |
| housekeep chans 5 (mono fixture) | 2.0000 (2 ch out) | static row |
| retime 1/6/7/9, stutter, clicknew | aux datafile the shared fixture cannot supply | row null + reason |
| retime 3/8/9/10 | flat noise refused NO SILENCE-GAPS | row null + reason |
| housekeep chans 4 | stereo-only (mono refused) | row null + reason |
| peakfind, retime 12 | .txt data output — no audio duration | row null + reason |

18 entries shipped; 6 drops recorded (retime 2, retime 11, refocus, repair,
housekeep chans 1, housekeep chans 2).
