# Tranche 9 — second submodes probe transcript

First tranche after commit 728b986 keyed the knowledge index by
`(program, mode, submode)`: every target here is a second (or third) submode of
an already-curated pair, previously blocked by pair keying.

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (built from ComposersDesktop/CDP8 source; Groucho
  programs banner "CDP Release 7.1 2016"; scramble/envspeak/specfnu print no release
  banner), Linux x86_64 sandbox.
- **Inputs:** the tranche-1/2 fixtures in `/tmp/probe` (`n1/n2/n3` enveloped noise,
  `tone1/tone2` 440 Hz sines, `flat2` flat noise, `ct2` click train, `syl2` syllable
  train, `st2` stereo noise, `n1_22k` 22.05 kHz noise) plus fresh tranche-9 fixtures in
  `/tmp/probe9`: `am2/am1` (220 Hz tone, deep 1.5 Hz AM), `sweep2` (100→2000 Hz sweep),
  `t9m_rich2/t9m_rich15` (synth wave 4 ramp, 2.0/1.5 s, for .ana pairs), `t9m_am2`
  (330 Hz deep-AM, PCM_16), `t9_vow2` (110 Hz source with 4 synthetic vowel formants
  at 700/1220/2600/3400 Hz), `t9e_1syl` (single asymmetric burst). `.ana` fixtures via
  `pvoc anal 1` defaults.
- **Methodology:** replicates `docs/curation/tranche2_timedomain.md`. Breakpoint proof =
  brk render differs from BOTH scalar-endpoint renders; determinism pairs launched
  > 1.1 s apart; shas are sha256 of decoded float64 samples; fresh output names per run;
  duration models verified at ≥ 2 input durations. Sibling entries were read first and
  every transferable claim was re-verified per submode, not assumed.

Refusal errors quoted below are verbatim from the binaries.

---

## 1. scramble scramble, submode 9 (INCREASING LEVEL)

Working argv: `scramble scramble 9 am2.wav out.wav 5` — exit 0. Sibling sm10 curated
(tranche 8); everything re-verified independently here.

| probe | result |
| ----- | ------ |
| duration (seed 5): am2/sweep2/n2/tone2/n1/flat2 | 1.9954 / 1.9998 / 1.9997 / 1.9977 / 0.9997 / 1.9999 — static, worst −0.23% (am2) |
| level-sort content (am2): first/last 300 ms RMS | mode 9: 0.028 → 0.537 (rises); mode 10 same fixture: 0.547 → 0.029 (exact mirror); shas differ |
| defaults (trns=0, atten=0): seed 5 vs seed 9 | byte-identical (`fdb3977471700cb3`) — seed inert |
| `-c4 -t3 -a0.5`: seed 5 twice, 1.2 s apart | byte-identical (`361f258961e48fe0`) |
| `-c4 -t3 -a0.5`: seed 5 vs 9 | differ; durations 2.0331 vs 1.9780 (trns re-lengths, ±1.7%/−1.1%) |
| seed 0 vs seed 1 (`-c4 -t3 -a0.5`) | byte-identical (`aba388e9b908e448`) — glibc srand(0)≡srand(1) |
| bare `5` vs `5 -c1 -t0 -a0` | byte-identical — rendered defaults equivalence |
| `-c1` vs `-c20` | differ (cnt live); `-a0.5 -c2` runs (flags NOT order-enforced) |

**Ranges (verbatim refusals):** seed 257 / −1 →
`ERROR: Parameter[1] Value (257.000000) out of range (0.000000 to 256.000000)`;
cnt `-c0`/`-c257` → `Parameter[2] ... out of range (1.000000 to 256.000000)`;
trns `-t13` → `Parameter[3] ... (0.000000 to 12.000000)`; atten `-a1.5` →
`Parameter[4] ... (0.000000 to 1.000000)`. Seed omitted →
`Insufficient parameters on command line.` (no unseeded path).

