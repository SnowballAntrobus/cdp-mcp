# Tranche 12 — submix depth probe transcript (2026-07-16)

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (fresh ComposersDesktop/CDP8 clone, banner
  "CDP Release 7.1 2016") — **Linux aarch64 sandbox this wave**, see the
  substrate finding below. Findings re-verified on macOS r8 by the CDP-gated
  suite after integration.
- **Inputs:** synthesized in `/tmp/probe12a` via python-soundfile (PCM_16,
  44100 Hz): mono enveloped noise `n1` (1.0 s), `n2` (2.0 s), `n3` (3.0 s),
  `m1` (1.5 s); 440/660 Hz tones `tone1/tone2/tone3`; burst trains `p2`
  (4 attacks / 2 s), `p15` (3 / 1.5 s); stereo `st2` (2.0 s), `st1` (1.0 s);
  near-full-scale `loud1` (1.0 s); `n1_22k` (22050 Hz, for SR probes).
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. Determinism
  = sha256 of decoded float64 samples (audio) or byte-compare (text outputs),
  pairs > 1.1 s apart; same-second collision probes via parallel launch.
  Breakpoint proof = brk render differs from BOTH scalar-endpoint renders.
  Fresh output names throughout. Refusals quoted verbatim (exit 255 unless
  noted).

## SUBSTRATE FINDING (first-class, environment not CDP): ARM unsigned `char` breaks every CDP textfile input

On this aarch64 sandbox the stock CDP8 build refused EVERY text input file —
mixfiles, sndfile lists, `submix test`, `submix mix` itself — with
`ERROR: INVALID DATA / ERROR: <name> is not a valid CDP file`. Source-diagnosed:
`dev/cdparse/cdparse_other.c initial_parse_textfile()` reads
`while((c = (char)fgetc(fp)) != EOF)` and then requires
`isalnum(c) || ispunct(c) || isspace(c)`. On AArch64 Linux `char` is
**unsigned**, so `(char)fgetc()` can never equal `EOF` (-1); at end-of-file the
byte 0xFF fails the character-class test and the parse aborts. x86_64 (all
prior tranches) and macOS (signed `char` on both Apple ABIs) are unaffected.
**Fix used:** a parallel CMake build with `-DCMAKE_C_FLAGS=-fsigned-char`
(no source patches), deployed to the same `NewRelease`. All audio-path findings
probed before the rebuild were re-verified BYTE-IDENTICAL on the signed-char
binaries (merge/balance/crossfade/mergemany/faders shas match). Recorded for
any future Linux-ARM substrate work.

## Curation decision rule (pinned for this tranche)

Most submix modes are mixfile TEXT transforms. An entry was curated only where
CDP adds value beyond text editing the model can do natively via
`write_data_file()`:

1. **Audio renderers** (merge, balance, crossfade 1/2, mergemany, faders).
2. **Audio-measuring generators** (getlevel 3; sync 1/2 and syncattack read
   durations/attacks from the soundfiles on disk).
3. **Stochastic munging** (timewarp 6, shuffle 3, spacewarp 5 — seeded jitter
   preserving mixfile validity; all clock-seeded).
4. **dB-aware / trajectory-aware rewrites** (attenuate — correct dB→linear
   conversion + line-range group fader; pan — the family's only time-varying
   parameter, event-start trajectory sampling).

Deterministic text arithmetic (dummy, atstep, ongrid, addtomix, model, the
other timewarp/shuffle/spacewarp submodes) is dropped or left to execute(),
with probe evidence below.

---

## 1. submix merge — SHIPPED

Working argv: `submix merge n1.wav n2.wav out.wav [-s][-j][-k][-b][-e]`.

| in1 | in2 | flags | outdur | predicted max(indur1, stagger+indur2−skip) |
| --- | --- | ----- | ------ | ---- |
| n1 1.0 | n2 2.0 | — | 2.000000 | 2.0 |
| n2 2.0 | n1 1.0 | — | 2.000000 | 2.0 |
| n1 | n2 | -s0.5 | 2.499229 | 2.5 |
| n1 | n2 | -j0.5 | 1.500771 | 1.5 |
| n2 | n1 | -s1.5 | 2.497687 | 2.5 |
| n1 | n2 | -b0.25 -e1.5 | 1.250385 | end−begin = 1.25 |

