# Tranche 20 — spectral tail I probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build, -fsigned-char;
  Groucho-family programs banner "CDP Release 7.1 2016"; specfold/specav/specenv/speclean/
  specnu/suppress/subtract/cantor/caltrain/notchinvert/peakiso/glisten print no release
  banner), Linux x86_64 sandbox. To be re-verified on macOS r8 by the CDP-gated suite.
- **Inputs:** fresh fixtures in `/tmp/probe20a` (`pvoc anal 1` defaults, 1024-point,
  44.1 kHz mono, PCM_16): `rich2.ana` (rich 5-partial gliss + 0.9 Hz AM, 2.0 s wav →
  synth round-trip **2.0230 s**, 698 windows), `rich15.ana` (1.5 s → **1.5209**, 525
  windows), `vow2.ana` (4-formant additive vowel 'ah', 2.0 s), `flat2.ana` (flat noise,
  rng seed 0, 0.2 amp, 2.0 s), plus purpose-built `noisy2/noisy3` tone+noise denoise
  fixtures and `rich2st.wav` (stereo). Time-domain refusal probes reuse `/tmp/probe/n2.wav`.
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. `.ana` outputs compared
  by RIFF `data`-chunk sha256 (never raw bytes — LIST date chunk); durations via
  `pvoc synth` round-trip (never sf.info on .ana); determinism pairs ≥1.3 s apart plus
  same-second pairs where stochasticity was suspected; breakpoint proof = brk render
  differs from BOTH scalar-endpoint renders; duration models at two input durations.

Refusals quoted verbatim (stdout, exit 255 unless noted).

---

## 1. spec gate

`spec gate rich2.ana out.ana 0.1` exit 0. Durations: rich2 → **1.9998**, rich15 → 1.5035
(static; marginally SHORTER than the family round-trip — atypical direction). flat2 row:
2.0085. threshold 0 → **byte-identical passthrough** (data chunk == input). Calibration on
the −14 dBFS probe: 0.003/0.01 ≈ untouched (−14.1), 0.05 −14.4, 0.2 −18.8, 0.5/1.0 →
**silence at exit 0**. Ranges: `Parameter[1] Value (-0.100000|1.500000) out of range
(0.000000 to 1.000000)`; omission `Insufficient parameters on command line.` Breakpoint
0→0.5 exit 0, differs from both endpoints → **capable**. Deterministic. wav refused
`Application doesn't work with this type of infile.`

## 2. hilite pluck

`hilite pluck rich2.ana out.ana 5` exit 0; 2.0230/1.5209 static; deterministic.
**gain 1 = byte-identical passthrough**; gain 0 accepted and NOT a passthrough. Range
`(0.000000 to 1000.000000)` (100000 refused). Brk 1→20 differs from both endpoints →
**capable**. Steady-source RMS barely moves even at gain 20 (−14.1) — change-detector by
design. wav refused.

## 3. hilite bltr

`hilite bltr rich2.ana out.ana 10 20` exit 0; static; deterministic. Ranges (both
input-dependent): blurring `(1.000000 to 698.000000)` (= window count), tracing
`(1.000000 to 513.000000)` (= channel count). Both brks differ from both endpoints →
**both capable**. wav refused.

## 4. caltrain

`caltrain caltrain rich2.ana out.ana 0.5 2000` exit 0; static (2.0230/1.5209);
deterministic; `-l300` live. Ranges: blurfact `(0.002902 to 2.025941)` (2 frames to
analysed duration, input-dependent both ends); blurabov/locut `(0.000000 to 22050.000000)`
(locut = Parameter[3]). Brks refused parameters 1/2. Banner typo 'defalut'. wav refused
`File rich2.wav is not of correct type`.

## 5. glisten

`glisten glisten rich2.ana out.ana 4 30` exit 0; static; **deterministic despite the
'random partition' framing** — 1.3 s-apart AND same-second pairs byte-identical; -p6 pair
also identical. Source: `dev/new/glisten.c` uses `drand48()` (lines 1247/1258/1386/1413)
with no srand/initrand48 anywhere — the osbind fixed-seed shim (blur chorus construction).
**grpdiv divisor rule:** 5, 3 AND 6 refused `ERROR: Number of channel-sets must be a
multiple of 2` (text misleading — 6 IS a multiple of 2); 2/4/8/512 accepted → the real
rule is the banner's "exact divisor of the channelcnt" (512 → powers of 2). Ranges:
grpdiv `(2.000000 to 512.000000)`, setdur `(1.000000 to 1024.000000)`, -p
`(0.000000 to 12.000000)` (Parameter[3]), -d/-v `(0.000000 to 1.000000)` (Parameters 4/5).
setdur brk (10→60) and grpdiv brk (2→8) both exit 0 and differ from both endpoints →
**capable** (grpdiv brk passes through non-divisors without complaint — noted). All three
flags change the render. wav refused.

