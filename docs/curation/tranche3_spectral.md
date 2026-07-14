# Tranche 3 — spectral curation probe transcript

Six SPECTRAL entries curated empirically against real CDP binaries:
`specfnu specfnu` (submode 1, NARROW FORMANTS), `stretch spectrum` (submode 1),
`focus fold`, `focus step`, `blur spread`, `blur suppress`.

## Test environment

- CDP binaries: **built from source at `/tmp/CDP8/NewRelease`** (Linux x86_64 sandbox);
  banners self-identify as "CDP Release 7.1 2016" (specfnu prints no release banner).
  Findings are to be re-verified on macOS r8 by the CDP-gated test suite when these
  rows are pinned.
- Source tree at `/tmp/CDP8/dev` — used to explain stretch spectrum's maxstretch
  bound, focus step's dynamic range, focus fold's silent bound-swap, and blur
  spread's per-file band ceilings (see below).
- Probe inputs: tranche 2's generated wavs reused verbatim (16-bit PCM mono
  44.1 kHz, synthetic gliss harmonics — f0 220 Hz rising 0.5 oct/s, partials
  1/2/3/5 — plus a light 0.9 Hz envelope so grabbed windows differ):
  `in1.wav` 2.000 s, `in3.wav` 3.000 s, `stereo.wav` 1.0 s stereo.
- Analysis: `pvoc anal 1 inN.wav inN.ana` (defaults: 1024 points, overlap 3);
  fresh .ana files regenerated in this tranche's own work dir (`/tmp/t3`).
- Output verification: every `.ana` output resynthesised with `pvoc synth`;
  durations, sha256 and RMS taken from the wav's **decoded data chunk**.
- Breakpoint probes: 2-point files (`0 <low>` / `1.9 <high>`) substituted at the
  parameter's argv position, or attached to the flag (`-X<brk>` — no space).
- Determinism probes: identical argv twice with `sleep 1.1` between runs.

### Channel constraint (shared)

`pvoc anal 1 stereo.wav stereo.ana` → exit 255,
`Application doesn't work with this type of infile.`
Reproduces tranches 1–2: stereo cannot even be analysed, so all six entries are
`channel_constraint: "mono"` at the .ana level.

### Probe-hygiene note (affects raw exit codes below)

CDP refuses to overwrite an existing output file with exit 255. Two focus fold
edge-probes initially reused output names from a failed batch and reported 255;
re-run with fresh names they exit 0. All exit codes below are from fresh-name runs.

---

## 1. specfnu specfnu (submode 1 — NARROW FORMANTS)

Banner: `specfnu specfnu 1 inanalfil outanalfil narrow [-ggain] [-ooff] [-t] [-f]
[-s] [-x|-k] [-r]` — narrow "Range 1 to 1000. Timevariable."; gain "Range 0.01 to 10".

### Mode selection (task: pick THE most musically valuable, cleanly probeable mode)

All eight SoundThread-covered modes surveyed once each, resynthesised, RMS checked
(the manual warns mode 10 "may give a silent output" on some PCs — every candidate
was checked for non-zero frames and non-silence):

| mode | argv params | exit | synth RMS | note |
| --- | --- | --- | --- | --- |
| 1 NARROW | `4` | 0 | −15.7 dBFS | clean |
| 2 SQUEEZE | `4 1` | 0 | −19.5 | clean |
| 3 INVERT | `0` | 0 | −37.3 | clean, quiet |
| 4 ROTATE | `0.5` | 0 | −18.7 | clean |
| 5 NEGATIVE | (none) | 0 | −42.1 | clean, quiet |
| 8 MOVE BY | `-100 100 200 700` | 0 | −13.1 | clean |
| 9 MOVE TO | `100 200 500 1200` | 0 | −12.6 | clean |
| 19 RANDOMISE | `0.1` | **134 (SIGABRT)** | −11.6 | **crashes at teardown**: `double free or corruption (out)` after `WARNING: failed to write PEAK data`; the .ana was already written and resynthesises, but the exit contract is broken — any harness treating nonzero exit as failure rejects it |