- **duration_model:** `max(indur1, stagger + indur2 - skip)`, quantised DOWN to
  sector granularity (0–11 ms under prediction; banner documents ~1/100 s).
- **Levels:** default output == `0.5*in1 + 0.5*in2` to 1 LSB (verified).
  skew gains = `skew/(skew+1)`, `1/(skew+1)` — source formula
  (`mixprepro.c` MIX2_GAIN1/2), verified exactly at skew 2 (0.6667/0.3333) and
  skew 9 (0.9000/0.1000). Gains sum to 1 ⇒ **cannot overload**.
- **HEADLINE — stereo requires explicit `-e` (LP64 int-overflow, source-diagnosed):**
  ANY stereo pair (even the same file twice) refuses
  `ERROR: INVALID DATA / ERROR: Mix cuts off before 2nd file enters` with no
  flags. `mixprepro.c mixtwo_preprocess()`: default end = 32767 s
  (`tklib1.c:2002`), `round(32767*44100)*channels` into a 32-bit `iparam` —
  mono just fits (1.445e9 < INT_MAX), stereo doubles past INT_MAX and wraps
  negative, tripping `MIX_DURA <= MIX_STAGGER`. The `>= LONG_MAX` guard never
  fires on LP64 (long is 64-bit). `-e2.0` unblocks (verified 2.0 s stereo).
  Entry `version_sensitive: true`.
- **`_temp.wav` pollution:** mono+stereo triggers
  `INFO: Files have different channel count. Converting to stereo.` via
  `_temp.wav` in the CWD. Success path cleans up (verified); the FAILED path
  (no `-e`) leaves it, and the next mixed-channel run refuses
  `ERROR: Cannot open output file '_temp': Can't create SFile, already exists`.
- **Ranges (verbatim):** stagger `(0.000000 to 1.000000)` on a 1 s first file —
  input-dependent 0..indur1 (`-s1.5` runs with n2 first); skip quoted
  `(0.000000 to 32767.000000)` with runtime
  `SKIP INTO 2ND FILE exceeds length of that file: cannot proceed` at 3.0 on a
  2 s file; skew `(0.000031 to 32767.000000)` (0 and −0.5 refused); begin/end
  `(0.000000 to 32767.000000)`; `-b1.2` on 1 s first file →
  `Mix does not start until first file has ended.`
- **Breakpoints:** all five refused (`Cannot read parameter N ...
  brkpnt_files not permitted.`, N = 1–5).
- **Determinism:** identical decoded shas 1.2 s apart. `-s0 -j0 -k1 -b0`
  byte-identical to flag-less (rendered-defaults equivalence).
- SR mismatch refused: `Different sample-rates in input files: can't proceed.`

## 2. submix balance — SHIPPED

Working argv: `submix balance n1.wav n2.wav out.wav [-k][-b][-e]`.

- **duration = indur1 exactly** (1s+2s → 1.0; 2s+1s → 2.0). `-b0.5 -e1.5` →
  1.0 = end−begin.
- **Gains:** least-squares recovery: default k → 0.5000/0.5000; `-k0.7` →
  0.7000/0.3000. Complementary (sum 1) ⇒ overload-safe. Stereo pair verified
  0.5/0.5 per channel; file-2 tail past indur1 discarded; file-2 shorter →
  balance*file1 continues.
- **balance breakpoint-capable (proof):** `-k` brk 0→1 sha `84a1c1c8…` differs
  from BOTH `-k0` (`f0732e03…`) and `-k1` (`8db8f7df…`). Range 0–1 verbatim.
- **HEADLINE — mixed channel counts corrupt (banner divergence):** banner says
  "files may or may not have different number of channels"; binary neither
  converts nor refuses: n2(2 s mono)+st1(1 s stereo) → **4.0 s mono
  channel-interleave garbage** (no INFO/ERROR); n1(1 s mono)+st2(2 s stereo) →
  2.0 s mono whose tail matches nothing (gain vs mono-mixed st2 = −0.008).
  Equal counts verified clean. Entry requires matching channels.
