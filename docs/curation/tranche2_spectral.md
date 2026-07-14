# Tranche 2 — spectral curation probe transcript

Six SPECTRAL entries curated empirically against real CDP binaries:
`stretch time` (submode 1), `strange glis` (submode 1), `strange invert` (submode 1),
`hilite trace` (submode 1), `spec magnify`, `focus accu`.

## Test environment

- CDP binaries: **built from source at `/tmp/CDP8/NewRelease`** (Linux x86_64 sandbox);
  banners self-identify as "CDP Release 7.1 2016". Findings are to be re-verified on
  macOS r8 by the CDP-gated test suite when these rows are pinned.
- Source tree available at `/tmp/CDP8/dev` — used to explain the analysis-dependent
  glis bound of `focus accu` (see below).
- Probe inputs (generated, 16-bit PCM mono 44.1 kHz, synthetic gliss harmonics + light
  envelope so grabbed windows differ):
  - `in1.wav` 2.000 s, `in3.wav` 3.000 s, `stereo.wav` 1.0 s stereo.
- Analysis: `pvoc anal 1 inN.wav inN.ana` (defaults: 1024 points, overlap 3).
- Output verification: every `.ana` output resynthesised with `pvoc synth out.ana out.wav`;
  durations and sha256 taken from the wav's **decoded data chunk** (headers carry
  timestamps and tick between runs).
- Breakpoint probes: 2-point files (`0 <low>` / `<t_end> <high>`) substituted at the
  parameter's argv position, or attached to the flag (`-X<brk>` — no space), per the
  Phase 2 methodology (`docs/phase-2-breakpoint-review.md`).
- Determinism probes: identical argv twice with `sleep 1.1` between runs (avoids
  same-second clock-seed collisions).

### Channel constraint (shared)

`pvoc anal 1 stereo.wav stereo.ana` → exit 255,
`Application doesn't work with this type of infile.`
Reproduces tranche 1's finding: stereo audio cannot even be analysed, so all six
entries are `channel_constraint: "mono"` at the .ana level (the refusal happens
upstream at PVOC, not in the six programs).

---

## 1. stretch time (submode 1)

Banner: `stretch time 1 infile outfile timestretch` / `stretch time 2 infile timestretch`
— "In mode 2, program calculates length of output, only. Timestretch may itself vary
over time." No range stated. Pinned to submode 1 (mode 2 produces no outfile).

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `stretch time 1 in1.ana st1.ana 2` | 0 | 4.0490 s | `27650d04d35db5fb` |
| `stretch time 1 in1.ana st1b.ana 2` (rerun) | 0 | 4.0490 s | `27650d04d35db5fb` = |
| `stretch time 1 in1.ana st1c.ana 2` (rerun after `sleep 1.1`) | 0 | 4.0490 s | `27650d04d35db5fb` = |
| `stretch time 1 in3.ana st2.ana 2` | 0 | 6.0459 s | indur 3.0 |
| `stretch time 1 in1.ana st3.ana 3.5` | 0 | 7.0879 s | |
| `stretch time 1 in1.ana st4.ana 0.5` | 0 | 1.0101 s | compression |
| `stretch time 1 in1.ana stB.ana b_ts.brk` (`0 1` / `1.9 3`) | 0 | 3.1289 s | brk accepted |
| `stretch time 2 in1.ana 2` | 0 | — | prints `INFO: Length of output file will be 4.052 secs.` |

Range refusals (raw): `stretch time 1 in1.ana stZ.ana 0` → exit 255,
`ERROR: Parameter[1] Value (0.000000) out of range (0.000100 to 10000.000000)`
(same range text for -1).

- **duration_model: expression `indur * timestretch`** — 2.0×2→4.0490 (+1.2%),
  3.0×2→6.0459 (+0.77%), 2.0×3.5→7.0879 (+1.26%), 2.0×0.5→1.0101 (+1.0%); all
  well inside 5% (the residual is the usual analysis-frame pad).
- **breakpoint_capable: timestretch = true** (exit 0, resynthesises; ramp 1→3 over a
  2 s input lands between the endpoints at 3.1289 s, consistent with integrating a
  time-varying stretch).
- **Deterministic** (identical sha ×3, including a >1 s gap).
- **Divergences**: banner states no range; enforced 0.0001–10000 (matches the manual's
  range for the newer SPECTSTR). afta8's max 10 and SoundThread's 0.1–100 slider are
  UI ceilings. Mode 2 is an information-only length calculator (verified: its 4.052 s
  prediction matches the measured 4.0490 s within 0.1%) — a useful preflight, pinned
  out of this entry.

