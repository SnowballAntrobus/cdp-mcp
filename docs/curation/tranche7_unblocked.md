# Tranche 7 — Phase 5 wave 2a: engine gaps closed + the six unblocked entries

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (built from ComposersDesktop/CDP8 source; banners
  self-report "CDP Release 7.1 2016"), Linux x86_64 sandbox.
- **Note:** these outcomes are re-verified on macOS r8 by the CDP-gated suite (the new
  `tests/test_pre_output_aux.py` / `test_data_outputs.py` / `test_arity0.py` carry
  real-CDP-gated re-verification of the headline empirics) after integration.
- **Inputs:** synthesized in `/tmp/probe7` via python-soundfile (PCM_16, 44100 Hz) —
  mono enveloped noise `n1` (1 s), `n2` (2 s), `n3` (3 s); 440 Hz sine `tone2` (2 s);
  4-burst raised-cosine `pulses2` (2 s); near-full-scale `loud1` (1 s); `st2` stereo.
  Spectral inputs are `pvoc anal 1` conversions (2 s wav → 2.029070 s `.ana`).
- **Methodology:** replicates `docs/curation/tranche2_timedomain.md`. Determinism
  compares decoded samples / RIFF `data` chunks (the tranche-5 `.ana` LIST-chunk trap
  applies to `.for` and `.evl` files too — they are RIFF containers with a per-run date
  comment). Breakpoint probes use 2-line files at the parameter's argv slot.
- The submix-mix empirics in `docs/curation/tranche5_mix_env.md` §1 were treated as the
  spec and spot-re-verified rather than re-derived (duration rule, overlap linearity,
  wraparound, getlevel) — plus one NEW finding on `-g` (below).

---

## Engine work (three schema gaps, closed first)

### 1. `position: "pre_output"` aux placement

`ParameterSpec` gains `position: Literal["pre_output"] | None` (default None), legal
only on positional `aux_file` params (model validator; a flagged or non-file param in
the pre-output slot has no CDP meaning). `build_cdp_argv` renders:

```
[program, mode, submode?, *inputs, *pre_output_params, output, *other_params]
```

Both param groups keep entry declaration order; the emission rules per param are
unchanged (factored into `_emit_param`). Real and dry-run paths share the builder.
Security is untouched: the pre-output slot is an ordinary argv element, so the
path-scope gate rejects outside-session pre_output paths exactly like Phase 3 aux
files (test pinned).

### 2. Data (non-audio) outputs