- begin/end refuse brks (parameters 2–3); ranges input-dependent
  `(0.000000 to 1.000000)` on a 1 s file 1. SR mismatch refused verbatim.
  Deterministic.

## 3–4. submix crossfade 1 & 2 — SHIPPED (both submodes)

Working argv: `submix crossfade 1 in1 in2 out [-s][-b][-e]`;
mode 2 adds `[-p powfac]`.

| mode | pair | flags | outdur | predicted stagger+indur2 |
| ---- | ---- | ----- | ------ | --- |
| 1 | n1,n2 | — | 2.0 | 2.0 |
| 1 | n2,n1 | — | 1.0 | 1.0 |
| 1 | n2,n3 | -b0.5 -e1.5 | 3.0 | 3.0 |
| 1 | n1,n2 | -s0.5 -b0.6 | 2.5 | 2.5 |
| 1 | n1,n2 | -e1.8 | 2.0 | 2.0 |
| 2 | n1,n2 | — | 2.0 | 2.0 |

- **duration_model:** `stagger + indur2`, SAMPLE-EXACT on every probe.
- **Content:** before `-b` the output is file 1 bit-exact (max diff 0.0);
  after `-e` it is file 2 bit-exact (0.0). Convex fade ⇒ overload-safe.
- **stagger>0 requires begin>stagger:** `-s0.5` alone refuses
  `Crossfade begins before end of stagger: Impossible.` (`-s0.5 -b0.6` runs).