## 6. specfold (modes 1–3; mode 3 curated — SoundThread's specfold_specfold_3)

Modes 1 (`20 64 4`), 2 (`20 64`), 3 (`20 64 5`) all exit 0, pairwise-distinct. Mode 3:
static (2.0230/1.5209); **seed 5 twice (1.3 s apart) byte-identical; seed 9 differs; seed
0 REFUSED** — `Parameter[3] ... out of range (1.000000 to 64.000000)` (only 64
permutations addressable). stt `(1.000000 to 509.000000)`, len `(4.000000 to 513.000000)`
(both analysis-dependent). `-a` live (distinct render). All three positionals refuse brks
(parameters 1–3). wav refused.

## 7. hilite filter (12 modes; mode 7 BAND PASS curated)

Survey (one run each): m1 HP centroid 1674 Hz, m3 LP 504, m5 HP+gain, m7 BP 1003, m9
notch 697, m11 BP+gain — all exit 0, direction as documented. Mode 7: static;
deterministic; **frq1 > frq2 silently swapped** (`2000 500` byte-identical to `500 2000`).
Ranges: frq1/frq2 `(10.000000 to 22050.000000)`; Q `(1.000000 to 22050.000000)` (banner
says only "> 0"). frq1/frq2/Q brks each differ from both endpoints → **all three capable**.
wav refused.

## 8. hilite arpeg — DROPPED (nondeterministic binary bug, source-diagnosed)