**Mode 1 pinned**: it is the flagship mode (first of 23, the manual's lead example),
has exactly one time-variable core parameter (narrow) plus a gain trim — the
cleanest probe surface of the candidates — and is the formant-aware complement of
the already-curated `focus exag`. Modes 8/9 also probe clean but take four
positional Hz values that only mean something against a specific vocal source;
mode 19 is disqualified by the teardown crash. Note `KnowledgeIndex` keys entries
by `(program, mode)` = `("specfnu", "specfnu")`, so only one specfnu submode can
be curated at a time under the current schema.

### Probes (mode 1)

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `specfnu specfnu 1 in1.ana fnu1.ana 4` | 0 | 2.0230 s | `0413a0d49a9e1136` (−15.7 dBFS) |
| rerun (immediately) | 0 | 2.0230 s | `0413a0d49a9e1136` = |
| rerun (after `sleep 1.1`) | 0 | 2.0230 s | `0413a0d49a9e1136` = |
| `... 1 in3.ana fnu1d.ana 4` | 0 | 3.0215 s | indur 3.0 |
| `... 1 in1.ana fnu1e.ana 100` | 0 | 2.0230 s | `450723ed4783dfa0` (−17.2 dBFS) |
| `... 1 in1.ana fnuB1.ana b_nar.brk` (`0 2` / `1.9 400`) | 0 | 2.0230 s | narrow brk accepted |
| `... 4 -g1` vs `... 4` (flag-less) | 0 | — | `.ana` data chunks bit-identical (`03c87b97f6e8`) → **default gain = 1.0 pinned** |
| `... 4 -o13` | 0 | — | off list accepted |
| `... 4 -t` / `-s` / `-r` / `-x` / `-k` (each alone) | 0 | 2.0230 s | all accepted; each changes output (−15.8 / −15.9 / −16.5 / −16.4 / −26.6 dBFS) |
| `... 4 -f` | 0 | 2.0230 s | `0413a0d49a9e1136` **= base** — on this source the fundamental already is the lowest formant peak |

Refusals (raw, all exit 255):

- gain brk: `ERROR: Cannot read parameter 3 [b_gain.brk]: brkpnt_files not permitted.`
- `narrow 0.5`: `ERROR: Parameter[1] Value (0.500000) out of range (1.000000 to 1000.000000)` (same text at 2000)
- `-g0`: `ERROR: Parameter[2] Value (0.000000) out of range (0.010000 to 10.000000)` (same text at 100)
- `-x -k` together: `ERROR: SUPPRESS NON-HARMONICS WITH SUPPRESS-HARMONICS WILL PRODUCE ZERO SIGNAL LEVEL.`

- **duration_model: static** (2.0→2.0230, 3.0→3.0215; narrow 4 vs 100 same duration).
- **breakpoint_capable: narrow = true; gain = false.**
- **Deterministic** (identical sha ×3 incl. a >1 s gap).
- **Divergences**: every specfnu run on this build — successes included — prints
  `WARNING: failed to write PEAK data`; the outputs are complete and resynthesise.
  Banner ranges for narrow and gain are exactly the enforced ones (rare!).
  afta8 has no specfnu entries (program is newer than that toolkit); SoundThread's
  narrow slider (1–1000, default 4) matches the enforced range.

## 2. stretch spectrum (submode 1 — stretch above the frq_divide)

Banner: `stretch spectrum mode infile outfile frq_divide maxstretch exponent
[-ddepth]` — "depth can vary over time." exponent "(> 0)". Submode 2 (stretch
below the divide) not curated here.

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `stretch spectrum 1 in1.ana ss1.ana 1000 2 1` | 0 | 2.0230 s | `251771dc444f2f40` (−12.4 dBFS) |
| rerun (after `sleep 1.1`) | 0 | 2.0230 s | `251771dc444f2f40` = |
| `... 1 in3.ana ss2.ana 1000 2 1` | 0 | 3.0215 s | indur 3.0 |
| `... 1 in1.ana ss3.ana 500 3 2` | 0 | 2.0230 s | 2nd param set, sha differs |
| `... 1000 2 1 -d1` vs flag-less | 0 | — | data chunks bit-identical (`a3f8af2730eb`) → **default depth = 1.0 pinned** |
| `... 1000 2 1 -d0.5` | 0 | — | data differs |
| `... 1000 0.5 1` (compression) | 0 | 2.0230 s | accepted |
| `... 1000 2 1 -db_dep.brk` (`0 0` / `1.9 1`) | 0 | 2.0230 s | depth brk accepted — **0 legal inside a brk** |

Refusals (raw, all exit 255):

- `-d0` (constant): `ERROR: A non-varying depth value of zero will not change your source file.` (INVALID DATA — a semantic refusal distinct from the range check)
- `-d2`: `ERROR: Parameter[4] Value (2.000000) out of range (0.000000 to 1.000000)`
- exponent 0: `ERROR: Parameter[3] Value (0.000000) out of range (0.020000 to 50.000000)`
- maxstretch 0: `ERROR: Parameter[2] Value (0.000000) out of range (0.000454 to 2205.000000)` (identical text at frq_divide 500 → bound independent of frq_divide)
- frq_divide −100 / 30000: `ERROR: Parameter[1] Value (...) out of range (5.000000 to 22050.000000)`
- frq_divide / maxstretch / exponent brks: `ERROR: Cannot read parameter 1|2|3 [...]: brkpnt_files not permitted.`

- **duration_model: static**; **breakpoint_capable: depth = true, others false**; deterministic.
- **Divergence (banner vague, source explains)**: "exponent (> 0)" is enforced
  0.02–50 (`STR_MIN_EXP`/`STR_MAX_EXP`, `dev/include/speccon.h:242-243`); maxstretch
  is enforced SPEC_MINFRQ/nyquist to nyquist/SPEC_MINFRQ (`SPEC_MINFRQ = 10.0`,
  `speccon.h:29`; case(STRETCH) in `dev/cdp2k/tklib1.c`) = 0.000454–2205 at 44.1 kHz —
  analysis-dependent, so the JSON leaves min/max null and documents the formula;
  frq_divide is PITCHZERO (5.0) to nyquist. afta8's maxstretch 0–100 / depth
  default 0.5 and SoundThread's 0.3–4 sliders are UI values; source default_val
  table confirms depth default 1.0 (`tklib1.c:1471`), matching the empirical pin.

## 3. focus fold

Banner: `focus fold infile outfile lofrq hifrq [-x]` — "lofrq & hifrq may vary
over time."

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `focus fold in1.ana ff1.ana 500 1000` | 0 | 2.0230 s | `38a6fe19a34ffbab` (−19.3 dBFS) |
| rerun (after `sleep 1.1`) | 0 | 2.0230 s | `38a6fe19a34ffbab` = |
| `focus fold in3.ana ff2.ana 500 1000` | 0 | 3.0215 s | indur 3.0 |
| `focus fold in1.ana ff3.ana 1800 3200` | 0 | 2.0230 s | `b4d7d44618b8b708` (−31.9 dBFS — high fold keeps little of this source) |
| `focus fold in1.ana ffX.ana 500 1000 -x` | 0 | 2.0230 s | `2d302eeb16043fb0` ≠ base (−18.4 dBFS) |
| `focus fold in1.ana ffBL.ana b_lo.brk 3000` (`0 300` / `1.9 800`) | 0 | 2.0230 s | lofrq brk accepted |
| `focus fold in1.ana ffBH.ana 200 b_hi.brk` (`0 900` / `1.9 2000`) | 0 | 2.0230 s | hifrq brk accepted |
| `focus fold in1.ana ffZ3x.ana 1000 500` (**lo > hi**) | 0 | 2.0230 s | `38a6fe19a34ffbab` **= the 500/1000 run** |
| `focus fold in1.ana ffZ4x.ana 500 500` (**lo == hi**) | 0 | **1.9998 s** | `f6a0be1cef4bb0fa`, **RMS −inf dBFS (pure silence)** |

Range refusals (raw, exit 255): lofrq 0 →
`ERROR: Parameter[1] Value (0.000000) out of range (5.000000 to 22050.000000)`;
hifrq 30000 → same text as Parameter[2].

- **duration_model: static**; **breakpoint_capable: lofrq = true, hifrq = true**; deterministic.
- **Divergence (silent bound-swap, source explains)**: reversed bounds are not an
  error — output is bit-identical to the swapped order. Source:
  `if(hifrq_limit < lofrq_limit) swap(&lofrq_limit,&hifrq_limit);`
  (`dev/focus/focus.c:158`).
- **Divergence (silent-success edge)**: lofrq == hifrq exits 0 and produces a .ana
  that resynthesises to pure silence, slightly shorter than the input round-trip.
  Pinned in known_issues.
- afta8's 0–22050 UI range understates the enforced floor (5 Hz, nyquist-dependent
  ceiling); its lofrq/hifrq defaults (500/14000) are UI seed values — both are
  required positionals.