## 2. strange glis (submode 1 — Shepard tones)

Banner: `strange glis 1 infile outfile -fN|-pN [-i] glisrate [-ttopfrq]` — "glisrate
may vary over time." Submodes 2 (inharmonic glide, extra `hzstep`) and 3
(self-glissando) not curated here.

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `strange glis 1 in1.ana sg1.ana -p8 2` | 0 | 2.0230 s | `9c13944626529294` |
| `strange glis 1 in1.ana sg1b/sg1c.ana -p8 2` (sleep 1.1 between) | 0 | 2.0230 s | `9c13944626529294` both |
| `strange glis 1 in3.ana sg2.ana -p8 2` | 0 | 3.0215 s | indur 3.0 |
| `strange glis 1 in1.ana sg3.ana -p8 12` | 0 | 2.0230 s | 2nd glisrate |
| `strange glis 1 in1.ana sg4.ana -f4 2` | 0 | 2.0230 s | -f form ok |
| `strange glis 1 in1.ana sgB2.ana -p8 b_gr.brk` (`0 2` / `1.9 24`) | 0 | 2.0230 s | glisrate brk accepted |
| `strange glis 1 in1.ana sgI.ana -p8 -i 2` | 0 | — | -i ok |
| `strange glis 1 in1.ana sgT.ana -p8 2 -t4000` | 0 | — | topfrq scalar ok |
| `strange glis 1 in1.ana sgP0.ana -p0 2` | 0 | — | **-p0 accepted** |

Refusals (raw):

- no -f/-p: `Formant parameter missing on cmdline.` (exit 255)
- both `-f4 -p8`: `ERROR: Cannot read parameter 1 [-p8]` (exit 255) — the second flag
  is mis-parsed as the glisrate positional; the flags are mutually exclusive.
- `-pb_pn.brk`: `Cannot read count of formant_bands.` (exit 255) — note this is *not*
  the standard `brkpnt_files not permitted` text.
- `-tb_tf.brk`: `ERROR: Cannot read parameter 3 [b_tf.brk]: brkpnt_files not permitted.` (exit 255)

- **duration_model: static** (2.0→2.0230, 3.0→3.0215; glisrate 2 vs 12 same duration).
- **breakpoint_capable: glisrate = true; fchans/pbands = false; topfrq = false.**
- **Deterministic** (identical sha ×3 incl. sleep 1.1).
- **Divergences**: exactly one of -f/-p is required and they are mutually exclusive
  (banner's `-fN|-pN` is accurate but the failure mode with both is a confusing
  mis-parse, not a clean refusal). `-p0` runs clean despite afta8/SoundThread floors
  of 1. afta8's topfrq default of 1000 Hz is a UI seed value; banner/manual say
  default = Nyquist.

## 3. strange invert (submode 1 — normal inversion)

Banner: `strange invert mode infile outfile` — no parameters at all beyond the mode.

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `strange invert 1 in1.ana si1.ana` | 0 | 2.0230 s | `828dd794f9ff7726` |
| `strange invert 1 in1.ana si1b.ana` (rerun after sleep 1.1) | 0 | 2.0230 s | `828dd794f9ff7726` = |
| `strange invert 1 in3.ana si2.ana` | 0 | 3.0215 s | indur 3.0 |
| `strange invert 2 in1.ana si3.ana` | 0 | 2.0230 s | `de692f9b316d538a` ≠ mode 1 |

Output-sanity probe (afta8 carries a "not working properly" warning): resynthesised
mode-1 output RMS −13.6 dBFS vs −12.1 dBFS for the source's plain PVOC round-trip —
non-silent, deterministic, and distinct from submode 2's output.

- **duration_model: static**; **no numeric parameters** → no breakpoint probes apply.
- **Deterministic.**
- **Divergence (advisory)**: afta8's warning that the function "is not working
  properly" is preserved in known_issues; every mechanical probe on this build is
  clean, but perceptual correctness of the inversion is not probeable.

## 4. hilite trace (submode 1)

Banner: `hilite trace 1 infile outfile N` — "N, lofrq and hifrq may vary over time."
Submodes 2–4 (lofrq/hifrq bounds, -r) not curated here.

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `hilite trace 1 in1.ana ht1.ana 10` | 0 | 2.0230 s | `b9a8e250baae1347` |
| `hilite trace 1 in1.ana ht1b.ana 10` (rerun after sleep 1.1) | 0 | 2.0230 s | `b9a8e250baae1347` = |
| `hilite trace 1 in3.ana ht2.ana 10` | 0 | 3.0215 s | indur 3.0 |
| `hilite trace 1 in1.ana ht3.ana 50` | 0 | 2.0230 s | 2nd param value |
| `hilite trace 1 in1.ana htB.ana b_n.brk` (`0 4` / `1.9 40`) | 0 | 2.0230 s | N brk accepted |

