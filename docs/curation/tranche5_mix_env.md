# Tranche 5 — mix / envelope / formants curation probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (built from ComposersDesktop/CDP8 source; banners
  self-report "CDP Release 7.1 2016"), Linux x86_64 sandbox.
- **Note:** these outcomes are re-verified on macOS r8 by the CDP-gated suite after the
  findings rows are integrated.
- **Inputs:** synthesized in `/tmp/probe` via python-soundfile (PCM_16) — mono 44100 Hz
  enveloped noise bursts `n1` (1.0 s), `n2` (2.0 s), `n3` (3.0 s); 440 Hz sines `tone1`
  (1.0 s), `tone2` (2.0 s); stereo noise `st2` (2.0 s). Tranche-specific extras:
  `n1_22k` (22050 Hz mono, for SR-mismatch probes), `pulses2` (2.0 s noise under four
  raised-cosine bursts — a maximally distinctive envelope donor), `loud1` (1.0 s
  near-full-scale noise, for overload probes). Spectral inputs are `pvoc anal 1`
  conversions of the above (default analysis; a 2 s wav → 2.029070 s `.ana`, one window
  = 1/344 s ≈ 0.002907 s).
- **Methodology:** replicates `docs/curation/tranche2_timedomain.md`. Breakpoint probes
  use a 2-line file `0.0 <lo>\n2.0 <hi>` substituted at the parameter's argv position (or
  `-X<file>` attached for flags). Determinism compares decoded samples (soundfile,
  float64), never raw bytes; unseeded pairs launched > 1.1 s apart.
- **Methodology addendum (new this tranche):** for `.ana` outputs libsndfile refuses to
  decode (channel count 1026), and raw-byte comparison ALWAYS differs because CDP writes
  a date comment into the RIFF `LIST` chunk. Determinism for spectral outputs is judged
  on the RIFF `data` chunk only (chunk-walk comparison). This trap produced two false
  "nondeterministic" readings before being identified.
- Two old traps re-confirmed: CDP refuses to overwrite existing outputs (`ERROR: INVALID
  DATA / ERROR: Cannot open output file ...`) — one whole probe round was invalidated by
  stale files from a previous tranche and re-run with fresh names; refusal errors below
  are verbatim from the binaries (exit 255 unless noted).

---

## 1. submix mix — DROPPED (engine argv-layout gap), exhaustively probed for Phase 6

**Working argv:** `submix mix <mixfile> <outfile> [-sSTART] [-eEND] [-gATTEN] [-a]` —
exit 0. The mixfile is a text file, one event per line. This is the Phase 6 `timeline()`
engine; every finding below is load-bearing for that design.

### Why dropped

`build_cdp_argv` renders `[program, mode, *inputs, output, *params]` — parameters,
including `aux_file` ones, always come AFTER the output path. `submix mix` requires the
mixfile BEFORE the output (`submix mix mixfile outfile`). An entry with the mixfile as an
`aux_file` param would render `submix mix out.wav data/events.mix` and CDP would try to
parse `out.wav` (nonexistent) as the mixfile. The mixfile also cannot be an entry input:
inputs pass through the PVOC domain gate, and a `.mix`/`.txt` extension is
`unknown_input_domain` (refused in both real and dry-run paths). **Recommendation:** add
a ParameterSpec position field (e.g. `position: "pre_output"`) consumed by
`build_cdp_argv`, or have `timeline()` assemble its own argv and enter at the security
gate. Everything else about the program is engine-compatible.

### Mixfile line syntax (all probed against the binary)

```
sndname  starttime  chans  level                                (no-pan form)
sndname  starttime  1      level  pan                           (mono panned)
sndname  starttime  2      left_level left_pan right_level right_pan   (stereo panned)
```

- `chans` MUST match the actual channel count of the named file. Wrong value:
  `WARNING: If <mixfile> is a mixfile: n1.wav is not a stereo sndfile` +
  `Application doesn't work with this type of infile.` (exit 255). Only 1 or 2 allowed.
- `level`: plain multiplier (`1.0` = unity, `4.0` accepted — clips/wraps, see below) or
  dB with suffix (`-6dB` verified ≈ ×0.5012; `0dB` = unity). **Plain negative numbers are
  refused** (`-6` and `-0.5` both: `Application doesn't work with this type of infile.`) —
  the manual's "gain −1 phase trick" does not exist here.