## 4. focus step

Banner: `focus step infile outfile timestep` — "Must be >= duration of 2 analysis
frames. (Rounded internally to a multiple of analysis-frame time.)" and "The
output is the same duration as the input." No time-variability claimed.

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `focus step in1.ana fs1.ana 0.25` | 0 | 2.0230 s | `2634d097341928b3` (−14.5 dBFS) |
| rerun (after `sleep 1.1`) | 0 | 2.0230 s | `2634d097341928b3` = |
| `focus step in3.ana fs2.ana 0.25` | 0 | 3.0215 s | indur 3.0 |
| `focus step in1.ana fs3.ana 0.05` | 0 | 2.0230 s | 2nd param value, sha differs |
| `focus step in1.ana fsR1.ana 0.2501` | 0 | 2.0230 s | `.ana` data chunk **bit-identical to the 0.25 run** → internal frame-time rounding verified |

Refusals (raw, all exit 255):

- brk: `ERROR: Cannot read parameter 1 [b_st.brk]: brkpnt_files not permitted.`
- `0.001`: `ERROR: Parameter[1] Value (0.001000) out of range (0.005805 to 2.025941)`
- `5` (2 s input): same range text; `5` on the 3 s input:
  `out of range (0.005805 to 3.024399)` → **max = input's analysed duration**.