**Breakpoints:** trns brk (0→3) exit 0, differs from both scalar endpoints at the same
seed → **capable**; atten brk (0→0.8) → **capable**; cnt →
`ERROR: Cannot read parameter 3 [b9_cn.brk]: brkpnt_files not permitted.`; seed →
`ERROR: Cannot read parameter 2 [b9_sd.brk]: brkpnt_files not permitted.`

**Channels:** stereo refused: `ERROR: INVALID DATA` /
`ERROR: File /tmp/probe/st2.wav is not of correct type (must be mono)` → `mono`.

## 2. filter bank, submodes 5 and 6 (equal-interval banks)

Working argv: `filter bank 5 n2.wav out.wav 50 5 200 4000 8` and
`filter bank 6 n2.wav out.wav 50 5 200 4000 3` — exit 0, 3.0000 s from 2 s input
(the sibling's undocumented tail default 1.0 re-verified in both submodes).

**FLTBANKN source question answered (task item):** `ap_filter.c:870` maps the
command-line mode `bank` to `FLTBANKN` for **all six** bank modes, and
`filters0.c:92` `case(FLTBANKN): do_norm = 1;` is unconditional — the normalization
pre-pass containing the pre-11cdcb4 OOB heap write runs in modes 4–6 exactly as in
1–3 (`INFO: Assessing input level.` visible in every mode-5/6 run). The
binary-vintage hang warning therefore carries to the new entries verbatim;
`version_sensitive: true` on both.

| probe (per mode) | mode 5 | mode 6 |
| --- | --- | --- |
| n1 no `-t` | 2.0000 | 2.0000 |
| n2 `-t0.5` | 2.5000 | 2.5000 |
| n2 `-t2` | 4.0000 | 4.0000 |
| n1 `-t2` | 3.0000 | 3.0000 |
| n2 `-t0` (tail-0 bug) | **262144 f / 5.9443 s** | **262144 f / 5.9443 s** |
| Q brk 5→500 vs scalar endpoints | differs from both → capable | differs from both → capable |
| scat 0 determinism (1.2 s apart) | identical | identical |
| `-s0.5` twice 1.2 s apart | **differ** (unseeded stochastic) | **differ** |
| `-d` | changes render, duration unchanged | same |
| stereo | accepted, 2 ch, 3.0 s | accepted, 2 ch, 3.0 s |
| hif < lof (4000 200) | **byte-identical to (200 4000)** — silent swap | same |

- **duration_model `indur + tail`** — sample-exact in both submodes; entry pins
  tail = 1.0 explicitly (as sibling).
- **HEADLINE DIVERGENCE (mode 5 spacing):** SoundThread's filter_bank_5 help says the
  filters are "spaced equally in Hz" ("Filter Bank: Linear... more discordant... will
  not align to uniform harmonic intervals"). The source says otherwise:
  `fltprepro.c:124` `frq[n] = lof * (hif/lof)^(n / filtcnt)` — **geometric spacing
  (equal pitch intervals)**. Verified twice: `filter bankfrqs 5 ... 200 4000 8` prints
  200, 290.84, 422.95, 615.06, 894.43, 1300.69, 1891.48, 2750.62 (ratio 1.4542 =
  20^(1/8) per step) and FFT peaks of the rendered audio match. Note the divisor is
  `filtcnt`, not `filtcnt−1`: the **top filter sits one step below hif** (2750.6, not
  4000) — hif is never itself a filter.
- Mode 6 verified against source (`fltprepro.c:128-130`: frq[0]=lof, ×2^(interval/12)
  while < hif) and `bankfrqs 6 ... 200 4000 3` → 18 filters 200 … 3805.46; the
  ceiling is likewise never reached.
- **Ranges (verbatim):** Q 0.0005 → `Parameter[1] Value (0.000500) out of range
  (0.001000 to 10000.000000)`; gain 0 → `Parameter[2] ... (0.001000 to 10000.000000)`;
  lof 0 / −5 → `Parameter[3] ... (0.100000 to 22050.000000)`; hif 30000 →
  `Parameter[4] ... (0.100000 to 22050.000000)`; **filtcnt (mode 5)** 0 / 5000 →
  `Parameter[5] ... out of range (1.000000 to 2000.000000)` (1 accepted — a single
  resonator; 8.5 accepted and byte-equals 9 → **rounded**); **interval (mode 6)**
  0 / 0.05 / 130 → `Parameter[5] ... out of range (0.250000 to 96.000000)` (0.5
  accepted); tail `-t25` → `Parameter[6] ... (0.000000 to 20.000000)`; scat `-s2` →
  `Parameter[7] ... (0.000000 to 1.000000)`.
- **Breakpoints (all but Q refused, both modes probed):** gain →
  `Cannot read parameter 2 [...]`; lof → `parameter 3`; hif → `parameter 4`;
  filtcnt/interval → `parameter 5`; tail → `parameter 6`; scat → `parameter 7`
  (all `brkpnt_files not permitted.`).
- Silent lof/hif swap source-confirmed: `fltpcon.c` setup_internal_fltbankn_params
  "correct inverted frq range".

## 3. morph bridge, submodes 2 (MINIMUM) and 3 (FOLLOW INFILE1)

Working argv: `morph bridge 2|3 in1.ana in2.ana out.ana` — exit 0. Fixtures:
tone2/rich2 (2.0 s), rich15 (1.5 s), am2b (2.0 s deep-AM, PCM_16). Durations via
pvoc synth round-trips.

**HEADLINE: the duration rules diverge from curated sm1 per mode.** Mode 1 sanity on
the same fixtures reproduces sm1's model exactly (`(rich15, tone2)` → 2.0230 = indur2;
`-a0.5` → 2.5223 = offset + indur2), so the divergence is real:

| probe | mode 2 | mode 3 | sm1 (sanity) |
| --- | --- | --- | --- |
| (2.0, 1.5) defaults | 1.5209 | 1.5209 | — |
| (1.5, 2.0) defaults | **1.5209** | **1.5209** | 2.0230 |
| (2.0, 2.0) `-a0.5` | **1.5238** | **2.0230** | 2.5223 |
| (2.0, 2.0) `-a1.0` | 1.0217 | 2.0230 | — |
| (2.0, 2.0) `-a1.5` | 0.5224 | — | — |
| (2.0, 1.5) `-a0.5` | 1.5209 | — | — |
| `-d0.8 -e0.8` both orders | 1.5209 | 1.5209 | 1.5209 (min) |
| (1.5, 2.0) `-a0.5 -d0.8` | 1.0217 | 1.5209 | — |

- **mode 2 duration = `min(indur1 − offset, indur2)`** — offset SUBTRACTS (the
  pre-entry stretch is dropped); ef2/ea2 irrelevant. Curated expr
  `((indur1 - offset) if (indur1 - offset) < indur2 else indur2)`; predictions carry a
  +1-window quantisation (~0.006–0.023 s), so relative error grows as
  `indur1 − offset → 0` (documented).
- **mode 3 duration = `min(indur1, indur2)`** — offset changes the CONTENT (shas
  differ for −a0/−a0.5/−a1.0) but never the length. Curated expr `indur_min`.
- **Level-rule content proof** (in1 = steady rich2, in2 = deep-AM am2b; RMS at in2's
  envelope peak/trough): mode 1 = 0.214/0.104; mode 2 = 0.125/**0.0004** (min ducks
  to silence); mode 3 = 0.313/**0.408** (follows steady in1); mode 4 = mode 2 on this
  pair. Swapped pair (in1 = deep-AM): **modes 2 and 3 render byte-identical**
  (min == amp1 when infile1 is everywhere quieter) — recorded in both entries.
- **Breakpoints:** all seven flags refused in BOTH submodes —
  `ERROR: Cannot read parameter N [b9_mb.brk]: brkpnt_files not permitted.`, N = 1–7
  (-a/-b/-c/-d/-e/-f/-g).
- **Ranges (spot re-verified):** `-a3` → `Parameter[1] Value (3.000000) out of range
  (0.000000 to 2.020136)` (runtime = indur1); `-b1.5` → `Parameter[2] ...
  (0.000000 to 1.000000)`; `-e-0.5` → `Parameter[5] ... (0.000000 to 1.000000)`;
  `-g3` → `Parameter[7] ... out of range (0.005805 to 2.025941)`.
- **NEW COMPAT AXIS (organic find):** a float-source .ana against a PCM-source .ana
  refuses `ERROR: INVALID DATA` / `ERROR: Incompatible original-sample-type in input
  file t9m_am2.ana.` — beyond sm1's analysis-sample-rate rule. Wav input refused
  (`Application doesn't work with this type of infile.`).
- Determinism: both modes identical resyntheses 1.2 s apart.

## 4. modify radical — choosing and probing two more modes

Banner survey: 1 REVERSE (curated), 2 SHRED, 3 SCRUB, 4 LOSE RESOLUTION,
5 RING MODULATE, 6 CROSS MODULATE (2 inputs), 7 QUANTISE. SoundThread's help covers
radical 1/3/4/5/6 (NOT 2); afta8 covers all including 2 (Shred). **Chosen: 5 (ring
modulate — ST+afta8, the most musically distinct single-input transform) and 2 (shred
— afta8-covered, the classic CDP glitch process; scrub 3 is another clock-seeded
stochastic and lose-resolution 4 duplicates ubiquitous bitcrushers).**

### 4a. modify radical 5 (RING MODULATE)

Working argv: `modify radical 5 tone2.wav out.wav 100` — exit 0.

- **duration_model `static` — sample-exact** (tone2/tone1/n2 88200/44100/88200 f;
  stereo 88200 f 2 ch).
- **Content:** 440 Hz ⊗ 100 Hz → FFT top bins exactly 340 + 540 Hz; residual energy at
  440 Hz = 0.0000 of peak. Textbook carrier-suppressed ring mod.
- **Breakpoint:** modfrq brk (50→500) exit 0 and differs from both scalar endpoint
  renders → **capable**.
- **Ranges (verbatim):** 0 / −50 / 30000 → `ERROR: Parameter[1] Value (...) out of
  range (0.100000 to 22050.000000)`; on the 22.05 kHz fixture 12000 →
  `... out of range (0.100000 to 11025.000000)` — **upper bound = Nyquist,
  input-dependent**.
- Deterministic (1.2 s apart identical). Stereo accepted → `any`.

### 4b. modify radical 2 (SHRED)

Working argv: `modify radical 2 n2.wav out.wav 3 0.1` — exit 0.

- **duration_model `static` — sample-exact** (n2/n1/tone2 exact; stereo exact).
- **CLOCK-SEEDED STOCHASTIC, NO SEED (first-class):** two runs 1.2 s apart differ;
  two runs in the SAME second byte-identical (collision trap verified). Source:
  `shred_pconsistency` (dev/modify/radical.c:395) calls `initrand48()` =
  `srand(time(0))` (osbind.c:334). No seed argv slot exists. (Scrub, radical.c:1030,
  has the same construction — recorded for future curation.)
- **scatter 0 is still stochastic:** banner's "reorders without shredding" is a random
  permutation — 1.2 s-apart `-s0` runs differ.
- **Ranges (verbatim):** repeats 0 / −1 → `Parameter[1] ... out of range (1.000000 to
  10000.000000)` (5001 accepted; afta8's 0–1000 advisory); chunklen 0 / 3 / 0.0001 on
  2 s → `Parameter[2] ... out of range (0.017415 to 0.999998)`; on 1 s the max quotes
  `0.499998` → **floor 768 samples (srate-dependent), max = indur/2, input-dependent**;
  scatter `-s-1`/`-s100`/`-s9` → `Parameter[3] ... out of range (0.000000 to 8.000000)`
  — **hard cap 8 diverges from the banner's "0 to K" and afta8's 0–10** — PLUS the
  runtime rule (chunklen 0.5, `-s7`, K = 4): `ERROR: INVALID DATA` /
  `ERROR: Scatter value cannot be greater than infileduration/chunklength.`
  (`-s8` at K = 20 accepted.)
- **Breakpoints:** repeats / chunklen / scatter →
  `Cannot read parameter 1|2|3 [...]: brkpnt_files not permitted.`
- `-n` accepted (duration unchanged; A/B against identical cuts impossible —
  clock-seeded).
- **Stereo:** accepted; dual-mono input → output channels correlation 1.0000 with 85%
  of samples bit-identical (differences confined to splice boundaries) — **cuts are
  shared across channels; the image survives**.

## 5. modify speed, submode 5 (ACCEL/DECEL)

Working argv: `modify speed 5 tone2.wav out.wav 2 1.0 [-s0.5]` — exit 0.

**Mechanism (source):** `strans.c:104` converts accel to a per-output-sample ratio
`pow(accel, 1/(acceltime*srate))` with `acceltime = goaltime − starttime`;
`do_acceleration` multiplies the read increment by it every output sample — the speed
is **exponential in output time**, reaching accel exactly at goaltime and continuing
beyond. For accel < 1 the increment can hit `MININC` = 0.002 (strans.c:50) before the
input is exhausted: `INFO: Acceleration reached black hole! - finishing` — **the rest
of the input is discarded** (verified: accel 0.5/goal 1 on 2 s consumes ~1.44 s of
source).

Closed form fitted (ln approximated arithmetically as `10000*(x**0.0001 − 1)` for the
functions-free expression language; approximation error ≤ 0.005%):

| accel | goaltime | starttime | indur | predicted | measured | err |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 1.0 | 0 | 2.0 | 1.2548 | 1.2548 | 0.001% |
| 2 | 0.5 | 0 | 2.0 | 0.9578 | 0.9578 | 0.003% |
| 2 | 2.0 | 0 | 2.0 | 1.5194 | 1.5194 | 0.003% |
| 4 | 1.0 | 0 | 2.0 | 0.9578 | 0.9578 | 0.001% |
| 0.5 | 1.0 | 0 | 2.0 | 8.9633 | 8.9658 | 0.028% (black hole) |
| 2 | 1.0 | 0 | 1.0 | 0.7597 | 0.7597 | 0.003% |
| 2 | 1.0 | 0.5 | 2.0 | 1.3114 | 1.3113 | 0.005% |
| 0.25 | 2.0 | 0 | 2.0 | 8.9636 | 8.9658 | 0.024% (black hole) |
| 0.8 | 1.0 | 0 | 2.0 | 2.6489 | 2.6490 | 0.003% (decel, exhausts input) |
| 3 | 0.5 | 0 | 1.0 | 0.5290 | 0.5290 | 0.001% |
| 1.5 | 0.3 | 0 | 2.0 | 0.9687 | 0.9687 | 0.000% |
| 1 | 1.0 | 0 | 2.0 | 2.0000 | 2.0000 | 0.000% (passthrough, 1 frame short) |

Worst error 0.028% — model shipped as the curated expression (verified to evaluate
under the repo's SimpleEval with `functions={}`).

- **Ranges (verbatim):** accel 0 / −2 → `Parameter[1] ... out of range (0.000100 to
  1000.000000)` (1000 accepted); goaltime 0 / −1 / 10 on 2 s → `Parameter[2] ... out
  of range (0.010000 to 2.000000)` (**max = indur, input-dependent**); starttime
  `-s-0.5`/`-s3` → `Parameter[3] ... out of range (0.000000 to 1.990000)`.
  goaltime == starttime → `ERROR: INVALID DATA` / `ERROR: time for acceleration
  (0.000000) must be greater than  0.010secs` (MINTIME_ACCEL, modicon.h:103).
- **Breakpoints:** accel / goaltime / starttime →
  `Cannot read parameter 1|2|3 [...]: brkpnt_files not permitted.`
- Deterministic (1.2 s apart identical). Stereo accepted (1.2548 s, 2 ch — matches
  the mono prediction exactly).

## 6. envspeak envspeak, submode 2 (REVERSE-REPEAT)

Working argv: `envspeak envspeak 2 syl2.wav out.wav 50 15 0` — exit 0. Mode-2 argv has
NO repet and NO rand slot.

| input | args | outdur | ×indur |
| --- | --- | --- | --- |
| syl2 (2.0) | 50 15 0 | 4.0000 | 2.000 |
| flat2 | 50 15 0 | 4.0000 | 2.000 |
| ct2 | 50 15 0 | 4.0000 | 2.000 |
| am2 | 50 15 0 | 4.0000 | 2.000 |
| st2 (stereo) | 50 15 0 | 4.0000 (2 ch) | 2.000 |
| syl2 | 15 5 0 | 3.9930 | 1.997 |
| syl2 | 50 15 1 | 3.9500 | 1.975 (offset shortens) |
| t9e_1syl (1.2) | 50 15 0 | 2.4000 | 2.000 |

- **duration_model `expression: indur * 2`** — exact at offset 0 across five fixtures
  including stereo; −0.18% at wsize 15/splice 5; offset > 0 under-runs the model (safe
  direction).
- **Content proof:** on the single asymmetric burst, the output contains a
  sample-exact time-reversed copy of the forward event — cross-correlation of the
  reversed segment at the located match = **1.000**.
- **DETERMINISTIC** (unlike sm1's rand path): no rand parameter exists in this mode;
  two runs 1.2 s apart byte-identical.
- **Ranges (verbatim):** wsize 4 / 1001 → `Parameter[1] ... out of range (5.000000 to
  1000.000000)`; splice 1 / 101 → `Parameter[2] ... (2.000000 to 100.000000)`; offset
  −1 / 101 → `Parameter[3] ... (0.000000 to 100.000000)`.
- **OFFSET RUNTIME CONSTRAINT (new vs sm1):** offset 2 on syl2 at wsize 50 (4 peaks
  found) → `ERROR: INVALID DATA` / `ERROR: ERROR: Offset (2) too large for number of
  peaks found (4).` (CDP's doubled "ERROR:" verbatim); offset 1 runs, and offset 2
  passes at wsize 15 (more peaks).
- **CONTENT REFUSAL (as sm1):** tone2 → `ERROR: FAILED TO FIND ANY ENVELOPE TROUGHS
  IN THE FILE.`
- **Breakpoints:** wsize / splice / offset →
  `Cannot read parameter 1|2|3 [...]: brkpnt_files not permitted.` (no time-variable
  parameter in this mode). Stereo accepted → `any`.

## 7. synth wave, submodes 2 (SQUARE) and 4 (RAMP)

Working argv: `synth wave 2|4 out.wav 44100 1 2.0 440 [-a] [-t]` — exit 0
(arity-0 generators).

- **Waveform identity verified numerically** (100 Hz, one cycle sampled at 9 points):
  mode 2 = **square** (+1 half-cycle, −1 half-cycle, single interpolated sample at
  each edge: 1.0, 1.0, 1.0, 1.0, −0.419, −1.0, −1.0, −1.0, −1.0); mode 3 = triangle
  (sibling's banner-bug re-confirmed in passing); mode 4 = **DESCENDING ramp/sawtooth**
  (1.0, 0.75, 0.50, 0.25, 0.0, −0.25, −0.50, −0.75, −1.0 — starts at +1, falls
  linearly to −1; afta8 labels it 'Ramp (sawtooth)').
- **duration `set_by dur`** — sample-exact both modes (2.0 → 88200 f, 0.7 → 30870 f).
- **Breakpoints (both modes):** frq brk (220→880) exit 0, differs from both endpoint
  renders → **capable**; amp brk (0.001→1) exit 0, differs from the constant render,
  RMS ramp verified (mode 2 first/last 100 ms 0.0585/0.9792; mode 4 0.0338/0.5660 —
  the latter = 1/√3 of full scale, as a ramp should be) → **capable**. `-a1` ==
  flag-less byte-identical (default amp 1.0 pinned, both modes).
- **TABSIZE QUIRK (first-class):** `-t4096` changes mode 2's render but is
  **byte-identical to the default in mode 4** — linear table interpolation reproduces
  a linear ramp exactly; the parameter is provably inert for the ramp waveform.
- **Ranges (verbatim, probed in mode 2):** srate 11025 → `Parameter[1] Value
  (11025.000000) out of range (16000.000000 to 192000.000000)`; srate 192000 (in
  quoted range) → `ERROR: INVALID DATA` / `ERROR: Invalid sample rate.` (discrete set
  as sibling); chans 17 → `Parameter[2] ... (1.000000 to 16.000000)`; dur 0.039 →
  `Parameter[3] ... (0.040000 to 7200.000000)`; frq 0.05 / 23000 → `Parameter[4] ...
  (0.100000 to 22000.000000)`; tabsize `-t3`/`-t100000` → `Parameter[6] ...
  (256.000000 to 4096.000000)`.
- **Aliasing:** 12 kHz at srate 22050 accepted silently in BOTH modes (exit 0, output
  written). `-a0` accepted, renders digital silence (−inf dBFS).
- Multi-channel = dual-mono (channels bit-identical, both modes). Deterministic
  (1.2 s apart byte-identical, both modes).

## 8. specfnu specfnu, submode 2 (SQUEEZE SPECTRUM)

Working argv: `specfnu specfnu 2 in.ana out.ana 4 1 [-ggain] [-t] [-f] [-s] [-x|-k]
[-r]` — exit 0 (with the family's usual `WARNING: failed to write PEAK data` on every
run, success included). Tranche-3 survey findings reused as priors (mode 2 probed
clean there at −19.5 dBFS; mode 19 teardown crash avoided).

| probe | result |
| --- | --- |
| duration | 2.0 → 2.0230 s; 3.0 → 3.0215 s; squeeze 1 vs 8 same duration → static |
| determinism | identical resyntheses 1.2 s apart |
| squeeze brk (1→8) | exit 0, differs from both scalar endpoints → **capable** |
| `-g1` vs flag-less | bit-identical → default gain 1.0 pinned |
| flags -t/-f/-s/-x/-k/-r each alone | all exit 0; -t and -x and -k and -r change output (−11.2/−15.7…/−41.8 dBFS); **-f bit-identical to base**; **-s bit-identical on both probe sources** |

**HEADLINE BINARY BUG — `centre` is a no-op in peak mode on pitched material:**

- Empirical: on `t9_vow2` (4 synthetic formants; `specfnu specfnu 21` confirms all
  four peaks are detected per window) **centre 1, 2, 3, 4 and 2.5 render
  byte-identical** at squeeze 6 and 10; the spectral centroid collapses to 334 Hz
  (the fundamental region) for centre 1 AND centre 4. Same on the harmonic-rich ramp
  source.
- With `-t` (squeeze around the trough above peak N): **centre 1 vs 3 differ** —
  the parameter is parsed and live in trough mode.
- On unpitched material (noise .ana): **centre 1 vs 4 differ** without -t.
- Source diagnosis: `specfnu.c` `case(F_SQUEEZE)` consistency code carefully gates
  fundamental-tracking (`-f` only with centre 1, warning otherwise) **and then
  unconditionally executes `dz->fundamental = 1;` (line 3468)**, clobbering the
  gating; `formants_squeeze()` (line 3787) then replaces the located formant-peak
  channel with the fundamental's channel whenever the window is pitched
  (`if(get_fundamental) { ... centre = newcc; }`). Consequences: centre inert in
  peak mode on pitched sources, and `-f` is meaningless (always effectively on) —
  matching the bit-identical probes. The binary even prints
  `WARNING: Cannot "Track Fundamental" if not squeezing around 1st formant:
  Ignoring.` for `-f` with centre > 1 — and overrides anyway.
- Entry ships with the bug pinned in known_issues, centre documented as
  trough-mode/unpitched-only, and musical_use built around what the binary actually
  does (root-ward spectral collapse).

**Ranges (verbatim):** squeeze 0.5 / 20 → `ERROR: Parameter[1] Value (...) out of
range (1.000000 to 10.000000)`; centre 0 / 5 → `Parameter[2] ... (1.000000 to
4.000000)` (2.5 accepted — fractional int slot); `-g0`/`-g100` → `Parameter[3] ...
(0.010000 to 10.000000)`. centre brk → `Cannot read parameter 2 [...]`; gain brk →
`Cannot read parameter 3 [...]` (both `brkpnt_files not permitted.`). `-x -k`
together → `ERROR: SUPPRESS NON-HARMONICS WITH SUPPRESS-HARMONICS WILL PRODUCE ZERO
SIGNAL LEVEL.` Wav input → `ERROR: File ... is not of correct type`.

**Incidental family finding:** `specfnu specfnu 21` (SEE SPEC PEAKS/TROFS) wrote its
complete, correct textfile and then **aborted (core dump)** at teardown on this build
— a second broken-exit-contract mode alongside the known mode 19.

---

## Drops

None. All ten targets (twelve entries) probed clean enough to ship. The two
modify radical picks and their rationale are recorded in §4; modes 3 (scrub — another
`initrand48()` clock-seeded stochastic, radical.c:1030), 4, 6, 7 remain for later
tranches.

## Final row confirmations (exact pinned params)

| row | predicted | actual | rel err |
| --- | --- | --- | --- |
| scramble scramble 9 (static), seed 5, flat2 indur 2.0 | 2.0 | 1.9999 | 0.005% |
| filter bank 5, q 50/gain 5/lof 200/hif 4000/filtcnt 8/tail 1.0, indur 2.0 | 3.0 | 3.0000 | 0.000% |
| filter bank 6, q 50/gain 5/lof 200/hif 4000/interval 3/tail 1.0, indur 2.0 | 3.0 | 3.0000 | 0.000% |
| morph bridge 2, defaults, (2.0230, 2.0230) | 2.0230 (min − 0) | 2.0230 | 0.000% |
| morph bridge 3, defaults, (2.0230, 2.0230) | 2.0230 (min) | 2.0230 | 0.000% |
| modify radical 5 (static), modfrq 440, indur 2.0 | 2.0 | 2.0000 | 0.000% |
| modify radical 2 (static), repeats 3/chunklen 0.1, indur 2.0 | 2.0 | 2.0000 | 0.000% |
| modify speed 5, accel 2/goaltime 1.0, indur 2.0 | 1.2548 | 1.2548 | 0.001% |
| envspeak envspeak 2, 50/15/0, indur 2.0 (flat2) | 4.0 | 4.0000 | 0.000% |
| synth wave 2 (set_by dur), dur 2.0 | 2.0 | 2.0000 | 0.000% |
| synth wave 4 (set_by dur), dur 2.0 | 2.0 | 2.0000 | 0.000% |
| specfnu specfnu 2 (static), squeeze 4/centre 1, indur 2.0 | 2.0230 | 2.0230 | 0.000% |

Engine spot-check (process_impl with `submode=`, real binaries): filter bank 5 →
3.0000 s (entry-pinned tail default emitted); modify speed 5 → 1.2548 s (matches the
curated expression); scramble 9 → 2.0764 s (static + trns drift), all `status: ok`.
Loader: 90 curated entries, zero malformed-entry warnings.

All twelve entries shipped; none dropped.