- `pan`: −1 hard left, 0 centre, +1 hard right; beyond ±1 = hard side + attenuation by
  1/|pan| (pan 2 verified: mono out at ×0.5 level). Letter pans from the manual's example
  (`L`, `R`) parse and behave as ±1 (verified L+R mix → stereo); **`C` does NOT behave
  as centre** — a single mono event panned `C` came out MONO, whereas numeric pan `0`
  makes a stereo file. Use numeric pans only.
- Stereo source short form `st2.wav 0.0 2 1.0` (single level, no pans) works.
- Missing columns (`sndname start` with no chans, or `chans` omitted) refuse with
  `Application doesn't work with this type of infile.`
- Comments: lines starting `;`. Blank lines ignored. Separators: spaces or tabs
  (verified). CRLF line endings work (verified). Events need NOT be in time order
  (verified — identical output after reordering).
- Negative start times refused (same infile-type error).
- **Paths may not contain spaces** — columns are whitespace-split; both bare and quoted
  space-paths refuse (`"sp dir/n one.wav"` quoted form also fails). Manual confirms:
  "There must be no gaps in the path or filename." timeline() must keep sources on
  space-free (session-relative) paths.
- Mixfile filename: `.mix`, `.txt`, and extensionless all accepted.
- Scale: a 40-line accelerando mixfile (geometric gap series) rendered in one call,
  duration matching prediction to 4 decimals.

### Path resolution inside the mixfile (cwd = session-root simulation)

Run with cwd=`/tmp/t5/sess`, mixfile at `data/ev.mix`, sounds in `inputs/`:

| mixfile reference | result |
| ----------------- | ------ |
| `inputs/n1.wav` (relative to cwd) | **works** |
| `cwd_n1.wav` (bare name, file in cwd) | works |
| `only_in_data.wav` (bare name, file next to the MIXFILE in data/) | **refused**: `WARNING: If data/ev.mix is a mixfile: uses only_in_data.wav which is not a sndfile` |
| `/abs/path/inputs/n1.wav` | works |
| `./inputs/n1.wav` | works |

**Rule: relative paths resolve against the process CWD, never the mixfile's own
directory.** With the engine's cwd = session root, `inputs/<file>` and
`graphs/<g>/<file>` references inside a mixfile work as-is.

### Output duration rule (timeline() may trust this)

`outdur = max(start_i + dur_i) − min(start_i)` — leading silence before the FIRST event
is silently stripped; gaps between events are preserved as silence.

| config | events | predicted | actual |
| ------ | ------ | --------- | ------ |
| 1 | n1@0.0 + n2@0.5 | 2.5 | 2.5000 (110250 fr) |
| 2 | n1@0.0 + n1@3.0 (gap) | 4.0 | 4.0000 |
| 3 | n1@1.0 alone | 1.0 (silence stripped) | 1.0000 |
| 4 | n1@0.5 + n1@1.5 | 2.0 (= 2.5 − 0.5) | 2.0000 |
| 5 | n1@0.0 + st2@0.2 | 2.2 | 2.2000 (2 ch) |
| 6 | 40-event accelerando | 5.3757 | 5.3757 |

Sample-exact in every case probed. timeline() should therefore predict
`max(at + dur) − min(at)` (not `max(at + dur)`).

### Channel rules (banner rule 3 verified)

- All-mono, no pan columns → **MONO** output.
- Any pan data (numeric, incl. 0/0.5) or any stereo source → STEREO. Exception: when ALL
  events are panned hard one side (all −1 or all +1, including beyond-±1 values) →
  MONO. A lone `C` behaves like no-pan (mono for a single mono event).
- Mono events without pan in an otherwise-stereo mix are panned centrally (manual,
  consistent with observations).

### SR mismatch

All sources must share one sample rate: 44.1k + 22.05k in one mixfile →
`WARNING: If data/ev.mix is a mixfile: Incompatible sample-rate in file inputs/n1_22k.wav`
+ `Application doesn't work with this type of infile.` (exit 255). An all-22050 mixfile
renders fine (output at 22050). The output SR = the common input SR.

### Overlap summing and overload — HEADLINE: it WRAPS, it does not clip