- **duration_model: static**; **breakpoint_capable: timestep = false**; deterministic.
- **Divergence (both range ends dynamic, source explains)**: lo = `2.0 * frametime`
  (0.005805 s = 2×128/44100 at this analysis), hi = `wlength * frametime` (= input
  duration) — case(STEP) in `dev/cdp2k/tklib1.c:3845-3846`. The JSON leaves min/max
  null and documents the rule. SoundThread's 0.01–1.0 slider is a UI range; afta8's
  `length/1000` max expression approximates the same input-duration cap.

## 5. blur spread

Banner: `blur spread infile outfile -fN|-pN [-i] [-sspread]` — spread "(Range 0-1 :
Default 1)", "spread may vary over time."

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `blur spread in1.ana bs1.ana -p8 -s1` | 0 | 2.0230 s | `84b9d607e0fbfa3b` (−17.4 dBFS) |
| rerun (after `sleep 1.1`) | 0 | 2.0230 s | `84b9d607e0fbfa3b` = (**deterministic despite the 'noise' framing**) |
| `blur spread in3.ana bs2.ana -p8 -s1` | 0 | 3.0215 s | indur 3.0 |
| `blur spread in1.ana bs3.ana -p8 -s0.3` | 0 | 2.0230 s | 2nd param value, sha differs |
| `blur spread in1.ana bs4.ana -f4 -s1` | 0 | 2.0230 s | -f form ok |
| `blur spread in1.ana bsD.ana -p8` (no -s) | 0 | — | `.ana` data bit-identical to -s1 run (`a3055625bb69`) → **default spread = 1.0 pinned (the maximum)** |
| `blur spread in1.ana bsB.ana -p8 -sb_sp.brk` (`0 0` / `1.9 1`) | 0 | 2.0230 s | spread brk accepted |
| `blur spread in1.ana bsI.ana -p8 -i -s0.5` | 0 | — | -i ok |
| `-p0` / `-p1` / `-f1` | 0 | 2.0230 s | all accepted, non-silent (−29.8 / −21.0 / −17.9 dBFS) |

Refusals (raw, all exit 255):

- neither -f/-p: `Formant flag missing on cmdline.` (note: strange glis says
  "Formant *parameter* missing" — same rule, different text)
- both `-f4 -p8`: `Unknown flag -p on command line.`
- `-s2` / `-s-1`: `ERROR: Parameter[1] Value (...) out of range (0.000000 to 1.000000)`
- `-p13`: `ERROR: Too many formant_bands requested: max for this file is 12`
- `-f300`: `ERROR: Too many formant_bands requested: max for this file is 256`
- `-f0`: `ERROR: INTERNAL ERROR: (Bug?)` / `Formant array too small: set_specenv_frqs()`
- `-pb_pn.brk`: `Cannot read count of formant_bands.` (same non-standard text as strange glis)

- **duration_model: static**; **breakpoint_capable: spread = true; fchans/pbands = false**; deterministic.
- **Divergences**: the band-count ceilings are per-file (`max_fbands` checks in
  `dev/cdp2k/formantsg.c:171`) — 12 pitchwise / 256 frequency-wise here; afta8's
  -p floor of 2 and default of 12 are UI values (-p0/-p1 run clean, no CDP default
  exists); -f0 fails as a self-confessed internal error rather than a range refusal.

## 6. blur suppress

Banner: `blur suppress infile outfile N` — "N may vary over time."

