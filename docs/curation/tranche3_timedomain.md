# Tranche 3 — time-domain curation probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (built from ComposersDesktop/CDP8 source; the older
  Groucho programs self-report "CDP Release 7.1 2016"; the `bounce` binary prints no
  version banner at all), Linux x86_64 sandbox.
- **Note:** these outcomes are re-verified on macOS r8 by the CDP-gated suite
  (`tests/test_curation_formulas.py` and `tests/test_breakpoint_curation.py`) after the
  findings rows are integrated.
- **Inputs:** the tranche-2 probe set in `/tmp/probe`, reused after re-verifying headers
  (mono 44100 Hz float32): enveloped noise bursts `n1` (1.0 s), `n2` (2.0 s), `n3`
  (3.0 s); 440 Hz sine tones `tone1` (1.0 s), `tone2` (2.0 s); stereo noise `st2`
  (2.0 s). Tranche-3 aux inputs written fresh: notedata textfiles and transposition
  value-lists (see §5/§6).
- **Methodology:** replicates `docs/curation/tranche2_timedomain.md`. Breakpoint probes
  use a 2-line file `0.0 <lo>\n2.0 <hi>` substituted at the parameter's argv position (or
  `-X<file>` attached for flags). Determinism compares sha256 of **decoded samples**
  (soundfile, float64), never raw bytes; unseeded pairs are launched > 1.1 s apart
  (clock-seed collision trap).
- **Probe trap (methodology note):** CDP refuses to overwrite an existing output file
  (`ERROR: INVALID DATA / ERROR: Cannot open output file t3_x.wav`, exit 255). One
  breakpoint probe (distort divide) initially appeared refused for this reason; every
  probe below was re-run against a fresh output name before recording.

Refusal errors quoted below are verbatim from the binary (emitted to stdout with exit 255).

---

## 1. modify stack

Working argv: `modify stack n1.wav out.wav -12 3 1 0 1 1` — exit 0
(positionals: transpos count lean atk-offset gain dur; flags -s -n).

| input | indur | transpos | count | dur | atk | outdur (frames) | predicted `dur * indur * max(1, 2^(-transpos(count-1)/12))` |
| ----- | ----- | -------- | ----- | --- | --- | --------------- | ---------------------- |
| n1 | 1.0 | −12 | 3 | 1.0 | 0   | 4.0000 (176401) | 4.0 |
| n1 | 1.0 | +12 | 3 | 1.0 | 0   | 1.0000 (44101)  | 1.0 |
| n1 | 1.0 | −12 | 2 | 1.0 | 0   | 2.0000 (88201)  | 2.0 |
| n1 | 1.0 | −12 | 3 | 0.5 | 0   | 2.0000 (88200)  | 2.0 |
| n2 | 2.0 | −12 | 3 | 1.0 | 0   | 8.0000 (352801) | 8.0 |
| n2 | 2.0 | −6  | 4 | 1.0 | 0   | 5.6569 (249468) | 5.65685 |
| n1 | 1.0 | −12 | 3 | 1.0 | 0.5 | 4.0000 (176401) | 4.0 (atk does not change outdur) |
| n1 | 1.0 | 0   | 3 | 1.0 | 0   | 1.0000 (44101)  | 1.0 |

- **duration_model:** `expression: dur * indur * (2 ** (-transpos * (count - 1) / 12) if
  transpos < 0 else 1)` — worst error 0.0023% (outputs carry one extra frame). The
  ternary and `**` were verified to evaluate under the repo's simpleeval with
  `functions={}`. atk-offset verified duration-neutral (only realigns attacks inside the
  output).
- **TRANSPOS FILE TRAP (first-class finding):** the transpos slot also accepts a text
  file of per-layer transposition values. Verified: file `0\n-12\n-24\n` with count 3 is
  **byte-identical** to scalar `-12` (scalar T ≡ value-list [0, T, 2T, …]). A brk-shaped
  time/value file (`0.0 0\n2.0 -12\n`) with count 4 runs (exit 0) with its four numbers
  consumed as a **flat value list** — layers at 0, 0, 2 and −12 semitones — NOT a time
  envelope. Mismatched counts print
  `WARNING: Count of transposition values in file (2) / does not correspond to number of
  stack components entered as parameter (3), / Using 2 as number of transpositions` and
  silently override count. transpos curated `breakpoint_capable: false`; the file form is
  inexpressible under the current schema (non-.brk str params are rejected).