Mixing is exact linear summation (2 × level-0.5 copies == 1.0 × source, bit-verified;
3 × `-g0.333` copies ≈ ×0.999). But **when the sum exceeds full scale the 16-bit result
WRAPS AROUND** (integer overflow): 3 full-level copies of `loud1` (float sum peak 2.85,
12182 samples over ±1) produced output **bit-identical to
`wrap_int16(3·x)`** (max diff 0.0) — positive overs come back as large NEGATIVE samples.
This is catastrophic, unmusical distortion, far worse than saturation.
- The `-a` "alternative mix algorithm ... may avoid clipping" flag produced output
  **byte-identical to the unflagged run** on this config — no protection observed.
- `modify loudness 1` in the same build CLIPS on overload (verified) — the two programs
  disagree, so headroom must be enforced BEFORE submix mix, not after.
- **Pre-flight companion (verified):** `submix getlevel 1 <mixfile>` prints
  `MAX SAMPLE ENCOUNTERED : 2.850123 at 0.086304 secs / NORMALISATION REQUIRED : 0.350862
  OR -9.0973dB` (exit 0; note mode `1` is required — bare `getlevel <mixfile>` refuses
  `Cannot read mode of program.`). `submix attenuate inmixfile outmixfile gainval`
  rescales a mixfile's levels. timeline() should either keep Σlevels ≤ 1 per overlap
  region or run getlevel-style arithmetic itself.

### Flags

- `-sSTART` / `-eEND`: crop the mix in OUTPUT-time (post-silence-stripping):
  `-s0.5` on the 2.5 s config → 2.0000 s; `-e2.0` → 2.0000 s; both → 1.5000 s. Banner
  marks them test-only (edges are abrupt; topntail afterwards).
- `-gATTEN`: whole-mix attenuation. Enforced range quoted `(0.000000 to 1.000000)`
  (`-g1.5` refused) — but `-g0` is ACCEPTED and renders digital silence (banner says
  "range >0-1"; the binary allows 0).
- Determinism: identical mixfile twice, 1.1 s apart → identical decoded samples.

## 2. submix interleave — SHIPPED

**Working argv:** `submix interleave n1.wav n2.wav out.wav` — exit 0.

| inputs | outdur | frames | ch |
| ------ | ------ | ------ | -- |
| n1 (1 s) + n2 (2 s) | 2.0 | 88200 | 2 |
| tone1 + n1 | 1.0 | 44100 | 2 |
| n1+n2+n3 | 3.0 | 132300 | 3 |
| n1+n2+n3+n1 | 3.0 | 132300 | 4 |
| 5 inputs | 3.0 | 132300 | 5 |

- **duration_model:** `expression: indur_max` — sample-exact; shorter channels
  zero-padded (channel 0 exactly silent past 1 s in row 1).
- **Content:** channel *i* is a bit-identical copy of input *i* (array-equal verified) —
  determinism follows a fortiori.
- **Refusals (verbatim):** stereo input `Application doesn't work with this type of
  infile.`; SR mismatch `ERROR: INCORRECT USE / ERROR: Different sample-rates in input
  files: can't proceed.`; single input `Insufficient input files for this process`.
- No parameters at all (entry `parameters: {}`); the >2-input forms (up to 1000 channels
  per banner) are execute() territory — entry pins arity 2.

## 3. envel impose, mode 1 — SHIPPED

**Working argv:** `envel impose 1 tone2.wav pulses2.wav out.wav 20` — exit 0.

| input1 (target) | input2 (donor) | wsize | outdur |
| --------------- | -------------- | ----- | ------ |
| tone2 (2 s) | pulses2 (2 s) | 20 | 2.0000 |
| n2 (2 s) | n1 (1 s) | 20 | 2.0000 |
| n1 (1 s) | pulses2 (2 s) | 20 | 1.0000 |
| tone2 | pulses2 | 2000 | 2.0000 |
| st2 (stereo) | pulses2 | 20 | 2.0000 (2 ch) |

- **duration_model:** `expression: indur1` — sample-exact regardless of donor length
  (`static` would over-predict when the donor is longer).
- **Envelope-transfer verification (required by the task):** using the repo's
  `analysis.trajectory_frames` (PYTHONPATH=src), the output's 16-point RMS-dB trajectory
  vs the DONOR's: impose on flat tone r = **0.9607**; the raw target↔donor baseline was
  r = 0.025. Transfer confirmed.
- **Donor shorter than target:** target material past the donor's end is scaled by the
  donor's closing envelope value, not silenced — 2 s target, 1 s fading donor → second
  half RMS = 9.0% of the unprocessed target's second half.