Range refusals (raw, both exit 255):

- `N = 0`: `ERROR: Parameter[1] Value (0.000000) out of range (1.000000 to 513.000000)`
- `N = 40000`: `ERROR: Parameter[1] Value (40000.000000) out of range (1.000000 to 513.000000)`

- **duration_model: static**; **breakpoint_capable: n = true**; deterministic.
- **Divergence**: enforced range is 1 to the analysis channel count (513 on a
  1024-point analysis — dynamic, so the JSON pins min=1 and documents the max).
  afta8's 0–32768 is a UI ceiling and its "default 2" a UI seed value (N is a
  required positional). SoundThread's percent-of-window slider is a UI reshaping.

## 5. spec magnify

Banner: `spec magnify infile outfile time dur` — "MAGNIFY A SINGLE ANALYSIS WINDOW,
AT TIME 'TIME', TO DURATION 'DUR'." Manual adds: dur "MUST BE > the analysis window
length".

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `spec magnify in1.ana sm1.ana 0.5 2.0` | 0 | 1.9969 s | `6ceb1ba436af27e3` |
| `spec magnify in1.ana sm1b.ana 0.5 2.0` (rerun after sleep 1.1) | 0 | 1.9969 s | `6ceb1ba436af27e3` = |
| `spec magnify in3.ana sm2.ana 0.5 2.0` | 0 | 1.9969 s | `6ceb1ba436af27e3` **= sm1** |
| `spec magnify in1.ana sm3.ana 0.5 1.0` | 0 | 0.9985 s | |
| `spec magnify in1.ana sm4.ana 0.5 2.5` | 0 | 2.4961 s | |
| `spec magnify in1.ana sm5.ana 1.5 2.0` | 0 | 1.9969 s | `0bded77d2b8e9e65` (time changes content, not dur) |
| `spec magnify in1.ana smE3.ana 0.5 40` | 0 | 39.9964 s | above afta8's 30 s cap |
| `spec magnify in1.ana smE1x.ana 0.5 0.01` | 0 | **0.0000 s** | empty data chunk (`e3b0c44298fc1c14`) |

Refusals (raw, all exit 255):

- time brk: `ERROR: Cannot read parameter 1 [b_time.brk]: brkpnt_files not permitted.`
- dur brk: `ERROR: Cannot read parameter 2 [b_dur.brk]: brkpnt_files not permitted.`
- time beyond end: `ERROR: Parameter[1] Value (5.000000) out of range (0.000000 to 2.025941)`

- **duration_model: set_by `dur`** (−0.16% at 1.0/2.0/2.5 s, −0.01% at 40 s),
  independent of indur — the 2 s and 3 s inputs (which share their first 2 s of
  synthesized content, hence the same window at 0.5 s) give **bit-identical** output.
- **breakpoint_capable: time = false, dur = false** (raw refusals above).
- **Deterministic.**
- **Divergence (manual requirement unenforced)**: dur below the analysis window
  length is accepted with exit 0 and silently yields a .ana that resynthesises to
  ZERO frames — no error, empty audio. `time` is range-enforced to the input's
  analysed duration; afta8's dur max of 30 (and SoundThread's 480) are UI ranges
  (40 s verified clean).

## 6. focus accu

Banner: `focus accu infile outfile [-ddecay] [-gglis]` — decay "Possible Range:
0.001000 to 1.0 : Default 1.0. Suggested Effective Range: 0.001000 to 0.5"; glis
"Approx Range: -11.7 to 11.7 : Default 0". Manual diverges: suggested effective
range "0.000001 to 0.5".

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `focus accu in1.ana fa1.ana -d0.5 -g0.5` | 0 | 2.0230 s | `8f235b7dd384fa34` |
| `focus accu in1.ana fa1b.ana -d0.5 -g0.5` (rerun after sleep 1.1) | 0 | 2.0230 s | `8f235b7dd384fa34` = |
| `focus accu in3.ana fa2.ana -d0.5 -g0.5` | 0 | 3.0215 s | indur 3.0 |
| `focus accu in1.ana fa3.ana -d0.1 -g2` | 0 | 2.0230 s | 2nd param values |
| `focus accu in1.ana fa0.ana` (no flags) | 0 | 2.0230 s | `9cabdc594eabc50e` |
| `focus accu in1.ana faD1.ana -d1` | 0 | 2.0230 s | `9cabdc594eabc50e` **= fa0** |
| `focus accu in1.ana faG0.ana -g0` | 0 | 2.0230 s | `9cabdc594eabc50e` **= fa0** |
| `focus accu in1.ana faDB.ana -db_dec.brk` (`0 0.1` / `1.9 0.9`) | 0 | 2.0230 s | decay brk accepted |
| `focus accu in1.ana faGB.ana -gb_gls.brk` (`0 -0.5` / `1.9 2`) | 0 | 2.0230 s | glis brk accepted |
| `focus accu in1.ana faR5.ana -g-11` | 0 | — | inside banner range |
| `focus accu in1.ana faR4x.ana -g20` | 0 | — | **beyond banner's ±11.7, accepted** |