`KnowledgeEntry.output_format` is now `Literal[".wav", ".ana", ".evl", ".for", ".txt"]`
with `DATA_OUTPUT_FORMATS = {".evl", ".for", ".txt"}` (schema.py). Chosen from what the
blocked entries actually emit, probed: envel extract mode 1 writes a binary envelope
(RIFF/WAVE container, FLOAT, sr 57, one float per window — `.evl`, matching CDP's
filestxt vocabulary and the security gate's extension list); formants get writes a
binary formant file (`.for`); `.txt` is reserved for text data outputs (envel extract
mode 2's brkfile — no curated consumer yet).

Switched behavior for data formats:

- **Naming** (node_validation step 9, both paths): extension comes from
  `output_format`, not the domain. `output_name` normalization refuses mismatched
  extensions (`x.wav` on envel extract → `invalid_output_name`).
- **Verification** (`graph.verify_output`): exists + non-empty only; the wav
  RMS/silence decoder is never entered (test trips a mine if it is). The 100-byte audio
  floor is relaxed to non-empty — a one-window envelope is legitimately tiny.
- **Duration pre-flight**: skipped entirely (`check_duration_preflight` returns
  `([], None)`) — data files have no audio duration; the entries' `duration_model` is a
  schema placeholder. Size watchdog still bounds the subprocess.
- **Nothing feeds them to sfprops/audition**: `_read_duration_seconds` only shells
  sfprops for `.ana`; visualize/analyze/compare/cluster only auto-synth
  `.ana`/`.pvx`; the PVOC input gate already refuses `.evl`/`.for`/`.txt` as inputs
  (`unknown_input_domain`) in both real and dry paths. Poison cases re-verified on the
  binaries: a get output named `.ana` reports `sfprops -d` = 107.848839 s from a 2 s
  source; a `.wav`-named extract output reads as sr-57 FLOAT "audio".

### 3. Arity-0 (generators)

`input_arity: 0` is now a working shape end to end:

- `process()`'s `input` argument becomes optional (`None` or `[]` = no inputs);
  `validate_node` accepts the empty list (every per-input loop is a clean no-op);
  `arity_mismatch` gets a generator-aware fix string.
- **Pre-flight with no indurs:** `set_by` evaluates from the dur param as before;
  `static` skips (no known durations); an `indur`-referencing expression skips
  explicitly (the old `any()` guard was vacuously False on an empty list and would have
  KeyError'd).
- **Breakpoints on generators:** relative-time envelopes need an axis and there is no
  input audio — the axis is the OUTPUT duration, taken from the `set_by` dur param
  (user value, then curated default). New lineage `source_kind: "set_by_param"`.
  Verified against the real binary: `synth wave` frq envelope `[[0,220],[1,880]]`
  compiles against `dur` and renders (differs from the constant render). Absolute-time
  tuples and pre-existing `.brk` paths worked already (no axis needed).
- **Lineage:** empty `inputs` list; params snapshot is the provenance.
- **graph()/batch()/sweep() EXCLUDE arity-0** with a structured
  `arity_zero_unsupported` error (documented choice): graph node specs require a
  non-empty `in` by construction, batch varies inputs, sweep holds one input constant —
  all three are input-wiring shapes. The error's fix points at `process()` (run the
  generator, then wire its output / reference it in `inputs={}`). Revisit only if a
  generator-inside-graph story earns a spec change.

One knock-on integration step: `data_uncurated/synth.json` (stub keyed
`synth <unknown>`) was deleted — the long-tail generator only emits programs with no
curated entry (its own invariant, pinned by `test_uncurated_loader`), and synth is now
curated. Totals move 250 → 255 / 61 → 67.

---

## 1. submix mix — SHIPPED (arity 0 + pre_output mixfile)

The tranche-5 §1 empirics are the entry's spec (mixfile syntax, path resolution,
channel/SR rules, duration rule, wrap, getlevel). Re-verified this wave:

| check | result |
| ----- | ------ |
| n1@0.0 + n2@0.5 | 2.5000 s (sample-exact, = max(at+dur) − min(at)) |
| lone n1@1.0 | 1.0000 s (leading silence stripped) |
| 2 × level-0.5 copies of n2 | bit-identical to n2 (maxdiff 0.0 — linear sum) |
| 3 × full-level loud1 | 22287 overs, output == wrap_int16(3x) to 1 LSB |
| `submix getlevel 1 <mixfile>` | `MAX SAMPLE ENCOUNTERED : 2.970153 at 0.004104 secs / NORMALISATION REQUIRED : 0.336683 OR -9.4556dB` |

**NEW FINDING — `-g` is the native headroom valve:** `-g0.336683` (getlevel's exact
factor) on the triple-overlap wrap case renders CLEAN — correlation 1.0 with the ideal
scaled float sum, peak 0.99997 (≈ 0.336683 × 2.970153), maxdiff ~1.5 LSB. So `-g`
attenuates the float sum BEFORE 16-bit quantisation, unlike the `-a` flag (tranche 5:
byte-identical no-op on the same case). The entry exposes `atten` (-g, curated min
0.000001 — CDP accepts `-g0` but renders silence) and its known_issues carry the
mandated pair: OVERLOAD WRAPS + `submix getlevel 1` pre-flight guidance (getlevel via
`execute()`; the mode digit is required).

- **Entry shape:** `input_arity` 0; `mixfile` aux_file `position: "pre_output"`
  (required); `atten` (-g). `-s`/`-e` crop flags are banner-marked test-only and `-a`
  is a verified no-op — none exposed.
- **duration_model:** `expression: "mixfile"` — deliberately references the (non-
  scalar) mixfile param so the pre-flight's existing "param isn't a scalar → can't
  predict → skip" guard engages. The real rule (max(at+dur) − min(at)) is documented in
  the entry for humans/LLMs; the engine cannot evaluate it (durations live inside the
  mixfile). Watchdog covers.
- **Engine argv (lineage-verified):** `submix mix data/ev.mix graphs/<gid>/n1_submix-mix.wav`
  — mixfile before output, lineage `inputs: []`.
- Deterministic; stochastic false.

## 2. formants put, mode 1 — SHIPPED (pre_output .for aux)

**Working argv:** `formants put 1 n2.ana g1.for out.ana [-i][-l][-h][-g]` — exit 0.

- **Duration = the input .ana's duration** regardless of the .for's length (2 s → 2.029070;
  1 s .ana + 2 s .for → 1.026163). `duration_model: expression "indur"` (pvoc grid
  ~+1.5%, inside 5%).
- Mode 1 (replace) pinned; mode 2 (impose on top) is data-chunk-distinct (verified) and
  execute() territory. `-i` quicksearch changes the render (mode 1 only per banner).
- **Ranges (verbatim):** `-l` → `Parameter[1] ... (5.000000 to 22050.000000)`; `-h` →
  `Parameter[2]` same range; `-g` → `Parameter[3] ... (0.000002 to 40.000000)` —
  **NOTE: gain max 40 here vs vocode's 10** (`-g20` accepted). Breakpoints refused:
  `-l` parameter 1, `-g` parameter 3, `-h` parameter 2 (`brkpnt_files not permitted`).
- Non-formant aux file refused cleanly: `ERROR: INVALID DATA / ERROR: cannot open input
  file notfor.txt to read data.`
- Deterministic (data chunk identical 1.1 s apart; flags change the render).
- **Engine chain verified end-to-end (real binaries):** formants get output referenced
  as `graphs/<gid>/n1_formants-get.for` → formants put exit ok → healthy `.ana`.

## 3. envel extract, mode 1 — SHIPPED (data output .evl)

**Working argv:** `envel extract 1 n2.wav out.evl 20` — exit 0 (engine names the
output `.evl`; CDP writes the same bytes under any name, which is the poison the data
output kind prevents).

- Output: RIFF/WAVE container, FLOAT, sr 57, 115 frames for 2 s at wsize 20 (~2530
  bytes; wsize 2000 → 1 float, 2074 bytes — header ≈ 2070 bytes). **Envelope fidelity:
  r = 0.99** against the source's per-window peak trajectory (115 effective windows ≈
  17.4 ms — CDP's window-count rounding runs above dur/wsize; noted in the entry).
- **wsize:** CDP-enforced 5 to input-length-in-ms (`(5.000000 to 2000.000000)` on 2 s;
  4 and 2001 refused). Fractional accepted (12.5). Brk refused (`Cannot read parameter
  1 ... brkpnt_files not permitted.`). Entry default 20 (always emitted).
- Stereo input accepted → `any`. Deterministic in the data chunk (raw bytes differ —
  LIST date chunk, same trap as .ana).
- **Round-trip verified:** `envel impose 2 tone2.wav e1.evl rt.wav` (NO wsize arg in
  mode 2) → exit 0, 2.0 s. Consumer route documented as execute() (curated envel
  impose is pinned to mode 1).
- Mode 2 (text brkfile, `-d` datareduce) remains uncurated (execute()); `.txt` sits in
  the Literal for the day it lands.

## 4. formants get — SHIPPED (data output .for)

**Working argv:** `formants get tone2.ana g1.for -p8` — exit 0.

- Exactly one of `-f`/`-p` (neither: `Insufficient parameters on command line`; both:
  `Unknown flag -f on command line.` — flag named per ordering). Entry pins `-p`
  (fbands, default 8) exactly like vocode; `-f` via execute().
- **Ranges (verbatim, all matching the vocode findings):** `-p13` → `Too many
  formant_bands requested: max for this file is 12` (input-dependent); `-p0` accepted
  (curated out, min 1); `-p2.5` accepted; `-f0` → `ERROR: INTERNAL ERROR: (Bug?) /
  ERROR: Formant array too small: set_specenv_frqs()`; `-f1000` → max 256. `-p` brk
  refused (`Cannot read count of formant_bands.`).
- Deterministic in the data chunk (148400 bytes at -p8 on tone2.ana).
- **Poison re-verified** (recorded in the entry): get output named `.ana` → `sfprops
  -d` 107.848839 s; named `.wav` → soundfile "reads" sr-344 audio. The engine now
  names it `.for` and treats it as data everywhere.

## 5. synth noise — SHIPPED (arity 0)

**Working argv:** `synth noise out.wav 44100 1 2.0 [-a0.5]` — exit 0.

| check | result |
| ----- | ------ |
| dur 2.0 | 88200 frames (sample-exact set_by) |
| back-to-back + 1.2 s apart | byte-identical — **deterministic, NO seed exists** |
| amp 0.25 | == 0.25 × amp-1 render (exact linear; RMS 0.1439 vs 0.5757) |
| amp brk 0→1 | ramp applied (first-100ms RMS 6% of last) — **breakpoint-capable** |
| chans 2 / 4 | **DUAL-MONO** (channels bit-identical) |

- **Ranges (verbatim):** dur `(0.040000 to 7200.000000)`; chans `(1.000000 to
  16.000000)` — **banner says "1, 2 or 4" but 3/5/8/16 all render** (correct channel
  counts); amp `(0.000000 to 1.000000)` with `-a0` ACCEPTED rendering digital silence
  (curated min 0.000001 — verification would fail a silent render); srate quotes
  `(16000.000000 to 192000.000000)` but only the discrete set
  16000/22050/24000/32000/44100/48000/88200/96000 is accepted (44000 → `Invalid sample
  rate.`; 176400/192000 refused despite the quote; the banner lists a third set).
- afta8's `-f` float flag is NOT in this binary's banner; passing it is accepted and
  ignored (output stays PCM_16). Not exposed.
- **The determinism is a first-class finding:** identical params → THE SAME noise
  every run (no clock seed, no seed flag) — the inverse of the tranche-2 clock-seed
  trap. Recorded `stochastic: false` literally.
- SoundThread ships `synth_noise` (inputtype `[]`) — parameterization matches
  (srate/chans/dur + automatable -a amp).

## 6. synth wave, mode 1 (sine) — SHIPPED (arity 0; frq probed)

**Working argv:** `synth wave 1 out.wav 44100 1 2.0 440 [-a0.5] [-t4096]` — exit 0.
Engine argv shape verified via lineage: `[synth, wave, 1, <out>, 44100, 1, 2, 440]`
(submode renders before the output; positionals in banner order after it).

- **frq (the probe the task asked for):** required positional after dur; CDP-enforced
  `(0.100000 to 22000.000000)` REGARDLESS of sample rate — **12 kHz at srate 22050
  accepted silently (aliases)**; fractional fine (440.5); **breakpoint-capable**
  (banner "Frq and Amp may vary through time"; brk render differs from constant).
  Entry default 440.
- **amp:** same rules as noise (0-1, `-a0` = silence, brk-capable, verified ramp).
- **tabsize (-t):** CDP-enforced `(256.000000 to 4096.000000)` (`-t3`/`-t100000`
  refused; afta8's 0-32000 wrong); `-t4096` changes the render (cleaner table).
- **Modes:** 1 sine / 2 square / 3 / 4; mode 5 → `Program mode value [5] is out of
  range [1 - 4]`. **DIVERGENCE:** banner labels mode 3 "sawtooth wave" and 4 "ramp
  wave", but mode 3's rendered cycle is a TRIANGLE (peak at quarter-cycle, trough at
  three-quarter, verified numerically); afta8 and SoundThread (`synth_wave_3`) both say
  triangle. Entry pins submode 1; 2-4 via execute().
- dur/chans/srate rules identical to noise (dur 0.039 refused; chans 17 refused
  `(1.000000 to 16.000000)`; dual-mono stereo verified). Deterministic (1.1 s apart).
- **Engine breakpoint axis verified on the binary:** frq `[[0,220],[1,880]]` through
  process() compiles against dur (`set_by_param`) and renders a glissando distinct
  from the constant render.

---

## Final row confirmations (exact pinned params)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| submix mix, n1@0 + n2@0.5, rule max(at+dur)−min(at) | 2.5 | 2.5000 | 0.000% |
| formants put 1, n2.ana + g1.for, indur | 2.0 | 2.0291 | +1.45% |
| synth noise, dur 2.0 (set_by) | 2.0 | 2.0000 | 0.000% |
| synth wave 1, dur 2.0 / frq 440 (set_by) | 2.0 | 2.0000 | 0.000% |
| envel extract 1, n2, wsize 20 | (data output — no audio duration; pre-flight skips) | .evl, 115 floats | n/a |
| formants get, tone2.ana, fbands 8 | (data output — no audio duration; pre-flight skips) | .for, 148400-byte data chunk | n/a |

**Fixture compatibility (the pinned-table landmines):** NONE of the six rows fit
`test_curation_formulas`' shared single-input formula fixture — submix mix and the
synths are arity-0 (the fixture always passes `input_name="in.wav"`), formants put
needs a .for aux the fixture cannot supply (grain rerhythm precedent), and the two
data outputs have no measurable audio duration (`_measured_duration` reads audio).
Duration rules are pinned instead by the new gated tests:
`test_submix_mix_real_cdp_duration_rule`,
`test_synth_noise_real_cdp_deterministic_and_exact`, and
`test_synth_wave_real_cdp_frq_breakpoint`.

**Shipped (6):** submix mix, formants put 1, formants get, envel extract 1, synth
noise, synth wave 1. **Dropped (0).**