- **Scalar ranges (CDP-enforced, all probed):** transpos ±100 →
  `ERROR: INVALID DATA / ERROR: Transposition value (100.000000) out of range (-60.000000
  to 60.000000)` (note: INVALID DATA, not INCORRECT USE — the file-or-number path);
  count `(2.000000 to 32.000000)`; lean `(0.010000 to 100.000000)` (11 accepted — afta8's
  0-10 advisory); atk-offset `(0.000000 to 1.000000)` on a 1 s file, 1.5 accepted on a
  2 s file (max = indur, input-dependent); gain `(0.100000 to 10.000000)`; dur
  `(0.000000 to 1.000000)`, and dur 0 passes the range check but aborts with
  `ERROR: You have asked to make NONE of the output!!`.
- **Breakpoint probes (all 5 numeric params refused; note the numbering EXCLUDES
  transpos):**
  - count: `ERROR: Cannot read parameter 1 [b3_cnt.brk]: brkpnt_files not permitted.`
  - lean: `ERROR: Cannot read parameter 2 [b3_ln.brk]: brkpnt_files not permitted.`
  - atk-offset: `ERROR: Cannot read parameter 3 [b3_ao.brk]: brkpnt_files not permitted.`
  - gain: `ERROR: Cannot read parameter 4 [b3_gn.brk]: brkpnt_files not permitted.`
  - dur: `ERROR: Cannot read parameter 5 [b3_du.brk]: brkpnt_files not permitted.`
- **Flags:** `-s` ("see the relative levels") is a **no-op in this build** — output
  byte-identical to the unflagged run, nothing extra on stdout/stderr; left unexposed.
  `-n` (Normalise) works (same duration, different samples) and is banner-only —
  **DIVERGENCE:** cgromody.htm's usage line lists only `[-s]`.
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo accepted (st2 −12/3 → 8.0 s, 2 ch, model holds) → `any`.

## 2. distort divide

Working argv: `distort divide tone2.wav out.wav 2` — exit 0.

| input | indur | divider | outdur (frames) | drift vs static |
| ----- | ----- | ------- | --------------- | --------------- |
| tone2 | 2.0 | 2 | 1.9977 (88100) | −0.11% |
| tone2 | 2.0 | 4 | 1.9955 (88000) | −0.23% |
| tone1 | 1.0 | 2 | 0.9977 (44000) | −0.23% |
| n2    | 2.0 | 2 | 1.9999 (88197) | −0.003% |
| n1    | 1.0 | 4 | 0.9998 (44092) | −0.02% |
| tone2 | 2.0 | brk 2→8 | 1.9932 (87900) | −0.34% |

- **duration_model:** `static` — worst drift −0.34% (wavecycle re-quantisation; always
  marginally shorter).
- **DIVERGENCE (breakpoint capability undocumented):** divider brk (`0.0 2 / 2.0 8`) →
  exit 0, 87900 frames (between the N=8 scalar's 87800 and N=2's 88100), and the render
  differs from **both** endpoint scalar renders → **capable**. Neither the banner nor
  cdistort.htm mentions time-variability (cf. distort multiply — same double silence).
- **"Integer only" not enforced:** divider 2.5 → exit 0, byte-identical to divider 3
  (rounds to nearest, does not truncate).
- **Scalar ranges (CDP-enforced):** divider 1 / 17 →
  `ERROR: Parameter[1] Value (...) out of range (2.000000 to 16.000000)`.
- **-i (interpolation):** exit 0, same duration, different render.
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo refused: `Application doesn't work with this type of infile.`
  (exit 255) → `mono`.

## 3. distort omit

Working argv: `distort omit tone2.wav out.wav 2 5` — exit 0 (positionals: A B).

| input | indur | A | B | outdur (frames) |
| ----- | ----- | - | - | --------------- |
| tone2 | 2.0 | 2 | 5 | 2.0 (88200) |
| tone2 | 2.0 | 4 | 5 | 2.0 (88200) |
| tone1 | 1.0 | 2 | 5 | 1.0 (44100) |
| n2    | 2.0 | 2 | 5 | 2.0 (88200) |
| n1    | 1.0 | 10 | 16 | 1.0 (44100) |
| n2    | 2.0 | 1 | 2 | 2.0 (88200) |
| tone2 | 2.0 | brk 1→7 | 8 | 2.0 (88200) |

- **duration_model:** `static` — **sample-exact** in all seven runs (silence replaces the
  omitted wavecycles; nothing is removed).