`.ana` chunk comparison: fa0 / faD1 / faG0 have identical `fmt ` and `data` chunk
hashes (and identical decoded audio) — **default decay = 1.0, default glis = 0,
empirically pinned.**

Range refusals (raw, all exit 255):

- `-d0`: `ERROR: Parameter[1] Value (0.000000) out of range (0.001000 to 1.000000)`
- `-d2`: `ERROR: Parameter[1] Value (2.000000) out of range (0.001000 to 1.000000)`
- `-d0.000001`: exit 255 (the manual's suggested low end is **below the enforced floor**)
- `-g100`: `ERROR: Parameter[2] Value (100.000000) out of range (-21.533204 to 21.533204)`
  (same text for -g-100 and -g1000)

- **duration_model: static**; **breakpoint_capable: decay = true, glis = true**
  (attached to flag, both verified with resynthesised output).
- **Deterministic.**
- **Divergence (manual wrong, banner right, on decay)**: the manual's "Suggested
  effective Range: 0.000001 to 0.5" dips below the enforced 0.001 floor — 0.000001
  is refused. afta8's min of 1e-06 repeats the manual's error; afta8's default of
  0.5 is a UI seed value (true default 1.0, pinned above).
- **Divergence (banner approximate, source explains, on glis)**: banner says
  "Approx Range: -11.7 to 11.7" but -g20 runs and -g100 is refused at ±21.533204.
  Source: `MAXGLISRATE = 0.0625` octaves **per window** (`dev/include/speccon.h:182`);
  the enforced bound is ±0.0625/frametime octaves/sec, which for this default
  1024-point overlap-3 analysis at 44.1 kHz (frame time 128/44100 ≈ 2.9 ms) is
  ±21.53. The bound scales with the analysis frame rate — the JSON leaves min/max
  null and documents the formula.

---

## Headline findings

1. **stretch time's duration model is `indur * timestretch`** (verified at two input
   durations and three stretch values, ≤1.3% error), with an enforced range of
   0.0001–10000 the banner never states. Mode 2 is a pure length calculator whose
   prediction matches the measured output within 0.1% — pinned out of the entry as
   an information mode.
2. **spec magnify silently emits zero-length audio** when dur is at or below the
   analysis window length — the banner/manual's "MUST BE >" is unenforced (exit 0,
   empty data chunk). Its `dur` sets output duration exactly, independent of input
   duration (bit-identical output from 2 s and 3 s inputs sharing window content).
3. **focus accu's manual suggests an unusable decay range**: "0.000001 to 0.5" dips
   below the enforced 0.001 floor (0.000001 refused). The true defaults were pinned
   empirically: decay 1.0 and glis 0 (flag-less, -d1 and -g0 runs bit-identical).
4. **focus accu's glis bound is analysis-dependent**, not the banner's ±11.7:
   enforced at ±0.0625/frametime oct/sec (`MAXGLISRATE`, speccon.h) — ±21.53 on a
   default analysis; -g20 runs clean.
5. **hilite trace's N is enforced 1..channel-count** (513 on a 1024-point analysis);
   afta8's 0–32768 range and "default 2" are UI artifacts.
6. **strange glis requires exactly one of -f/-p**, and supplying both fails as a
   mis-parse (`Cannot read parameter 1 [-p8]`) rather than a clean refusal; its
   formant-band count refuses breakpoints with the non-standard text
   `Cannot read count of formant_bands.`; `-p0` is accepted despite documented
   floors of 1.
7. **strange invert runs clean on this build** despite afta8's "not working
   properly" warning: exit 0, deterministic, static duration, non-silent output
   (−13.6 dBFS) distinct from mode 2's. The warning ships as advisory in
   known_issues, per the tips-never-override-probes rule.
8. **All six are deterministic** — no stochastic process in this tranche
   (every rerun, with ≥1.1 s gaps, produced bit-identical decoded audio).
