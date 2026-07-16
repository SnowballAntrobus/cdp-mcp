# Tranche 8 — scramble seed-link trigger + ST-covered singles (wave 2b) probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build; Groucho-family
  programs banner "CDP Release 7.1 2016"; scramble/envspeak/quirk print no version banner),
  Linux x86_64 sandbox. Re-verified on macOS r8 by the CDP-gated suite after integration.
- **Inputs:** synthesized in `/tmp/probe8` via python-soundfile — mono 44100 Hz float32
  enveloped noise `n1/n2/n3` (1/2/3 s, 50 ms edge ramps + 1.5 Hz amplitude envelope),
  440 Hz sines `tone1/tone2`, `am2` (220 Hz tone, deep AM — wide dynamic range for the
  level-sort probes), `sweep2` (100→1000 Hz sweep with amplitude contour — varied waveset
  sizes AND levels), `ct2` (unipolar click train), `vp2` (2.2 s, five syllable-like
  enveloped bursts — envspeak fixture), stereo noise `st2`, and `flat2` (exact replica of
  the shared formula fixture's flat noise, rng seed 0, 0.2 amp). Spectral fixtures
  `tone2.ana/rich2.ana` (2 s) and `t550_15.ana` (1.5 s) via `pvoc anal 1`.
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. Breakpoint probes use a
  2-line file substituted at the argv slot (or attached to the flag); determinism compares
  sha256 of decoded samples (float64), unseeded/paired runs launched 1.2 s apart; .ana
  outputs compared by RIFF `data` chunk (never raw bytes) or by `pvoc synth` round-trip.

Refusal errors quoted verbatim (stdout, exit 255).

---

## 1. scramble scramble (TOP PRIORITY — the stereo seed-link trigger), pinned submode 10

Working argv: `scramble scramble 10 sweep2.wav out.wav 5` — exit 0. Usage families:
modes 1–2 add an `outdur` positional, 5–8/11–14 a `cuts` textfile; 3–4/9–10 take
`infile outfile seed [-ccnt] [-ttrns] [-aatten]` only. ST covers 9/10 (level sorts).

**Loader constraint discovered:** `KnowledgeIndex` keys entries by `(program, mode)`, so
only ONE `scramble scramble` entry can exist. Submode **10** (decreasing level —
transient-first decay gesture, ST's favourite) pinned; submode 9 verified as the exact
mirror and documented in the entry.

| probe | result |
| ----- | ------ |
| duration (m9 & m10, seed 5): sweep2/am2/n2/tone2/n1 | 1.9993 / 1.9954 / 1.9999 / 1.9977 / 0.9999 — static, worst −0.23% (am2); flat2 1.9999 |
| level-sort content (am2): first/last 300 ms RMS | mode 9: 0.084 → 0.466 (rises); mode 10: 0.466 → 0.084 (exact mirror) |
| m9 vs m10 sha | differ |

**Seed verification (the point of this entry):**

- Defaults (trns=0, atten=0): seed 5 twice 1.2 s apart → **byte-identical**; seed 5 vs
  seed 9 → **identical too** — the level sort consumes no randomness; the seed is inert
  until trns/atten are nonzero.
- `-t3 -a0.5`: seed 5 twice 1.2 s apart → **byte-identical**; seed 5 vs 9 → **differ**;
  differs from the no-random render. Same on mode 10. GENUINELY STOCHASTIC with a
  WORKING, REQUIRED seed.
- Seed 0 twice → identical; **seed 0 == seed 1** (glibc `srand(0)`≡`srand(1)`, byte-identical).
- Omitting the seed: `Insufficient parameters on command line.` — **no unseeded/clock path
  exists**; reruns of identical params always reproduce.
- Mechanism (source): `dev/science/scramble.c:1123` `srand(dz->iparam[SCR_SEED])` seeds the
  `rand()` behind the osbind.c drand48 shim — the exact path that is Windows-only for
  modify revecho, live here on all platforms.
- **Trigger note:** mono-only + stochastic + seeded = the long-deferred stereo
  channel-machinery trigger now has a live curated entry. Machinery deliberately NOT
  built (Phase 6 reevaluation decision); entry carries `stereo_link_default: "related"`,
  `phase_sensitive: true`, and a known_issues record.
- Duration with `-t3`: 2.0080/2.0190 (mode 9/10) — random transposition re-lengths
  wavesets, ±~1% seed-dependent drift; documented, excluded from the static model.

**Ranges (CDP-enforced, all probed):** seed `(0.000000 to 256.000000)`; cnt `-c`
`(1.000000 to 256.000000)`; trns `-t` `(0.000000 to 12.000000)`; atten `-a`
`(0.000000 to 1.000000)`.

**Breakpoints:** trns brk → exit 0, differs from both scalar endpoints at the same seed
→ **capable** (banner-confirmed: "TRNS and ATTEN can vary through (output) time");
atten brk → exit 0, differs from both endpoints → **capable**; cnt `-c<brk>` →
`Cannot read parameter 3 [...]: brkpnt_files not permitted.`; seed positional brk →
`Cannot read parameter 2 [...]: brkpnt_files not permitted.`

**Flags NOT order-enforced** (unlike texture): `-a0.5 -c2` and `-c2 -t3 -a0.5` both run
(an apparent order failure was CDP's refuse-to-overwrite-existing-output, not ordering).
**Channels:** stereo refused `ERROR: INVALID DATA / ERROR: File st2.wav is not of correct
type (must be mono)` → `mono`. `-c20` deterministic and distinct from `-c1`.

## 2. texture grouped, pinned submode 5 (NONE)

Working argv: `texture grouped 5 n2.wav out.wav nd60.txt 5 0.5 0 0 1 1 64 64 0.2 0.5 60 60
0 1 1 0 0 2 5 20 100 1 12 -r5` (nd60.txt = "60") — exit 0, 4.9988 s, 2-channel.

- **Seed (mirrors texture simple):** `-r5` twice 1.2 s apart byte-identical; `-r5` vs
  `-r9` differ; unseeded runs differ in samples AND frame count (211225 vs 221414).
- **duration_model `set_by outdur`, honesty:** outdur 5/maxdur 0.5 → 4.9988 (−0.02%);
  outdur 8 → 7.8430 (−2.0%); maxdur 1.5 → 5.5337 (+10.7%); **gpsizehi 1001 → 58.8 s from
  outdur 5** — the last group's tail scales with gpsizehi × gppakhi + maxdur. First-class
  duration landmine, documented in the entry.
- **Ranges (CDP-enforced, probed):** packing `(0.000023 to 60)`; gpspace `(0 to 5)`;
  gpsprange `(0 to 1)`; amprise `(0 to 127)`; contour `(0 to 6)`; gpsizelo
  `(1 to 32767)`; gppaklo/hi `(0.022676 to 60000)` ms (min = one sample, srate-dependent);
  gpranglo/hi `(1 to 127)`; phgrid `(0 to 1000)`; atten `-a` `(0.000002 to 1.000000)`
  (afta8's 0–100 wrong, as with simple); seed `-r` `(0 to 32767)`; **position `-p` IS
  range-enforced here** `(0 to 1)` — DIVERGENCE from texture simple, where `-p2` ran.
- **Breakpoint map (all 24 numerics + 3 value-flags probed):** capable = packing, scatter,
  tgrid, sndfirst, sndlast, mingain, maxgain, mindur, maxdur, minpich, maxpich, phgrid,
  gpsprange, amprise, gpsizelo, gpsizehi, gppaklo, gppakhi, gpranglo, gpranghi, atten,
  position, spread (packing verified to differ from both scalar endpoints at seed 5).
  Refused = outdur (`parameter 1`), **gpspace (`parameter 14`)**, **contour
  (`parameter 17`)**, seed (`parameter 30`). **MANUAL DIVERGENCE:** cgrotext.htm says
  "All parameters except notedata, outdur and seed may vary over time" — gpspace and
  contour refuse.
- Flag order enforced (`-r5 -a0.5` → `option flag -a out of order on cmdline.`).
  `-w` (+33% dur, plays whole source), `-d` (fixed in-group timestep) exposed; `-i`
  meaningless single-input (left unexposed, like simple's `-p`/`-c` switches).
- Stereo input refused (`Application doesn't work with this type of infile.`); output
  always stereo.

## 3. envspeak envspeak, pinned submode 1 (REPEAT)

Working argv: `envspeak envspeak 1 vp2.wav out.wav 50 15 0 2 0` — exit 0.

| wsize splice offset repet rand | outdur (vp2, 2.2 s) | ×indur | note |
| --- | --- | --- | --- |
| 50 15 0 2 0 | 4.4000 | 2.000 | exact indur×repet |
| 50 15 0 3 0 | 6.6901 | 3.041 | splice overlap +1.4% |
| 50 15 0 4 0 | 8.9801 | 4.082 | +2.0% |
| 50 15 2 3 0 | 5.7100 | 2.595 | offset leaves first 2 peaks unrepeated |
| 15 5 0 2 0 | 4.3833 | 1.993 | |
| 50 15 0 2 0.5 | 3.6726 | 1.670 | rand shortens |

flat2 (shared fixture) → 4.0000 exact at repet 2; ct2 → 4.0000; st2 (stereo) → 4.0000, 2ch.

- **CONTENT REFUSAL:** tone2 → `ERROR: INVALID DATA / ERROR: FAILED TO FIND ANY ENVELOPE
  TROUGHS IN THE FILE.` (steady unmodulated material).
- **CLOCK-SEEDED STOCHASTIC (first-class finding):** rand 0.5 twice 1.2 s apart →
  **different** samples AND durations (3.7852 vs 3.8439). Source: envspeak.c:1425 calls
  `initrand48()` when rand > 0 — osbind.c defines it as `srand(time(0))`. Mode 1 has NO
  seed parameter (`ESPK_SEED` exists only for mode 11's `srand(seed)` at line 2122) →
  irreproducible, same-second collision trap applies. rand 0 twice → byte-identical.
- **Ranges (CDP-enforced):** wsize `(5 to 1000)` ms; splice `(2 to 100)` ms; offset
  `(0 to 100)`; repet `(1.000000 to 100.000000)` — **BANNER DIVERGENCE** ("Range 2
  upwards"; repet 1 runs as a near-passthrough ×1.05); rand `(0 to 1)`.
- **Breakpoints:** repet brk (2→6) exit 0, differs from both endpoints → **capable**
  (banner-confirmed); rand brk exit 0 → **capable** — **banner-silent** (its
  time-varying list omits RAND); wsize/splice/offset refused (`parameters 1–3`).
- Stereo accepted → `any`.

## 4. morph bridge, pinned submode 1

Working argv: `morph bridge 1 tone2.ana rich2.ana out.ana` — exit 0. All params optional flags.

| probe (durations via pvoc synth) | outdur |
| --- | --- |
| defaults, 2.0+2.0 | 2.0230 |
| in2 = 1.5 s | 1.5209 (= indur2) |
| in1 = 1.5 s, in2 = 2 s | 2.0230 (= indur2) |
| `-a0.5` (offset) | 2.5223 (= offset + indur2) |
| `-d0.8 -e0.8`, in1 2 s / in2 1.5 s | 1.5209 (= min) |
| `-d0.8 -e0.8`, in1 1.5 s / in2 2 s | 1.5209 (= min) |
| `-a0.5 -d0.8`, unequal pair | 2.0201 (offset + min; pred 2.0209) |

- **duration_model:** `offset + (indur2 if ef2 >= 1 and ea2 >= 1 else (indur1 if indur1 <
  indur2 else indur2))` — verified to evaluate under the repo's simpleeval (bool ops +
  ternary). **BANNER DIVERGENCE:** "outsound ends at end of first sound" for ef2/ea2 < 1
  is wrong when infile2 is shorter (rule is the MINIMUM).
- **AFTA8 DIVERGENCE (flag map):** afta8 has `-a start -b end -c sf2 -d ef2 -e sa2 -f ea2`
  (CDP7 layout); the r8 banner/binary use `-a offset -b sf2 -c sa2 -d ef2 -e ea2 -f start
  -g end`. Binary wins.
- **Ranges:** offset/start `(0.000000 to 2.020136)` (runtime = indur1); sf2/sa2/ef2/ea2
  `(0 to 1)`; end `(0.005805 to 2.025941)` (window-quantised, input-dependent).
- **Breakpoints:** all seven refused (`Cannot read parameter N [...]`, N = 1–7).
- Determinism: data chunks identical 1.2 s apart. Wav input refused (`Application doesn't
  work with this type of infile.`); mismatched analysis (`-c2048` vs default) refused
  `Incompatible analysis-sample-rate in input file ...`. Modes 2/3 verified distinct
  (submode 1 pinned; 2–6 same argv shape).

## 5. distort reform, pinned submode 6 (click stream)

Working argv: `distort reform 6 tone2.wav out.wav` — exit 0. No parameters.

- **duration_model `static` — sample-exact** on all 12 runs (modes 2/4/6/7 × tone2/n2/flat2).
- Modes 2/4/6/7 all run and are pairwise distinct; 6 pinned (most characterful; ST covers
  2/4/6/7, the rest via execute()).
- **Deterministic 'randomness':** mode 6's pulse widths come from `drand48()` in
  `genpulse()` (distort.c:339) with NO srand anywhere in distort → identical output every
  run (verified byte-identical 1.2 s apart). Unseedable by construction.
- Stereo refused (`Application doesn't work with this type of infile.`) → `mono`.

## 6. distort delete, pinned submode 2 (strongest 1-in-N retained)

Working argv: `distort delete 2 tone2.wav out.wav 4` — exit 0.

| input | cyclecnt | outdur | pred indur/cc | rel err |
| ----- | -------- | ------ | ------------- | ------- |
| tone2 | 2 | 1.0001 | 1.0 | +0.01% |
| tone2 | 4 | 0.4989 | 0.5 | −0.23% |
| tone2 | 8 | 0.2494 | 0.25 | −0.23% |
| am2 | 4 | 0.4999 | 0.5 | −0.01% |
| sweep2 | 4 | 0.5012 | 0.5 | +0.24% |
| n2 | 2 | 1.2079 | 1.0 | **+20.8%** |
| n2 | 4 | 0.7209 | 0.5 | **+44.2%** |
| n1 | 2 | 0.6036 | 0.5 | **+20.7%** |
| flat2 | 2 / 4 | 1.2105 / 0.7210 | 1.0 / 0.5 | **+21.1% / +44.2%** |

- **duration_model `expression: indur / cyclecnt`** — ±0.25% on periodic material; noise
  runs +21–44% long (strongest noise cycles are longer than average). **Duration row
  EXCLUDED from the shared flat-noise fixture** (would fail 5% tolerance by construction) —
  documented here, as with the tranche-6 grain exclusions.
- **Ranges:** cyclecnt `(2.000000 to 32767.000000)` (ST's 2–64 advisory); skipcycles
  `-s` in-range 0–32767.
- **Breakpoints:** cyclecnt brk (2→8) exit 0, 0.4695 s (between endpoints), differs from
  both scalar renders → **capable** (banner-confirmed); skipcycles →
  `Cannot read parameter 2 [...]: brkpnt_files not permitted.`
- `-s100` DROPS the skipped cycles from the output (0.4989 → 0.4422 = −100 cycles/cc at
  440 Hz) — distort repeat/average behavior; excluded from the model.
- Submode 2 distinct from 1 and 3 (verified). Stereo refused → `mono`. Deterministic.

## 7. distort replace (no submode)

Working argv: `distort replace tone2.wav out.wav 4` — exit 0.

| input | cyclecnt | outdur | rel err vs indur |
| ----- | -------- | ------ | ---------------- |
| tone2 | 4 / 8 | 1.9864 / 1.9773 | −0.68% / −1.13% |
| tone1 | 4 | 0.9887 | −1.13% |
| am2 | 4 | 1.9816 | −0.92% |
| sweep2 | 4 | 1.9978 | −0.11% |
| n2 | 4 | 2.8827 | **+44.1%** |
| flat2 | 4 | 2.8827 | **+44.1%** |

- **duration_model `static`** on periodic material (−0.1 to −1.1%); noise +44% (each
  replaced slot inherits the strongest cycle's LENGTH). **Duration row EXCLUDED from the
  shared fixture** (same reason as delete).
- **Ranges:** cyclecnt `(2.000000 to 32767.000000)` — afta8's max 500 advisory (501 ran).
- **Breakpoints:** cyclecnt brk exit 0, differs from both endpoints → **capable**
  (banner-confirmed); skipcycles refused (`parameter 2`). `-s100` drops exactly 0.2268 s
  (100 cycles) from the output. Stereo refused → `mono`. Deterministic. `-s0` verified
  byte-identical to the flagless run (the engine emits the 0 default).

## 8. analjoin join

Working argv: `analjoin join tone2.ana t550_15.ana out.ana` — exit 0.

- **duration_model `expression: indur1 + indur2`:** 2.0230 + 1.5209 → 3.5468 via synth
  (+0.08% frame padding); 3-input join runs too (5.5728 ≈ sum of three) — variadic
  upstream, entry pins arity 2, more via execute().
- No parameters. Deterministic (data chunks identical). One input →
  `Insufficient input files for this process`; wav input →
  `ERROR: INVALID DATA / ERROR: File tone2.wav is not of correct type`; mismatched
  analysis → `Incompatible analysis-sample-rate in input file ...`.

## 9. newdelay newdelay

Working argv: `newdelay newdelay n2.wav out.wav 60 1 0.7` — exit 0.

| midipitch | feedback | outdur (n2, mix 1) | model pred | rel err |
| --------- | -------- | ------------------ | ---------- | ------- |
| 60 | 0.7 | 2.1666 | 2.2003 | +1.6% |
| 60 | −0.7 | 2.1603 | 2.2003 | +1.9% |
| 60 | 0.3 | 2.0450 | 2.0657 | +1.0% |
| 60 | 0.9 | 2.5697 | 2.6718 | +4.0% |
| 60 | 0.99 | 8.9700 | 9.0358 | +0.7% |
| 60 | 0 | 2.0038 | 2.0354 | +1.6% |
| 36 | 0.7 | 2.6711 | 2.8014 | +4.9% |
| 84 | 0.7 | 2.0346 | 2.0501 | +0.8% |
| 0 | 0.7 | 7.1875 | 8.4112 | +17.0% |
| −12 | 0.7 | 10.8149 | 14.8224 | +37.1% |
| 48 | 0.5 (mix 0.5) | 2.1576 | 2.2122 | +2.5% |
| 60 | 0.7 (n1, 1 s) | 1.1508 | 1.2003 | +4.3% |
| 60 | 0.7 (flat2) | 2.1689 | 2.2003 | +1.4% |

- The tail is measured by an internal test pass (`domulti_test`, "Checking levels and
  length of tail") — no closed form. Curated expression `indur + period(midipitch) * 18.5 *
  (|fb|+1)/(2*(1−|fb|))` (Padé ln approximation, constant fitted to over-predict)
  **over-predicts on every row (+0.7% to +37.1%), never under** — safe for the duration
  cap; simpleeval-verified.
- **FEEDBACK ±1 HANGS:** `feedback 1.0` still running at 40 s (killed). CDP range is
  `(-1.000000 to 1.000000)`; curated range engine-narrowed to ±0.99 (0.99 completes in
  <1 s). First-class landmine.
- **Ranges:** midipitch `(-76.239452 to 136.765572)` (srate-dependent: one sample period
  to the delay-buffer max); mix `(0.001000 to 1.000000)`; feedback `(-1 to 1)` (CDP).
- **Breakpoints:** midipitch brk (48→72) exit 0, differs from both endpoints →
  **capable** (banner: "Delay may vary over time"); mix/feedback refused
  (`parameters 2/3`).
- Stereo accepted (2-in/2-out, tail differs slightly: 2.3290). Deterministic.

## 10. quirk quirk, pinned submode 1

Working argv: `quirk quirk 1 tone2.wav out.wav 0.7` — exit 0.

- **duration_model `static`:** tone2 2.0000 (powfac 0.3/0.7/2.0), n2 2.0000, n1 0.9999,
  am2 1.9977 (−0.11% worst), flat2 1.9999.
- **UNIPOLAR TRAP (first-class finding):** ct2 (one-sided click train, no zero crossings)
  → exit 0 and a **0-frame output file**. No CDP error; the engine's output verification
  is the only guard.
- **Ranges:** powfac `(0.010000 to 100.000000)` (0/negatives refused).
- **Breakpoints:** powfac refused (`Cannot read parameter 1 [...]`).
- Mode 1 vs 2 distinct (verified). Stereo refused (`must be mono`). Deterministic.

## 11. silend silend, pinned submode 1

Working argv: `silend silend 1 n2.wav out.wav 1.0` — exit 0.

| input | sildur | outdur | pred indur + sildur |
| ----- | ------ | ------ | ------------------- |
| n2 | 1.0 | 3.0000 | 3.0 |
| n2 | 0.5 | 2.5000 | 2.5 |
| n2 | 0.0 | 2.0000 | 2.0 |
| n1 | 2.0 | 3.0000 | 3.0 |
| st2 (stereo) | 1.0 | 3.0000 (2 ch) | 3.0 |
| flat2 | 1.0 | 3.0000 | 3.0 |

- **duration_model `expression: indur + sildur`** — exact (4 dp). Content verified: head
  bit-identical to input, tail max |amp| 0.0.
- **Ranges:** sildur `(0.000002 to 32767.000000)` (−1 refused) — but **0 is accepted**
  (no-op copy); 32768 fails with misleading `ERROR: INVALID DATA / ERROR: Cannot open
  output file` instead of a range refusal; sildur 7200 happily produced a 2-hour file
  (duration-cap pre-flight is the guard).
- **Breakpoints:** sildur refused (`Cannot read parameter 1 [...]`).
- Mode 2 (total outdur) verified: 3.5 → 3.5000; outdur < indur refused
  `out of range (2.000002 to 32769.000000)` (input-dependent). Submode 1 pinned.
- Stereo accepted → `any`. Deterministic.

---

## Engine argv verification

`build_cdp_argv` output for every entry replayed against the binaries verbatim — all
exit 0, and default-rendering equivalences hold (`scramble ... 5 -c1 -t0 -a0` byte-equals
the bare seed-5 run; `distort replace ... -s0` byte-equals the flagless run; morph
bridge's fully-defaulted flag string runs; texture grouped's 24-positional line runs).

## Final row confirmations (flat-noise fixture-compatible rows only)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| scramble scramble 10 (static), seed 5, indur 2.0 | 2.0 | 1.9999 | 0.005% |
| envspeak envspeak 1, 50/15/0/repet 2/rand 0, indur 2.0 | 4.0 | 4.0000 | 0.000% |
| newdelay, midipitch 60/mix 1/fb 0.7, indur 2.0 | 2.2003 | 2.1689 | 1.45% |
| quirk quirk 1 (static), powfac 0.7, indur 2.0 | 2.0 | 1.9999 | 0.005% |
| silend silend 1, sildur 1.0, indur 2.0 | 3.0 | 3.0000 | 0.000% |
| distort reform 6 (static), indur 2.0 | 2.0 | 2.0000 | 0.000% |

Excluded from the shared fixture with documented reasons: distort delete 2 and distort
replace (+21–44% on noise by construction), texture grouped (aux notedata file the shared
fixture cannot supply — texture simple precedent), morph bridge and analjoin join
(multi-input; the fixture writes one in.wav).

All eleven entries shipped; none dropped.