- **wsize:** CDP-enforced `5` to **input 1's duration in ms** (2 s target: `(5.000000 to
  2000.000000)`; 3 s target: max 3000 — 2500 accepted, 3100 refused). **DIVERGENCE:**
  cgroenvl.htm and afta8 say the bound is the DONOR's length; probed both directions —
  it is the TARGET's. Fractional wsize (12.5) accepted. Breakpoint refused: `ERROR:
  Cannot read parameter 1 [b5_ws.brk]: brkpnt_files not permitted.`
- Stereo target and mono donor (and vice versa) accepted → `any`.
- Determinism: two runs 1.1 s apart identical decoded samples.

## 4. envel replace, mode 1 — SHIPPED

**Working argv:** `envel replace 1 n2.wav pulses2.wav out.wav 20` — exit 0
(SoundThread `envel_replace_1`).

| input1 | input2 | wsize | outdur |
| ------ | ------ | ----- | ------ |
| n2 | pulses2 | 20 | 2.0000 |
| st2 (stereo) | pulses2 | 20 | 2.0000 (2 ch) |
| n2 | n1 (1 s donor) | 20 | 2.0000 |

- **duration_model:** `expression: indur1` — sample-exact.
- **Replace ≠ impose:** on the same (wavy-noise target, pulsed donor) pair the two
  programs' outputs differ byte-wise; replace flattens the target's own envelope first.
  Trajectory correlation vs donor: replace r = **0.9619** (impose on the same wavy
  target: 0.9668; baseline 0.025).
- wsize rules and the donor-length documentation divergence are shared with impose
  (same refusal texts, parameter 1). Deterministic. Stereo → `any`.

## 5. envel extract — DROPPED (data-file output), fully probed

**Working argv:** `envel extract 1 n2.wav out.env 20` / `envel extract 2 n2.wav out.brk
20 [-dN]` — both exit 0.

- **Mode 1 writes a pseudo-WAV**: RIFF/WAVE container, FLOAT subtype, **sample rate 57**,
  115 frames for a 2 s input at wsize 20 (one float per envelope window; soundfile reads
  it as "audio"). With a `.wav` output name CDP writes it unchanged (`x2.wav`, RIFF
  header, SR 57); an extensionless name gets `.wav` appended by CDP itself. **Schema
  gap:** the engine derives the output extension from the domain (`.wav` for time), so an
  entry would mint an SR-57 pseudo-wav that PASSES output verification (rms readable!)
  and then poisons any downstream consumer. Dropped; needs an output-kind field (e.g.
  `output_format: ".env"` honored by the namer + verifier) before curation.
- **Mode 2 writes a text brkfile** (tab-separated time/level pairs, 116 lines at wsize 20
  on 2 s; head `0.000000 0.023255`). A `.wav` output name is refused: `ERROR: Cannot
  open a textfile (x6.wav) with a reserved extension.` `-d` datareduce range 0–1
  enforced (`-d-1`, `-d2` refused, `(0.000000 to 1.000000)`, parameter 2); `-d0.5`
  reduced 116 lines → 6; `-d0` = no reduction (116).
- wsize breakpoint refused (`Cannot read parameter 1 ... brkpnt_files not permitted.`).
- **Round-trip verified:** `envel impose 2 tone2.wav x1.env out.wav` runs (exit 0, 2.0 s)
  — the natural consumer once an env-output schema exists. Until then `envel impose 1`
  (donor = the sound itself) covers the transfer use-case without intermediate files.

## 6. formants get / formants put — DROPPED (aux `.for` pair), fully probed

**get:** `formants get tone2.ana g1.for -p8` — exit 0. Requires exactly ONE of
`-fN`/`-pN` (neither: `Insufficient parameters on command line`; both: `Unknown flag -p
on command line.`).

- The `.for` output is ALSO a RIFF/WAVE-container data file, written verbatim under ANY
  name (`.for`, `.ana`, `.wav` all accepted). **Poison verified:** a get-output named
  `.ana` reports `sfprops -d` = **107.848839 s** (from a 2 s source!) — if the engine
  named it `.ana` (its only spectral output extension), downstream duration preflights
  and PVOC synth would consume garbage. Dropped on the same output-kind schema gap as
  envel extract.
- **put:** `formants put 1 n2.ana g1.for out.ana [-i] [-l -h -g]` — exit 0; modes 1
  (replace) and 2 (impose-on-top) both produce a full-length `.ana` (duration = the
  input .ana's: 1 s input + 2 s .for → 1.026 s out; 2 s input → 2.029 s). `-i`, `-l100
  -h8000 -g0.5` all exit 0. Deterministic (data chunk identical). **Dropped on TWO
  engine gaps:** (a) the fmntfile precedes the output in the argv (same pre-output
  layout gap as submix mix); (b) it cannot be input 2 either — `.for` is
  `unknown_input_domain` to the PVOC gate. `formants vocode` covers the musical
  use-case (get+put in one program) and IS shipped.

## 7. formants vocode — SHIPPED

**Working argv:** `formants vocode tone2.ana pulses2.ana out.ana -p8` — exit 0.
Requires exactly one of `-f`/`-p` (refusals as for get). Entry pins `-p` (pitchwise,
SoundThread's choice, default 8); `-f` unexposed (mutual exclusion is inexpressible —
both flags with defaults would co-emit).

| input1 | input2 | outdur (.ana) |
| ------ | ------ | ------------- |
| tone2.ana (2 s) | pulses2.ana (2 s) | 2.029070 |
| tone2.ana (2 s) | n1.ana (1 s) | 1.026163 |
| tone1.ana (1 s) | pulses2.ana (2 s) | 1.026163 |

- **duration_model:** `expression: indur_min` (combine cross precedent; the analysis
  grid adds ~+1.5% over the source wav duration — within the 5% row tolerance).
- **Ranges (CDP-enforced, verbatim):** `-p13` → `ERROR: INVALID DATA / ERROR: Too many
  formant_bands requested: max for this file is 12` (input-analysis-dependent);
  `-p0` accepted (curated out, min 1); `-p2.5` accepted (fractional OK). `-f0` →
  `ERROR: INTERNAL ERROR: (Bug?) / ERROR: Formant array too small: set_specenv_frqs()`;
  `-f1000` → max 256. `-l`/`-h`: `(5.000000 to 22050.000000)` (numbered parameter 1);
  `-g`: `(0.000002 to 10.000000)` (parameter 3; afta8's 0–1 advisory). `-l400 -h100`
  (h<l) accepted silently; flag order `-h` before `-l` fine.
- **Breakpoints all refused:** `-p<brk>` → `Cannot read count of formant_bands.`;
  `-l<brk>` → `Cannot read parameter 1 ... brkpnt_files not permitted.`; `-g<brk>` →
  parameter 3 same.
- **Determinism:** data chunks identical 1.1 s apart (only the RIFF LIST date chunk
  differs — see methodology addendum).
- **Transfer sanity:** pvoc synth of (flat tone × pulsed donor) vocode → RMS trajectory
  correlates with the donor at r = 0.8887.

## 8. spec grab — SHIPPED

**Working argv:** `spec grab pulses2.ana out.ana 1.0` — exit 0.

- Output = ONE analysis window: 6174 bytes, `sfprops -d` **0.002907 s** (= 1/344 s, the
  default-analysis window rate) at every probed time (0, 1.0, 2.0, 2.5). Entry
  duration_model: `expression: "0.0029"` (constant; +0.24% vs measured).
- **Past-the-end behavior:** grab@2.5 on the 2.029 s analysis works and is
  data-identical to grab@2.0 (last window). But grab@99 REFUSES: `ERROR: Parameter[1]
  Value (99.000000) out of range (0.000000 to 3.025941)` — the banner's "a time beyond
  end of file will grab last window" holds only inside an internal bound slightly past
  the end. grab@−1 refused (same range text).
- time breakpoint refused (`Cannot read parameter 1 [b5_t.brk]: brkpnt_files not
  permitted.`).
- **Workflow verified end-to-end (this is why it's curated):** `morph glide sg2.ana
  sg1.ana mg.ana 2.0` on two grabbed windows → exit 0, output 2.002907 s. And the
  anti-pattern verified: `pvoc synth` of a bare grabbed window → exit 0 but **0
  frames** — a grab is not auditionable directly.
- Deterministic (data chunk).

## 9. modify loudness, mode 1 — SHIPPED

**Working argv:** `modify loudness 1 n2.wav out.wav 0.5` — exit 0 (SoundThread
`modify_loudness_1`; picked over modes 2–8: mode 1 is the only one that is single-input
with a breakpointable level — 3/4 are runtime-normalisers, 5/7/8 are multi-file).

| input | gain | outdur | notes |
| ----- | ---- | ------ | ----- |
| n2 | 0.5 | 2.0000 | == 0.5×input to 1 LSB |
| st2 (stereo) | 2 | 2.0000 (2 ch) | |
| loud1 | 4 | 1.0000 | 17979 samples over ±1: output == **clip**(4×input) |
| n2 | brk 0→1 | 2.0000 | differs from both endpoints |

- **duration_model:** `static` — sample-exact.
- **Overload behavior:** SATURATES (allclose to `clip(g·x)`, wraparound ruled out) —
  the safe counterpoint to submix mix's wrap, worth stating in both entries.
- **gain breakpoint-capable** (verified differs-from-endpoints; ramp applied: first
  100 ms RMS 3.7% of source, last 100 ms 97%; also runs on stereo input).
- **Ranges/refusals (verbatim):** gain −0.5 / −1 / 100000 → `ERROR: Parameter[1] Value
  (...) out of range (0.000000 to 32767.000000)`; gain 0 → runtime `ERROR: INVALID DATA
  / ERROR: With gain of 0.000000 the soundfile will be reduced to SILENCE!`; gain 10000
  accepted. **DIVERGENCE:** cgromody.htm claims "a gain value of −1 inverts the phase" —
  the binary refuses every negative; phase inversion is mode 6.
- Deterministic; stereo → `any`.

## 10. filter bank, mode 1 — SHIPPED

**Working argv:** `filter bank 1 n2.wav out.wav 50 1 220 4400` — exit 0 (SoundThread
`filter_bank_1`).

| input | tail flag | outdur | frames |
| ----- | --------- | ------ | ------ |
| n2 (2 s) | (none) | **3.0000** | 132300 |
| n2 | -t2 | 4.0000 | 176400 |
| n1 (1 s) | (none) | 2.0000 | 88200 |
| n1 | -t2 | 3.0000 | 132300 |
| n1 | -t0.5 | 1.5000 | 66150 |
| n3 (3 s) | -t1 | 4.0000 | 176400 |
| n1 | **-t0** | **5.9443** | **262144 (= 2^18)** |

- **duration_model:** `expression: indur + tail` — sample-exact, with an
  **UNDOCUMENTED DEFAULT tail = 1.0 s** (first-class finding: the banner shows `[-ttail]`
  with no default and cgrofilt.htm's usage line omits `-t` entirely). The entry pins
  `default: 1.0` so the emitted argv always carries `-t1.0`.
- **-t0 BUG:** tail 0 is in CDP's accepted range `(0.000000 to 20.000000)` but produces a
  fixed 262144-frame (2^18) output on BOTH 1 s and 2 s inputs — first section identical
  to the normal render, remainder low-level garbage ringing (RMS 0.001). Curated
  `min: 0.01` makes it unreachable.
- **Breakpoints:** Q brk (5→500) exit 0 and differs from BOTH endpoint renders —
  capable, banner-confirmed ("Q may vary over time"). All others refused (verbatim):
  gain `Cannot read parameter 2`, lof `3`, hif `4`, tail (`-t<brk>`) `6`, scat
  (`-s<brk>`) `7` — while range refusals number tail 5 and scat 6 (CDP's parameter
  numbering is stage-dependent; both sets quoted as-is).
- **Ranges (CDP-enforced, verbatim):** Q 0.0005 → `(0.001000 to 10000.000000)`; gain 0 →
  same range; **lof/hif 0 / −5 / 30000 → `(0.100000 to 22050.000000)`** — DIVERGENCE:
  banner/manual say 0-or-10 to srate/3 (14700); binary enforces 0.1–22050 (lof 5 and
  hif 20000 both accepted). hif < lof accepted silently. tail −1 / 31 →
  `(0.000000 to 20.000000)`; scat 2 → `(0.000000 to 1.000000)`.
- **STOCHASTIC when scat > 0, with NO seed flag:** two `-s0.5` runs 1.1 s apart differ;
  two scat-less runs are identical. Documented in the entry: keep scat 0 for
  reproducibility; no way to pin a scattered take.
- `-d` (double filtering): exit 0, differs from the unflagged render, duration unchanged.
- Stereo accepted (3.0 s, 2 ch from st2) → `any`.

## 11. hilite arpeg — DROPPED (binary defect: uninitialized memory), fully probed

**Working argv:** `hilite arpeg 1 n2.ana out.ana 2 2` — exit 0, duration 2.029070
(static). The full parameter surface was probed before the defect was found:

- Ranges (verbatim): rate → `(0.000000 to 344.531250)` (= window rate, input-dependent;
  rate 0 accepted); wave → `(1.000000 to 4.000000)`; `-p` → `(0.000000 to 1.000000)`;
  `-N` → `(0.020000 to 50.000000)` (banner says only "> 0"); `-s` → `(1.000000 to
  698.000000)` (= window count, input-dependent); `-b` → `(43.066406 to 22050.000000)`
  (min = one channel width); `-a` → `(0.000000 to 10000.000000)` (afta8's 0–100
  advisory; `-a1000` accepted). `-T`/`-K` switches exit 0.
- Breakpoints: rate brk exit 0 and differs from both endpoint renders (capable);
  `-l/-h/-b/-a/-s` brks exit 0; wave brk refused (`Cannot read parameter 1`); `-p` brk
  refused (parameter 3) — consistent with the banner ("all parameters may vary over
  time, except for wavetype and startphase") **except -N**, which ALSO refuses
  (`Cannot read parameter 8 [b5_dk.brk]: brkpnt_files not permitted.`) — banner/afta8
  divergence.
- **THE DEFECT:** repeated identical runs produce different analysis data with garbage
  amplitudes. Mode 1, 8 runs: per-run max amplitude `inf, 5.19e+18, 2.81e+22, 1.09e+35,
  inf, inf, 2.68e+26, 0.496` — 7 of 8 poisoned, one clean (0.496). Mode 2: 3 of 4
  poisoned. Modes 5/6: NaN amplitudes plus inf (mode 5's synth is 0.0 RMS silence).
  A poisoned mode-1 render synthesizes to FULL-SCALE noise (RMS 0.9999; pvoc synth
  warns `You should reduce source level to avoid clipping: use gain of <= 0.000000`);
  a lucky clean render synthesizes sane audio (RMS 0.042) — the algorithm is fine, the
  memory is not.
- **Mechanism (source-confirmed):** `dev/hilite/ap_hilite.c:820` allocates the sustain
  counter array with `malloc(dz->clength * sizeof(int))` and never zeroes it;
  `do_on()` (hilite.c) treats any nonzero `ARPE_KEEP[cc]` as an active sustained
  arpegtone and `sustain_arpeg_note()` computes `amp = windowbuf_amp * KEEP[cc]/SUST` —
  heap garbage becomes a gigantic gain. Runs are clean only when the heap happens to
  hand back zeroed pages. A one-line `calloc` fix upstream would make this curatable;
  until then every render is a lottery and the program is unusable through the engine.

---

## Final row confirmations (exact pinned params)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| submix interleave, inputs n2 (2.0) + n1 (1.0), indur_max | 2.0 | 2.0000 | 0.000% |
| envel impose 1, n2 + pulses2, wsize 20, indur1 | 2.0 | 2.0000 | 0.000% |
| envel replace 1, n2 + pulses2, wsize 20, indur1 | 2.0 | 2.0000 | 0.000% |
| formants vocode, tone2.ana + pulses2.ana, fbands 8, indur_min | 2.0 | 2.0291 | +1.45% |
| spec grab, pulses2.ana, time 1.0, const 0.0029 | 0.0029 | 0.002907 | +0.24% |
| modify loudness 1, n2, gain 0.5 (static) | 2.0 | 2.0000 | 0.000% |
| filter bank 1, n2, Q 50 / gain 1 / lof 220 / hif 4400 / tail 1.0 | 3.0 | 3.0000 | 0.000% |

**Shipped (7):** submix interleave, envel impose 1, envel replace 1, formants vocode,
spec grab, modify loudness 1, filter bank 1.
**Dropped (5, all fully probed):** submix mix (engine argv-layout gap — pre-output
aux_file position; exhaustive mixfile documentation above for Phase 6 timeline()),
envel extract (data-file output inexpressible), formants get (data-file output,
`.ana`-name poison), formants put (pre-output aux slot + `.for` input domain), hilite
arpeg (uninitialized-memory defect, source-confirmed).