- **Breakpoints:** `A` brk (`0.0 1 / 2.0 7`, B=8) → exit 0, sample-exact length, differs
  from **both** endpoint scalar renders → **capable** (banner-confirmed: "A may vary over
  time"). `B`: `ERROR: Cannot read parameter 2 [b3_b.brk]: brkpnt_files not permitted.`
- **Runtime constraint:** A=5 B=5 and A=6 B=5 both →
  `ERROR: A > or = B: can't proceed.`
- **Scalar ranges (CDP-enforced):** A 0 / −1 →
  `out of range (1.000000 to 32767.000000)`; B 40000 →
  `ERROR: Parameter[2] Value (40000.000000) out of range (2.000000 to 32768.000000)`
  (that message also pins B's lower bound at 2 — the direct `0 1` probe was masked by
  A=0 being range-checked first). Note the asymmetric maxima (A ≤ 32767, B ≤ 32768),
  consistent with A < B.
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo refused (`Application doesn't work with this type of infile.`) → `mono`.

## 4. extend doublets

Working argv: `extend doublets n2.wav out.wav 0.25 3` — exit 0
(positionals: segdur repets; flag -s).

| input | indur | segdur | repets | outdur (frames) | predicted `repets*(segdur-0.005)*((indur-0.0001)//segdur)` | rel err |
| ----- | ----- | ------ | ------ | --------------- | ------------------------------- | ------- |
| n2 | 2.0 | 0.25 | 3 | 5.1448 (226884) | 5.145 | 0.005% |
| n2 | 2.0 | 0.25 | 2 | 3.4298 (151256) | 3.43  | 0.005% |
| n2 | 2.0 | 0.1  | 3 | 5.4144 (238773) | 5.415 | 0.012% |
| n1 | 1.0 | 0.25 | 3 | 2.2049 (97236)  | 2.205 | 0.005% |
| n1 | 1.0 | 0.5  | 4 | 1.9800 (87316)  | 1.98  | 0.002% |
| n2 | 2.0 | 0.3  | 3 | 5.3098 (234162) | 5.31  | 0.004% |
| n2 | 2.0 | 0.4  | 3 | 4.7399 (209028) | 4.74  | 0.003% |

- **duration_model:** `expression: repets * (segdur - 0.005) * ((indur - 0.0001) //
  segdur)` — sample-exact modulo splice quantisation (each written repetition is
  `round(segdur*srate) − 221` frames at 44.1 kHz). Mechanism source-confirmed in
  `dev/extend/iterate.c do_doubling` + `extdcon.h` (`SPLICEDUR (5 * MS_TO_SECS)`): each
  repetition loses one fixed 5 ms crossfade splice, and the **final segment — partial or
  exactly boundary-aligned — is silently dropped** (the write is skipped whenever the
  input runs out during a segment's build, including exactly at its end). `//` verified
  to evaluate under the repo's simpleeval.
- **ZERO-LENGTH OUTPUT (first-class finding):** segdur equal to the input duration (the
  allowed maximum) → exit 0, **0-frame output file**, plus
  `WARNING: Can't close output sf-soundfile : can't truncate SFfile`.
- **Breakpoints:** `segdur` brk (`0.0 0.1 / 2.0 0.4`) → exit 0 (5.7862 s), differs from
  **both** endpoint scalar renders → **capable** (banner-confirmed: "can vary through
  time"; the envelope's time axis advances by segdur − 0.005 per consumed segment ≈ input
  time). `repets`:
  `ERROR: Cannot read parameter 2 [b3_rp.brk]: brkpnt_files not permitted.`
- **Scalar ranges (CDP-enforced):** repets 0 / 1 / 33 →
  `out of range (2.000000 to 32.000000)`; segdur 0.005 / 3.0 (on a 2 s file) →
  `out of range (0.010000 to 2.000000)` (max = indur, input-dependent).
- **-s (sync) flag:** exit 0, output 2.2049 s from a 2 s input at 0.25/3 — "tries" to
  stay synchronised (near, not exactly, the input length); model assumes -s off.
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo accepted (226884 frames × 2 ch, same frame count as mono) → `any`.

## 5. bounce bounce

Working argv: `bounce bounce n1.wav out.wav 3 0.5 0.8 0.5 1` — exit 0
(positionals: count startgap shorten endlevel ewarp; flags -s<min> -c -e).

| input | indur | count | startgap | shorten | ewarp | outdur (frames) | predicted | rel err |
| ----- | ----- | ----- | -------- | ------- | ----- | --------------- | --------- | ------- |
| n1 | 1.0 | 3 | 0.5  | 0.8 | 1 | 1.7320 (76382)  | 1.732   | 0.001% |
| n1 | 1.0 | 5 | 0.5  | 1.0 | 1 | 3.5000 (154350) | 3.5     | 0.000% |
| n1 | 1.0 | 5 | 0.5  | 0.8 | 1 | 2.0085 (88574)  | 2.00848 | 0.000% |
| n2 | 2.0 | 3 | 0.5  | 0.8 | 1 | 2.2440 (98962)  | 2.244   | 0.002% |
| n1 | 1.0 | 3 | 1.0  | 0.5 | 1 | 1.8750 (82688)  | 1.875   | 0.001% |
| n1 | 1.0 | 8 | 0.25 | 0.7 | 2 | 0.8430 (37175)  | 0.84279 | 0.004% |

- **duration_model:** `expression: startgap * count + indur if shorten == 1 else
  startgap * (1 - shorten ** count) / (1 - shorten) + indur * shorten ** count` — worst
  error 0.004%. Semantics: gap k (start-to-start) is `startgap * shorten^(k-1)`, and **by
  default each repeated element is itself shrunk** to `indur * shorten^k` (the file ends
  when the last, shortest bounce ends). ewarp and endlevel verified duration-neutral.
  The ternary was verified to evaluate under the repo's simpleeval (`shorten == 1` takes
  the linear branch, avoiding the closed form's division by zero).
- **Flag divergences from the model (all measured, documented in the entry):**
  - `-s0` (shrinkage OFF): 2.2200 s vs modelled 1.732 — output becomes gap-sum + indur.
  - `-s0.2` with elements never reaching the floor: **byte-identical** to the unflagged
    run (the flag is a shrinkage floor, inert until hit; the unflagged default is full
    shrinkage).
  - `-c` (cut overlap, n2 run): 1.4760 s vs 2.244 — last element truncated one gap-length
    after the final bounce start.
  - `-e` (trim start): same duration as unflagged (76382 frames), different render.
  - `-c -e` together: **accepted** (exit 0, distinct render from `-c` alone) despite the
    manual's "WARNING: do not set both -c and -e flags."
- **Scalar ranges (CDP-enforced):** count 0 / 101 → `out of range (1.000000 to
  100.000000)` (count 1 works); startgap 0.03 / 11 → `out of range (0.040000 to
  10.000000)`; shorten 0.05 / 1.5 → `out of range (0.100000 to 1.000000)`; endlevel −0.1
  / 1.5 → `out of range (0.000000 to 1.000000)`; ewarp 101 → `out of range (0.010000 to
  100.000000)` and 0.05 **accepted** — **DIVERGENCE:** cgroextd.htm gives ewarp's range
  as "0.1 to 100"; the binary enforces 0.01-100. shrink `-s1.5` →
  `ERROR: Parameter[6] Value (1.500000) out of range (0.000000 to 1.000000)`.
- **Breakpoint probes (all 6 refused):**
  - count: `ERROR: Cannot read parameter 1 [b3_ct.brk]: brkpnt_files not permitted.`
  - startgap: `ERROR: Cannot read parameter 2 [b3_sg.brk]: brkpnt_files not permitted.`
  - shorten: `ERROR: Cannot read parameter 3 [b3_sh.brk]: brkpnt_files not permitted.`
  - endlevel: `ERROR: Cannot read parameter 4 [b3_el.brk]: brkpnt_files not permitted.`
  - ewarp: `ERROR: Cannot read parameter 5 [b3_ew.brk]: brkpnt_files not permitted.`
  - shrink (`-s`): `ERROR: Cannot read parameter 6 [b3_sm.brk]: brkpnt_files not permitted.`
- **Determinism:** two runs 1.1 s apart → identical decoded shas. Not stochastic.
- **Channels:** stereo accepted (st2 → 2.2440 s, 2 ch — model holds) → `any`.
- **Banner note:** unlike the Groucho-era programs, `bounce` prints no "CDP Release"
  version line.

## 6. texture simple, mode 5 — DROPPED (schema gap: aux notedata file)

Working argv: `texture simple 5 n2.wav out.wav nd.txt 5 0.25 0.3 0 1 1 64 64 0.2 0.5 60
60 0` — exit 0, where `nd.txt` contains the single line `60` (mode 5 "NONE" needs only
the assumed MIDI pitch of each input sound; modes 1-4 additionally need a harmonic
field/set NOTELIST). Probed fully, then dropped — see the verdict below.

| input | outdur param | packing | scatter | maxdur | outdur actual (ch) |
| ----- | ------------ | ------- | ------- | ------ | ------------------ |
| n2 | 5 | 0.25 | 0.3 | 0.5 | 5.1582 (2 ch) |
| n2 | 3 | 0.25 | 0.3 | 0.5 | 3.1714 (2 ch) |
| n2 | 8 | 0.25 | 0.3 | 0.5 | 7.9443 (2 ch) |
| n1 | 5 | 0.25 | 0.3 | 0.5 | 5.1124 (2 ch) |
| n2 | 5 | 0.25 | 0.3 | 1.5 | 5.8331 (2 ch) |
| n2 | 5 | 0.1  | 2.0 | 0.5 | 5.2275 (2 ch) |

- **duration_model (had it shipped):** `set_by outdur`, honestly bounded: observed
  −0.7% to +16.7% around the outdur parameter (overshoot grows with maxdur; the last
  event's tail extends past the grid). **DIVERGENCE:** the banner calls outdur the
  "(min) duration of outfile", but unseeded renders came in *below* it (7.9443 from 8) —
  the "minimum" is not strictly honoured. Duration varies run-to-run when unseeded (the
  event count/placement is stochastic).
- **GENUINELY STOCHASTIC, WORKING SEED (contrast with modify revecho's no-op):**
  unseeded runs 1.1 s apart → **different** decoded shas *and different frame counts*
  (224103 vs 224582); `-r5` twice, 1.1 s apart → **identical**; `-r5` vs `-r9` →
  different; seeded ≠ unseeded. Would have been curated `stochastic: true` with a
  functioning seed parameter.
- **Output is STEREO from a mono input** (all runs 2 ch; -p position / -s spread place
  events in a stereo image). Stereo *input* refused:
  `Application doesn't work with this type of infile.` → mono in, stereo out.
- **Breakpoints (spot probes, manual: "All parameters except notedata, outdur and seed
  may vary over time"):** packing brk (`0.0 0.1 / 5.0 0.5`, seed 5) → exit 0, differs
  from both endpoint scalar renders at the same seed → **capable**. outdur brk →
  `ERROR: Cannot read parameter 1 [b3_od.brk]: brkpnt_files not permitted.`
- **Scalar ranges (spot probes, CDP-enforced):** packing 0 →
  `ERROR: Parameter[3] Value (0.000000) out of range (0.000023 to 60.000000)`; omit 65 →
  `ERROR: Parameter[14] Value (65.000000) out of range (0.000000 to 64.000000)`.
- **VERDICT — DROPPED (schema gap):** the required `notedata` argv slot (between outfile
  and outdur) is an auxiliary *text* file, not a numeric parameter and not a breakpoint
  envelope. Under the current schema there is no clean expression: `validate_params`
  rejects any str value not ending in `.brk`, and a `.brk`-named notedata file would be
  routed through the breakpoint compiler (read, hashed and validated as time/value
  pairs — which a notedata file is not). Even mode 5's one-line pitch file cannot be
  passed. **Recommendation:** add an `aux_file` ParameterSpec type — a str path param
  that `validate_params` accepts as-is, `build_cdp_argv` renders at its positional slot
  (cwd-relativised like other paths), and lineage records by content hash; the engine's
  `write_data_file` tool already produces exactly these files. With that in place this
  entry (and the rest of the TEXTURE suite, plus modify stack's per-layer transposition
  file form) becomes expressible. An honest omission beats a broken entry.

---

## Final row confirmations (exact pinned params, noise inputs)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| modify stack, transpos −12/count 3/lean 1/atk_offset 0/gain 1/dur 1, indur 2.0 | 8.0 | 8.0000 | 0.0003% |
| distort divide (static), divider 2, indur 2.0 | 2.0 | 1.9999 | 0.003% |
| distort omit (static), omit 2/group 5, indur 2.0 | 2.0 | 2.0000 | 0.000% |
| extend doublets, segdur 0.25/repets 3, indur 2.0 | 5.145 | 5.1448 | 0.005% |
| bounce bounce, count 3/startgap 0.5/shorten 0.8/endlevel 0.5/ewarp 1, indur 2.0 | 2.244 | 2.2440 | 0.002% |

Five of six entries shipped; texture simple dropped with a documented schema-gap
recommendation (`aux_file` parameter type).