- **Ranges (verbatim):** stagger `(0.000000 to 1.000000)` on a 1 s file 1
  (input-dependent); powfac `(0.125000 to 8.000000)` (0.05 and 9 refused —
  banner's "0.12" understates the floor).
- **Breakpoints:** all refused, parameters 1–3 (mode 1) / 1–4 (mode 2).
- Mode 2 ≠ mode 1 (shas differ); `-p4` ≠ default (powfac live).
- Channels must match: `Different no. of channels in input files: can't
  proceed.` (no auto-convert; stereo pairs run WITHOUT the merge `-e` bug).
- Deterministic (both modes).

## 5. submix mergemany — SHIPPED (arity pinned 3)

Working argv: `submix mergemany f1 f2 f3 out` (variadic; 2-input run verified).

- **duration = indur_max** sample-exact (3.0 from 1+2+3 s; 2.0 from a pair).
- **HEADLINE — always normalises to full scale, both directions:**
  3×loud1 (raw sum peak 2.970) → per-file gain 0.33669, out peak 0.99997
  (no wrap/clip); two 0.2-peak files (sum peak 0.216) → out peak **1.0000**
  (amplified). Single shared gain (n1+n2+n3 all at 0.50124) ⇒ relative balance
  preserved, absolute level always full scale.
- Mixed channels refused `Incompatible channel-count in input file st2.wav.`;
  SR refused `Incompatible sample-rate in input file n1_22k.wav.`; stereo trio
  renders stereo. No parameters. Deterministic.

## 6. submix faders — SHIPPED (arity pinned 2; two post-output aux files)

Working argv: `submix faders in1 in2 out balance-data envelope-data`.

- **duration = indur_max** (2.0 both orders; 3.0 with a trio + 3-column lines).
- **Balance lines auto-scale to sum 1:** `0 2 3` byte-identical to `0 0.4 0.6`.
  Content verified: fade file `0 1 0 / 1 0 1` tracks the crossfade (t=1.5
  g2=1.000); scalar env slot accepted (`0.5` == 0.5× the flat render, 1 LSB).
- **Cross-validation:** linear balance + flat env renders BYTE-IDENTICAL to
  `submix crossfade 1` on the same pair (sha `a2351ba0…` both).
- **HEADLINE — overload WRAPS (P5-3 pathology):** balance `0 1 1` + envelope
  3.0 on loud1 pairs → ideal peak 2.97, out peak 1.0000, and **100% of
  over-samples bit-match `wrap_int16`, 0% match clipping**. Envelope point
  values CDP-enforced `(0.000000 to 256.000000) in brkpntfile` (verbatim).
- **HEADLINE — no SR validation:** 44.1k + 22.05k pair ACCEPTED (exit 0,
  1.0 s out) — the only probed submix mode that skips the SR check; the
  mismatched file plays at the wrong rate.
- Refusals (verbatim): balance data must `begin at time zero`; all-zero line
  `levels are zero at line 2` (on a ONE-line file — off-by-one); wrong column
  count → misleading `Times 0.000000 and 0.000000 too close in datafile …`;
  mixed channels `Process only works with files having the same number of
  channels: file 2 will not work`; single input `Insufficient input files for
  this process`. Deterministic.

## 7. submix getlevel, mode 3 — SHIPPED (data output .txt; the P5-3 pre-flight)

Working argv: `submix getlevel 3 mixfile out.txt [-s][-e]`.

- **Report:** `Clip at time <t> secs : sample <n> : For <k> samples` lines +
  blank + `MAX SAMPLE ENCOUNTERED : <peak> at <t> secs` +
  `NORMALISATION REQUIRED : <factor>   OR  <dB>`. Hot 3×loud1 mixfile: 2623
  lines, factor 0.336693 (matches P5-3's mode-1 stdout on the same mix).
- **Factor = 1/peak unconditionally:** clean mix (peak 0.400) reports
  `NORMALISATION REQUIRED : 2.499924 OR 7.9585dB` — >1 means headroom, not a
  warning. File never empty (101 bytes on the clean mix).
- **Sibling disqualifiers (why mode 3):** mode 1 = stdout only, NO output argv
  (engine-incompatible); mode 2 writes a **0-byte file when nothing clips**
  (verified) — fails non-empty data verification.
- `-s9` on a 2.5 s mix → `(0.000000 to 2.500000)` (input-dependent); `-e0` →
  `Mix starts after it ends.`; with `-s` the report times are WINDOW-relative
  (verified). `-s` brk refused (parameter 1). Output named `.wav` refused
  (`Cannot open a textfile (x.wav) with a reserved extension.`). Sub-dir
  source paths inside the mixfile verified. Deterministic (byte-identical).
- **Engine spot-check:** arity-0 + pre_output mixfile + `.txt` data output ran
  end-to-end through process_impl; report tail parsed
  (`NORMALISATION REQUIRED : 0.398359 …` on a deliberate 2× overlap).

## 8. submix attenuate — SHIPPED (mixfile → mixfile, .txt)

Working argv: `submix attenuate inmix outmix gain [-s][-e]`.

- gain 0.5 on levels 1.0/0.8 → `0.5000 / 0.4000` (4-dp linear). `-6dB` at
  gain 0.5 → `0.2506` (**dB converted to linear**). Comments STRIPPED. Pans
  preserved. gain 3 → `3.0000/2.4000` (amplifies). `-s2 -e2` touched only
  line 2. Round-trip: output renders through `submix mix` (2.5 s stereo).
- Ranges: gain −1/40000 → `(0.000000 to 32767.000000)`; **gain 0 ACCEPTED**
  (writes all-zero levels — silent mix downstream; curated min 1e-6); `-s0` on
  a 2-line file → `Parameter[2] … out of range (1.000000 to 2.000000)`
  (input-dependent line count). gain brk refused (parameter 1). Deterministic.

## 9. submix pan — SHIPPED (mixfile → mixfile, .txt; time-varying pan)

Working argv: `submix pan inmix outmix pan` (scalar or breakpoint file).

- **Trajectory sampling verified exact:** panfile `0 −1 / 2.5 1` on events at
  0.0/0.5 → pans `−1.0000 / −0.6000` (linear interpolation at event START
  times). Sounds are positioned at entry only (banner).
- **HEADLINE — no-pan mono lines produce mix-REFUSED output:** input
  `name t 1 level` (no pan) → output `name t 1 lev pan lev pan` (stereo column
  layout under chans=1) and the level HALVED; `submix mix` refuses
  `Application doesn't work with this type of infile.` Mono lines WITH pan
  (5-col) round-trip perfectly — levels preserved, mix-accepted. Stereo
  short-form → valid 8-col with levels halved (both channels to one spot).
- **dB corruption:** `-6dB` level came through as plain `−3.0000` (numeric −6
  through the halving path) — negative linear level, invalid downstream.
  Sanctioned fix: `submix attenuate` gain 1.0 first (correct dB→linear).
- pan 2.5 and 50 accepted and mix-consumable (hard side + 1/|pan| attenuation).
  Deterministic. **Engine spot-check:** `abs:`-tuple envelope on this arity-0
  entry compiled and rendered `−1.0000 / −0.6000` — matching the raw probe.

## 10. submix timewarp, mode 6 (scatter times) — SHIPPED

- Q CDP-enforced 0–1 (`1.5` refused verbatim); **Q=0 identity (byte-equal)**;
  `-s3 -e4` left lines 1–2 bit-unchanged. Names/levels/pans preserved; times
  5-dp. Line 1 NOT pinned (0 → 0.599 observed at Q=0.5 on unsorted input).
- **CLOCK-SEEDED, UNSEEDABLE:** 1.2 s apart differ; same-second parallel
  launches byte-IDENTICAL; no seed slot. Q brk refused (parameter 1).
- Deterministic sibling probes (recorded, execute()-territory): mode 1 sorts
  into time order (deterministic, byte-stable); mode 13 multiplies inter-entry
  intervals by Q (times 0/1.5/2.2/3.0 ×2 → 0/3.0/4.4/6.0; Q range
  `(0.000000 to 32767.000000)`, Q=0 accepted); **mode 13 on UNSORTED input
  emits NEGATIVE times** (−1.5 observed — invalid downstream; sort first).

## 11. submix shuffle, mode 3 (scatter name order) — SHIPPED

- Permutes the NAME column only; times/levels/pans byte-preserved. `-s2 -e3`
  permuted only lines 2–3. Clock-seeded (same-second identical, 1.2 s differ).
- Sibling probes (recorded): mode 1 duplicates every line; mode 2 reverses
  name order (verified); mode 5 `-s2 -e3` omitted lines 2–3, survivors keep
  the timegap to their original successor (0/1.0 from 0/1.0/2.0/3.5); mode 6
  kept even lines (n2@0, p2@1.0). Modes 5/6 need time-sorted input (banner).

## 12. submix spacewarp, mode 5 (random-scatter positions) — SHIPPED

- Fresh random pans inside [Q1,Q2] per event; times/levels preserved; output
  mix-accepted. Bounds CDP-enforced `(-1.000000 to 1.000000)` (`-3 3` refused);
  swapped bounds (1 0) accepted. Clock-seeded (same-second identical).
- Sibling probes: mode 1 = pan-to-position (redundant with submix pan, levels
  preserved); mode 2 narrow = pans × Q (−1/+1 at Q 0.5 → ∓0.5, verified).
  Modes 3–6 collapse stereo files to mono points (banner).

## 13–14. submix sync 1 & 2 — SHIPPED (audio-aware mixfile generators)

- **sync 1 (midtimes):** n1/n2/m1 (1/2/1.5 s) → starts 0.5/0.0/0.25 (midpoints
  at 1.0). **sync 2 (endtimes):** starts 1.0/0.0/0.5 (ends at 2.0). Earliest
  start always 0.
- Bare list → lines `name t chans 1.0 C` (C = no-pan per tranche 5); existing
  mixfile input → levels/pans PRESERVED, lines re-sorted (verified on mx4).
  Stereo entries → `name t 2 1.0 L 1.0 R`. Sub-dir paths intact; round-trip
  through `submix mix` verified (2.0 s from the endtime set).
- Missing name refuses `Application doesn't work with this type of infile.`
- **No SR validation:** 44.1k+22.05k list ACCEPTED (exit 0) — refusal deferred
  to mix time. Deterministic (both modes).

## 15. submix syncattack — SHIPPED

- Aligns detected attacks: p2/p15 → offsets 0.00646/0.0 (default),
  0.00057/0.0 with `-p` (peak-power detection — flag verified live).
  Per-line search windows work (`p2.wav 0.4 1.2` moved the alignment,
  0.0/0.49746). Levels auto-set to anti-clip estimate (0.49998 each for two
  files; banner: may be over-cautiously low — adjust with submix attenuate).
- `-w` accepts ONLY 2/4/8/16/32 (`-w3`, `-w64` refused `ERROR: INCORRECT USE`);
  w2 == w32 byte-identical on this material. Mixed mono/stereo lists fine.
  Deterministic (both flag states).

---

## Dropped (evidence)

| mode | evidence |
| ---- | -------- |
| inbetween 1/2 | MULTI-OUTPUT: `submix inbetween 1 n1 tone1 ib 3` → exit 0 writing `ib001.wav ib002.wav ib003.wav` — generic outname, no single outfile argv (standing drop rule). |
| inbetween2 | Same shape: `ib2001.wav ib2002.wav` from count 2. |
| test | NO output argv: `submix test mx4.mix` prints `MIX SYNTAX IS CORRECT.` (exit 0) / infile-type error on bad files (exit 255). Console utility — execute(). |
| fileformat | Banner prose only (prints the mixfile format help); not a process. |
| dummy 1–3 | Trivial text generation: mode 2 verified (`n1 0.0 / n2 1.0 / m1 3.0` — each at previous end) — the engine already knows the durations; write_data_file territory. |
| atstep | `k*step` arithmetic (verified 0/0.75/1.5 at step 0.75, level 1.0 C) — one-line generation. |
| ongrid | Copies the gridfile times verbatim into mixfile lines (verified 0/1.25/2.0) — the LLM would write the mixfile directly. |
| addtomix | Appends new sounds at `max(at+dur)` (verified 5.5) at level 1.0 C — trivial append; duration available from describe_workspace. |
| model | Name substitution preserving times/levels/pans (verified) — trivial rewrite; CDP adds only chans/SR validation. |

Also intentionally NOT curated (recorded, not "dropped": submode selection):
getlevel 1 (no outfile argv) and 2 (0-byte file on clean mixes); timewarp
1–5, 7–16; shuffle 1–2, 4–7; spacewarp 1–4, 6–8 (deterministic text
arithmetic; key behaviors probed above for the record).

## Overload behavior map (task special-attention item)

| mode | overload behavior |
| ---- | ----------------- |
| submix mix | WRAPS (P5-3, prior) |
| submix faders | **WRAPS** via overall envelope (100% over-samples == wrap_int16; balance stage convex-safe) |
| submix merge | safe by construction (gains sum to 1) |
| submix balance | safe by construction (complementary gains) |
| submix crossfade 1/2 | safe (verbatim passthrough + convex fade) |
| submix mergemany | never overs — global peak-normalise (up AND down) |
| extend sequence2 | floats > 1 written unclipped (prior, for contrast) |

## Engine spot-checks (process_impl, real binaries)

| check | result |
| ----- | ------ |
| getlevel 3: arity-0 + pre_output mixfile + .txt data output | ok; report tail `NORMALISATION REQUIRED : 0.398359 OR -7.9945dB` |
| balance: relative brk on -k (input1 axis) | ok; outdur 1.0 = indur1 |
| mergemany: 3 inputs | ok; outdur 3.0 = indur_max; peak 1.0000 |
| pan: abs:-tuple envelope on arity-0 entry | ok; output pans −1.0000 / −0.6000 == raw-probe values |

Loader: 317 entries (318 once the parallel wave-1 agent's next entry landed
mid-run), zero malformed warnings; all 15 triples resolve by exact
(program, mode, submode).

**Shipped (15):** merge, balance, crossfade 1, crossfade 2, mergemany, faders,
getlevel 3, attenuate, pan, timewarp 6, shuffle 3, spacewarp 5, sync 1,
sync 2, syncattack. **Dropped (9, evidence above):** inbetween, inbetween2,
test, fileformat, dummy, atstep, ongrid, addtomix, model.