| argv | exit | synth dur | decoded sha |
| --- | --- | --- | --- |
| `blur suppress in1.ana bp1.ana 10` | 0 | 2.0230 s | `1b59122d6ce3bea1` (−42.5 dBFS) |
| rerun (after `sleep 1.1`) | 0 | 2.0230 s | `1b59122d6ce3bea1` = |
| `blur suppress in3.ana bp2.ana 10` | 0 | 3.0215 s | indur 3.0 |
| `blur suppress in1.ana bp3.ana 100` | 0 | 2.0230 s | `37ac66ae5032b500` (−76.9 dBFS) |
| `blur suppress in1.ana bpB.ana b_ns.brk` (`0 2` / `1.9 100`) | 0 | 2.0230 s | N brk accepted (−37.0 dBFS) |

Range refusals (raw, both exit 255):

- `N = 0`: `ERROR: Parameter[1] Value (0.000000) out of range (1.000000 to 513.000000)`
- `N = 40000`: same text → enforced 1..analysis-channel-count, exactly like hilite trace.

- **duration_model: static**; **breakpoint_capable: n = true**; deterministic.
- **Divergence / honest observation**: the probe source is a clean 4-partial
  harmonic gliss (plain round-trip ≈ −12 dBFS), so suppressing even 10 channels
  leaves a −42.5 dBFS residue and 100 leaves near-silence (−76.9 dBFS) — expected
  behaviour (the loudest channels ARE such a sound), pinned in musical_use /
  known_issues as a gain-staging warning. afta8's "default 2" is a UI seed value
  (N is a required positional); SoundThread's percent-of-window slider is a UI
  reshaping.

---

## Curation-shape divergences from tranche 2 (deliberate)

1. **Bool switches ship with `default: null`, not `default: false`** (contrast
   `strange_glis.json`'s `quicksearch`). Reason: `build_cdp_argv` only omits a
   flag param when its resolved value is `None`; a `false` default is not `None`,
   so it would emit the bare switch on every engine run (and `validate_params`
   currently rejects user-supplied bools outright, telling callers to use
   execute()). With `null`, switches stay off unless explicitly requested. The
   pre-existing strange_glis entry was left untouched, but this looks like a live
   always-on `-i` for engine-built strange glis argv — flagged for the maintainers.
2. **A `str`-typed parameter is curated for the first time** (specfnu's `off`,
   `-o` formant-suppression list). The engine rejects plain-string values in
   process() today; the spec is documented for execute() use and forward
   compatibility, with `default: null` so it never reaches argv otherwise.

## Headline findings

1. **specfnu mode 19 crashes at teardown on this build** (`double free or
   corruption (out)`, exit 134/SIGABRT) *after* writing a resynthesisable .ana —
   the exit contract, not the DSP, is what fails. Combined with the manual's
   mode-10 silent-output warning, this justifies the task's "verify non-zero
   frames" rule; all eight ST-covered modes were surveyed and mode 1 (NARROW
   FORMANTS) pinned as the flagship, cleanly-probeable choice.
2. **Every specfnu run prints `WARNING: failed to write PEAK data`, successes
   included** — harness code must not treat that stderr line as failure.
3. **focus fold silently swaps reversed bounds** (`1000 500` bit-identical to
   `500 1000`; `dev/focus/focus.c:158`) **and emits pure silence at exit 0 when
   lofrq == hifrq** — a zero-width band is a silent success, not an error.
4. **stretch spectrum refuses a constant depth of 0 with a semantic error**
   ("A non-varying depth value of zero will not change your source file.") while
   accepting 0 inside a breakpoint file; its true defaults and bounds come from
   source: depth default 1.0 (empirically pinned bit-identical), exponent
   0.02–50, maxstretch nyquist/10-rule (0.000454–2205 at 44.1 kHz).
5. **focus step's range is dynamic at both ends** (2 analysis frames to the
   input's analysed duration — refusal text changes with input length) and its
   frame-time rounding is real: 0.25 vs 0.2501 give bit-identical output.
6. **blur spread is deterministic** despite being "controlled noisiness" — the
   noise is shaped from the spectral envelope, not a RNG; its `-f0` failure is a
   self-confessed internal error (`(Bug?) Formant array too small`), and its
   band-count ceilings are per-file (12 pitchwise / 256 frequency-wise here).
7. **blur suppress mirrors hilite trace's dynamic 1..channel-count bound** and
   collapses spectrally simple sources toward silence fast (−76.9 dBFS at N=100
   on a 4-partial probe) — pinned as a gain-staging warning rather than a bug.
8. **All six entries are deterministic** (every rerun with a ≥1.1 s gap produced
   bit-identical decoded audio) and **all six have static duration models**
   (2.0 s → 2.0230 s, 3.0 s → 3.0215 s at two param values each; residual is the
   usual analysis-frame pad, ≤1.2%).