`hilite arpeg 1 rich2.ana out.ana 2 2`: **every run renders differently — including two
runs in the SAME second** (shas 7f95/8697/f5d7/ca95 across four identical invocations;
rate 0.25 where the wavetable never wraps also differs run to run). Resyntheses swing from
**pure silence (−240 dBFS) to full-scale clipping (0 dBFS, peak 1.0)** on identical argv.
No rand anywhere in dev/hilite/*.c — this is NOT an RNG: **`ap_hilite.c:820` mallocs the
per-channel `ARPE_KEEP` sustain array and never initialises it, and `hilite.c:492/506`
read it (`if(dz->iparray[ARPE_KEEP][cc])`) to choose sustain-vs-new-note from the first
window** — per-process heap garbage steers the render. Second latent bug: `hilite.c:1191`
wraps the wavetable position with `fmod(pos, 1024)` (range [0,1024)) but `hilite.c:452`
indexes with `round(pos)` → index 1024 reads one double past the 1024-slot `ARPE_TAB`
(`ap_hilite.c:780`). Flags/ranges recorded before the drop: wave `(1.000000 to 4.000000)`;
rate `(0.000000 to 344.531250)` (= window rate); -p `(0.000000 to 1.000000)`; all nine
flags accepted and each changed the render; rate brk accepted. All 8 modes share
`specarpe` → family-wide drop; afta8's overflow warning corroborates the loudness
pathology. Reachable via execute() at user's own risk.

## 9. blur weave (the "free-string" landmine defused)

`blur weave rich2.ana out.ana wv.txt` — the weave is a **datafile**, not a free string:
curable as a standard aux_file. Duration rule (empirical): outdur ≈ indur × steps/sum:
`1 2 -1 3` → 1.6167 from 2.023 (×4/5; rich15 → 1.2161); `2 2 2 -3` → 2.6877 (×4/3);
`0 1` → 4.0490 (×2). Newline vs space byte-identical; deterministic. Refusals verbatim:
step too big `Weave value 1 out of range (-696 to 697) for this file.`; back-before-start
`You cannot weave to before weave-start.`; net ≤ 0 `Weave must progress aint file.` (CDP
typo); fractional `Invalid character in weave file.`; empty `No data in weave file.`
wav refused.

## 10. focus freeze (modes 1–3; mode 3 curated)

Plain time pairs REFUSED `ERROR: No flags given in freeze data` — **at least one a/b
marker is required** (banner's "may be preceded" misleads). `a0.5 1.0`: modes 1/2/3 all
exit 0, pairwise-distinct; static (2.0230/1.5209); deterministic. Multi-event
`a0.3 0.8\n1.2 b1.5` exit 0; non-increasing times refused `Time values out of sequence in
file <name>.` wav refused.

## 11. focus hold

`focus hold rich2.ana out.ana '0.5 0.8\n1.2 0.5'` → **3.3234 s** (= 2.023 + 1.3);
rich15 → **2.8212** (= 1.521 + 1.3) → rule outdur ≈ indur + Σ(holddurs). Deterministic.
Refusals: unpaired `Freeze times not paired correctly.`; time beyond file
`Invalid freeze location : 1722.656282` — **the bad location is quoted in WINDOWS**
(5.0 s × 344.5). wav refused.

## 12. combine sum

`combine sum rich2.ana flat2.ana out.ana` exit 0. **Flag-less byte-equals -c1 (default
crossover 1.0 pinned); -c0 byte-equals infile1 (exact passthrough).** Duration =
**indur_max** ((2.023,1.521) → 2.0230 both orders). crossover range
`(0.000000 to 1.000000)`; brk 0→1 differs from both endpoints → **capable**.
Deterministic.

## 13. combine mean (8 modes; 1 and 3 curated — ST's Mean / Mean Pitch)

All 8 modes exit 0, pairwise-distinct. Duration = **indur_min** (1.5209 both orders, modes
1 and 3). Ranges: -l `(5.000000 to 22028.466797)`, -h `(48.066406 to 22050.000000)` (both
analysis-dependent), -c `(2.000000 to 513.000000)`. -l/-h/-z live; **-c100 byte-identical
to flag-less** on the probe pair. -l brk refused (`Cannot read parameter 1`).
Deterministic.

## 14. combine make / make2 — DROPPED (pitch-data-wave dependencies)

make WORKS end-to-end: `repitch getpitch 1 rich2.ana tone.ana rich2p.frq -z` (4862-byte
binary .frq) + `formants get rich2.ana rich2f.for -f4` → `combine make rich2p.frq
rich2f.for out.ana` exit 0, synth 2.0230, deterministic. But both inputs are BINARY data
files: the entry would be arity-0 with two binary pre_output aux params whose .frq
producer (repitch getpitch) is uncurated until T22 — deferred drop with this transcript as
the unblocking evidence. Wrong-type/wrong-order inputs refuse `Application doesn't work
with this type of infile.` make2 additionally requires an envelope file at the ANALYSIS
frame rate: envel extract 1's .evl refused `ERROR: Incompatible sample-rate (57) in
envelope file rich2.evl (must be 344).` — envel extract cannot produce 344 Hz (wsize floor
5 ms = 200 Hz max), so make2 has no producer even via curated paths. getpitch itself
refused the synthetic vowel (`ERROR: No valid pitch found.`) — note for T22.

## 15. spec bare

`spec bare rich2.ana rich2p.frq out.ana` exit 0 — pitchfile rides the PRE-OUTPUT argv slot
(formants put layout). Static (2.0230); deterministic; -x live (−14.1 → −17.8 dBFS).
Refusals verbatim: mismatched pitchfile `Pitchfile (525 vals) and analysisfile (698
windows) are not same length`; wrong type `rich2f.for is not a pitch file.` wav refused.
Curated with the execute() producer documented (formants_put/brktoenv precedent).

## 16. spec clean (modes 1–4; mode 2 curated)

Fixture: tone (0.4–1.2 s) + broadband noise floor; nfile = `spec cut noisy3.ana nse3.ana
0.05 0.35`. Mode 2 (`0.5` skiptime): **noise-only tail −33.9 dBFS → −240 (deleted), tonal
region untouched (−12.5 → −12.5)**. Modes 1/2 distinct; -g4 distinct; **flag-less
byte-equals -g2 (default noisgain 2.0 pinned)**. Duration 2.0143 (≈ indur1).
Ranges: skiptime `(0.000000 to 2.023039)` (input-dependent); -g `(1.000000 to 40.000000)`;
-g brk refused (parameter 2). Deterministic.

## 17. hilite greq (modes 1–2; mode 1 curated)

Mode 1 filtfile = `0.5\n400\n1200\n2600`: exit 0; static; deterministic; -r distinct;
mode 2 (paired centre/bandwidth) exit 0, distinct. Datafile validation verbatim:
`Bandwidth value (400.000000) out of range (0.083333 to 14.4) in filter data file`;
`Frequency value (-100.000000) out of range (10.000000 to 14700.0) in filter data file`
— **frequency ceiling = srate/3, not nyquist**.

## 18. hilite band

`200 800 1000 0.5` (amp) and `200 800 0010 1.5` (transpose) both exit 0, distinct; 2-line
file with 0011 flag exit 0. Static; deterministic.

## 19. hilite vowels

`hilite vowels flat2.ana out.ana vw.txt 0.25 3 0.95 0.5` (vw = `0 a/1.0 ee/2.0 oo`)
exit 0; static (2.0230/1.5209); deterministic. Content: flat noise takes band structure.
Ranges verbatim: halfwidth `(0.010000 to 10.000000)` [Parameter 2], steepness
`(0.100000 to 10.000000)` [3], range `(0.000000 to 1.000000)` [4], threshold same [5].
Bad vowel: `Unrecognised vowel string zz at pair 1 in vowel datafile`. **Banner's "Times
must start at zero" NOT enforced** (first time 0.5 accepted). halfwidth brk refused
(`Cannot read parameter 1`).

## 20. specav (modes 1–3; mode 1 curated, .txt data out)

Mode 1 → **textfile of 513 tab-separated frq/amp pairs** (the input format of
notchinvert/peakiso). **starttime 0 REFUSED** `Parameter[1] Value (0.000000) out of range
(0.002902 to 2.023038)` (min = one frametime — banner divergence); endtime
`(0.005805 to 2.025941)`. -n verified (amp column peaks at exactly 1.000000).
Byte-identical reruns. Mode 3 verified **multi-output** (`sav3out_1.txt ... _4.txt`, no
file at the declared name) → standing-rule drop; mode 2 = variadic multi-input average
(drop, execute()).

## 21. specenv

`specenv specenv flat2.ana vow2.ana out.ana 4` exit 0; content verified (noise takes the
vowel's formants: +35 dB band contrast at 650/1080/2650 Hz). All four flags live; equal
lengths exit 0; file2 shorter refused `First file is longer than 2nd: cannot proceed.`;
**file2 strictly LONGER → complete resynthesisable output then SIGABRT at teardown
(`free(): invalid size`, exit 134)** — exit-contract bug, curated stability: unstable with
equal-length guidance. windowsize `(1.000000 to 513.000000)`, brk refused; **-b enforced
`(-1.000000 to 1.000000)` while the banner describes bal > 1** (documentation error).
Duration = indur1 (1.5209/2.0230). Deterministic.

## 22. speclean clean vs specnu clean/subtract (one denoiser curated: specnu subtract)

Identical banner prose, DIFFERENT units and results: speclean persist is **SECONDS**
(`(0.002902 to 1.000000)` — refuses 100), specnu clean/subtract persist is **ms**
(`(0.000000 to 1000.000000)`). On the reference fixture (persist 100 ms / 0.1 s, noisgain
2): speclean left the noise tail at −33.9 dBFS; **specnu clean and specnu subtract both
silenced it (−240)**, subtract also drying the kept signal (−12.5 → −12.8, spectral
subtraction). specnu subtract deterministic; duration 1.9998. noisgain range
`(1.000000 to 40.000000)`. speclean clean and specnu clean dropped with this comparison;
specnu subtract curated.

## 23. specnu remove / rand / squeeze / slice

- **remove 1** (`56 58 4000 1`): exit 0, static, deterministic; mode 2 = keep-only
  complement (−35.3 vs −15.0 dBFS residues, distinct). atten `(0.000000 to 1.000000)`
  [Parameter 4]; midimin 0 accepted; reversed midimin/midimax accepted silently.
- **rand**: exit 0, static (2.0201); **all default runs byte-identical incl. same-second
  pair — no seed, fixed-shim deterministic**; -t/-g live; -t `(0.005805 to 2.025941)`
  (input-dependent), -g `(1.000000 to 349.000000)` (= windows/2); **-t brk capable**
  (differs from both endpoints). afta8's "[Doesn't work?]" contradicted — works.
- **squeeze** (`500 0.5`): exit 0, static, deterministic; centrefrq
  `(0.000000 to 22050.000000)`, squeeze `(0.001949 to 1.000000)`; **both brks capable**.
  Banner typo "may vray over time". afta8 "[Doesn't work?]" contradicted.
- **slice**: modes 1–4 multi-output ("outanalfiles"; afta8 agrees) → standing-rule drop;
  mode 5 (invert around frq) exit 0/2.0230 — left uncurated (overlaps specfold mode 2
  invert; execute()), recorded here.

## 24. suppress partials

`suppress partials rich2.ana out.ana ts.txt 300 3000 4` (ts = `0.2 0.8/1.2 1.8`) exit 0;
static (2.0230/1.5209); deterministic. Ranges: lofrq/hifrq `(0.000000 to 22050.000000)`
[Parameters 2/3], chancnt `(1.000000 to 513.000000)` [4]. Datafile refusals verbatim:
`Times (0.800000 & 0.200000) in file <name> less than 1 sampleframe (0.002902 secs)
apart.` (also catches reversed pairs); `Data not paired correctly in file <name>`.
lofrq brk refused (`Cannot read parameter 1` — brk numbering differs from range
numbering). wav refused.

## 25. subtract subtract (TIME-DOMAIN)

.ana refused `File rich2.ana is not of correct type`; wav pair exit 0. **Sample-exact
file1 − file2** wherever |ideal| ≤ 1 (maxdiff 0.0); self-subtract = digital silence
(−240); **the 6 out-of-range samples matched integer WRAPAROUND bit-exactly** (clip
hypothesis maxdiff 2.0 — it wraps, like submix mix). Duration = **indur_max** (2.0 from
(2.0,1.5) AND (1.5,2.0)). Stereo file1 + mono file2 ok; -c2 live; -c3 on stereo refused
`Channel to subtract cannot be greater than number of channels in 1st infile.`
Deterministic (decoded shas equal).

## 26. cantor — DROPPED (multi-output stem naming)

Banner argv order (`cantor set infile outfile 1 ...`) is WRONG — exit 249 `Invalid mode of
program entered.`; the working order is standard `cantor set 1 infile outfile ...`
(exit 0). But the declared outfile becomes a STEM: `... can2.wav ...` wrote
`can20.wav can21.wav can22.wav can23.wav` (4 files, one per hole-cutting generation) and
NO file at the declared path — engine output verification cannot succeed. Modes 2 and 3
likewise. Standing-rule drop (multi-output, no outfile argv honored), per precedent.

## 27. notchinvert / peakiso — DROPPED (single-token argv, engine rule pinned)

Both run WITHOUT any verb token: `peakiso savy.txt out.txt 44100` exit 0 (513-line
frq/amp in → frq/amp out; notchinvert likewise; srate restricted
`INVALID SAMPLE RATE ENTERED (44100,48000,88200,96000 only).`; minnotch
`INVALID MINIMUM NOTCH ... (range 0 - 1)`). **CLI rule pinned:** `build_cdp_argv`
(processing.py:296) unconditionally emits `[program, mode, ...]`; the doubled-token form
misparses — `peakiso peakiso savy.txt pk3.txt 44100` reads pk3.txt as minnotch:
`INVALID MINIMUM NOTCH pk3.txt (range 0 - 1)` (verbatim). Same missing-machinery class as
tranche 10a's blur shuffle: what's needed is a "no mode token" entry capability. specav 1
(curated) produces exactly their input format — chain ready when unblocked; execute()
reaches them today.

---

## Duration-row sanity pass (flat-noise fixture analysis, 2.0 s → 2.023)

spec gate 0.005 → 2.0085; specnu remove 1 → 2.0230; caltrain → 2.0230; glisten 4/30 →
2.0230; specfold 3 → 2.0230; specnu squeeze → 2.0230; specnu rand -g4 → 2.0172; hilite
pluck/bltr/filter7/greq1/band/vowels → 2.0230; suppress → 2.0230; focus freeze 3 →
2.0230. All within 1.2% of the 2.0 prediction.

## process_impl spot-checks (engine end-to-end)

| entry | call shape | predicted | actual (synth path) | result |
| ----- | ---------- | --------- | ------------------- | ------ |
| spec gate | **wav input end-to-end (auto-PVOC)**, threshold 0.005 | 2.0 | 2.0201 | PASS 1.01% |
| blur weave | aux weavfile '0 1' (x2 rule through the engine) | 4.0 | 4.0490 | PASS 1.22% |
| hilite bltr | blurring 10 + tracing BREAKPOINT [[0,200],[1,6]] | 2.0 | 2.0230 | PASS 1.15% |
| focus freeze 3 | submode triple + aux 'a0.5 1.0' | 2.0 | 2.0230 | PASS 1.15% |
| combine sum | 2-input + crossover BREAKPOINT (duration source max) | 2.0 (indur_max) | 2.0230 | PASS 1.15% |

Loader: `KnowledgeIndex.load()` clean — zero malformed warnings; all 26 new triples
resolve; multi-submode pairs (combine mean [1,3] etc.) resolve by exact triple.

26 entries curated; drops with evidence: hilite arpeg (all modes), combine make, combine
make2, cantor, notchinvert, peakiso, speclean clean, specnu clean, specnu slice (1–5),
specav 2–3, specfold 1–2, focus freeze 1–2, combine mean 2/4–8, hilite filter non-7 modes,
hilite greq 2, spec clean 1/3/4.
