# Tranche 23 — text-data utilities probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (`-fsigned-char` rebuild — CDP textfile parsing
  works), Linux x86_64 sandbox. Fixtures in `/tmp/probe23b`; every probe wrapped in
  `timeout 30` (60 for renders).
- **Inputs:** python-soundfile mono float32 — `tone2` (440 Hz, 2.0 s, peak 0.5),
  `tone1` (1.0 s), `n2` (noise 2.0 s), `st2` (stereo noise 2.0 s); text fixtures inline
  per section.
- **Methodology:** tranche-2 verbatim where applicable; these are mostly data->data, so
  the empirical duties shift to format pins, verbatim refusal quotes, and round-trips.
  Data-output/data-input precedents: envel envtobrk/brktoenv, peakfind, oneform get.
- Refusals quoted verbatim. Deterministic comparisons on decoded samples (audio) or
  bytes (text), unseeded pairs launched > 1.1 s apart.

## 0. The mode-token gate (kills most of the tranche)

`build_cdp_argv` unconditionally emits `[program, mode, ...]` (processing.py:296).
CDP8-standard programs take a mode word (`peakfind peakfind ...` verified); the old
standalone tabedit/science utilities take NONE — their argv[1] is a file. Tolerance
probed per binary (all worked plainly first, then refused a doubled-name token):

| program | plain run | doubled-name token | verdict |
| ------- | --------- | ------------------ | ------- |
| getcol  | `getcol multi.txt gc_o.txt 2` exit 0, column 2 extracted | `ERROR: Cannot open file 'getcol'` exit 1 | **engine-gap drop** |
| putcol  | `putcol times.txt multi.txt pc_o.txt 2 -r` exit 0 (note: output double-spaces lines) | `ERROR: Cannot open file 'putcol'` exit 1 | **engine-gap drop** (also mandatory `-r|-i` choice flag) |
| columns | `columns times.txt col_m.txt -m2` exit 0 (values doubled); `-a0.5`, `-t` (total, to stdout with no outfile) verified | `Cannot open infile columns` exit 1 | **engine-gap drop** |
| vectors | `vectors v1.txt v2.txt vad.txt -a` exit 0 (11/22/33/44) | name token shifts every slot: `ERROR: Cannot read flag 'vad2.txt'.` exit 1 | **engine-gap drop** |
| cubicspline | `cubicspline spec.txt cs_o.txt 32 44100` exit 0 (3922-line frq/amp curve) | `CANNOT OPEN DATAFILE cubicspline` exit 255 | **engine-gap drop** |
| smooth  | same shape, exit 0 (same grid, different values: 0.6229 vs 0.6010 at the first interior point — spline vs linear smoothing) | `CANNOT OPEN DATAFILE smooth` exit 255 | **engine-gap drop** |
| newscales | see §1 | usage + exit 255 | **drop** (multi-output too) |

Flag-first was also probed for columns (would have let `mode` carry a valueless op
flag): `columns -o unsorted.txt srt.txt` → `Cannot open infile -o` exit 1. argv[1] is
unconditionally the infile. No expressible form exists.

**columns family enumeration (recorded for the drop):** `columns -f` lists ~100 ops
across -g/-l/-m/-M/-R screens — arithmetic (a/m/d/P, quantise q, approx A), list ops
(o sort, rr reverse, I interleave, ed dupl-elim), musical (Mh/hM midi<->hz, i intervals,
Ir interval->ratio, Th/TM tempering, At/Ad accelerating time/duration seqs, Tc/Tl
tempo->times, td density, st sample->time, DB/db), random (Ro/Ra/RA/Rm/Rs/Rc/Re/Rg/Rv).
The musically load-bearing subset (At/Ad/Tc/Tl time-list generation for
timeline/clicknew/retime; Mh/hM/q/Th for pitch lists) is exactly what the mode-token
gap forecloses; `-J` juxtapose additionally modifies infile1 IN PLACE, `-S/-N` are
multi-output. Failure exits are also unreliable (`Cannot open infile` cases exit 1, but
success prints to stdout when no outfile — tsconvert-class contract risks throughout).

## 1. newscales — drop (multi-output + no mode token)

- 2-note datafile + 3-line spectrumfile → `ERROR: No. of lines of spectral data (3)
  does NOT = no. of notes entered (2).` (spectrum must be 1 line or one per note).
- Working run (`newscales nsout notes.txt harmline.txt 44100`, exit 0) wrote
  **`nsout0.wav` and `nsout1.wav`** — one soundfile PER NOTE from a stem that "must not
  end with a number". No single-outfile argv exists → standing multi-output drop.
- Doubled-name token: usage + exit 255.

## 2. histconv — drop (toolkit plumbing, out of scope)

Source (`dev/misc/histconv.c`): parses Sound Loom usage-histogram lines (`#...cdprog`
paths + program/mode NUMBERS) and rewrites them as names via `get_progname`/
`get_modename`. It is the tkusage histogram converter — toolkit plumbing per the
standing scope decision. (Also modeless argv `histconv infile outfile`, so the
mode-token gap applies anyway. A junk probe exits 0 and echoes joined words — no
data-file use.)

## 3. matrix (dev/standnew/unitary_matrix.c) — modes enumerated, 2/3/4 curated

`matrix matrix <mode>` — .wav in, .wav out (runs its own FFT/overlap-add; no PVOC).
Mode gate verbatim: `Program mode value [5] is out of range [1 - 4].`

- **Mode 1 (make) — drop:** `matrix matrix 1 tone2.wav mxout 1024 3` exit 0 writes TWO
  files (`mxout.wav` + `mxout.txt`, 524289 lines) from a stem — multi-output. Matrix is
  RANDOM and clock-seeded (`initrand48()` = `srand(time(0))` at unitary_matrix.c:1434,
  osbind shim): two runs' matrices differ, no seed argv. Also clipped hard: `WARNING:
  60751 samples overflowed... maximum sample was 16.590696 ... use gain of <= 0.060261`.
- **Mode 2 (use) — CURATED:** `matrix matrix 2 infile outfile inmatrixfile [-c]` — the
  matrix file rides the post-output aux slot; analchans/winoverlap are READ FROM THE
  FILE (format, source-pinned at :46: line 1 = overlap 1-4, then N*N complex entries as
  real/imag line pairs; analchans-4 matrix = 9 lines, verified reapplied to multiple
  inputs). Hand-made junk refuses `ERROR: WARNING: Matrix data does not have zeros on
  the diagonal. Not a unitary matrix.` Deterministic for a fixed matrix (byte-identical
  1.3 s apart); `-c` (cyclic: window n gets matrix^n) verified distinct. Re-applying
  mode 1's own matrix does NOT byte-reproduce mode 1's sound (shas 464d0750... vs
  db6566c7...). Levels are matrix-dependent (tiny matrix peak 0.754; 1024-matrix clipped
  as above). Stereo refused `ERROR: File st2.wav is not MONO`.
- **Mode 3 (exchange reals/imags; source :1880) — CURATED:** 440 Hz tone → energy at
  ~421/507 Hz (FFT-verified); RMS 0.348→0.255, peak ~0.5, no clipping. Deterministic.
  Durations sample-exact static: 2.0→2.0000 (tone + noise), 1.0→1.0000.
- **Mode 4 (invert phase; source :1886 negates imags = per-window conjugation =
  window-wise time reversal) — CURATED:** distinct from input and from mode 3 (shas);
  same RMS drop; deterministic (byte-identical 1.3 s apart).
- **Ranges (all verbatim):** analchans `Parameter[1] Value (1.000000) out of range
  (2.000000 to 32768.000000)` (65536 same quote) — **banner '4-16384' wrong at BOTH
  ends**; 2 renders with `WARNING: analWindow impulse response is too small / Decimation
  too low: adjusted`; 32768 renders. Non-pow-2: `ERROR: Number of analysis channels must
  be a power of 2`. winoverlap `Parameter[2] Value (5.000000) out of range (1.000000 to
  4.000000)` (0 same).
- **Breakpoints refused:** analchans `Cannot read parameter 1 [b_ac.brk]: brkpnt_files
  not permitted.`; winoverlap parameter 2 (same wording). `-c` on mode 3: `Unknown flag
  -c on command line.`
- **Channels:** mono only (refusal above) → `mono`.

## 4. hfperm — hfchords 1 & 4 curated; delperm/delperm2 dead; mode 2 multi-output

### 4a. Input-typing landmine (applies to every hfperm mode; source-diagnosed)

`hfperm hfchords 3 midi.txt ...` with `60\n64\n67\n72\n` refused `Application doesn't
work with this type of infile.` — cdparse types an EVEN-count list whose odd-position
values ascend as a possible breakpoint file, and only the NUMLIST typing validates
hfperm (`cdp2k/validate.c:603` — `NUMLIST_OR_[LINELIST_OR_]WORDLIST` validates
HF_PERM1/2 + DEL_PERM/2; the TRANSPOS/PITCH-brkfile compound types do not). Verified:
{60,64,67,72} refused; {64,60,72,67} refused (odd positions 64,72 still ascend);
{60,64,67,72,76} (odd count) PASSES; {76,72,67,64,60,55} (even, descending) PASSES.
Always-safe forms: odd counts or descending order. ';' comment line: accepted,
byte-identical output.

### 4b. hfchords mode 3/4 argv — banner lies about srate

Banner: `hfchords 3-4 ifil ofil sr min bn bo tn to srt`. With sr passed: `ERROR:
Parameter[1] Value (44100.000000) out of range (1.000000 to 48.000000)` (that's
minset's gate). Real argv: `ifil ofil min bn bo tn to srt [-m -s -a -o]`. Refusal slot
numbers still quote the mode-1 table (minset = parameter 5, sortby = parameter 10).

### 4c. hfchords 4 (MIDI text out) — CURATED

- `hfperm hfchords 4 midi5.txt hfc4.txt 2 0 0 0 1 0` exit 0 → 7 clean lines
  (`60  67  ` ... `64  67  72  `, cat -A verified; 'Sorting chords...' prose is stdout
  only). Deterministic byte-identical (1.2 s apart).
- Fractional input 60.5 → output `60` (ROUNDED, verified).
- `-m` with minset 3: only the two triads emitted (verified). Breakpoints refused:
  minset `Cannot read parameter 5`, sortby `Cannot read parameter 10`.
- **Round-trip (binary level):** `synth chord 1 sc.wav hfc4.txt 44100 1 2.0 -a0.5`
  exit 0 — the whole file renders as the union field; FFT peaks 261.5/329.5/392.0/523.5
  Hz = C4/E4/G4/C5. Re-verified through process_impl (§6).

### 4d. hfchords 1 (single soundfile of all chords) — CURATED

- `hfperm hfchords 1 midi5.txt hfc1.wav 44100 0.3 0.1 0.5 2 0 0 0 1 0` exit 0 → ONE
  wav, 4.8416 s, peak 0.800, deterministic (decoded-identical 1.3 s apart). First chord
  spectrum 260/392(+785/1177 harmonics) — harmonic-rich tone, chords voiced in the
  bn/bo..tn/to window. 6-note octave-spanning input produced the identical chord set as
  the 5-note reduction (pitch classes rule).
- **Ranges (all verbatim):** srate `(16000.000000 to 96000.000000)` — CONTINUOUS:
  22050/48000/96000 all render (no synth-family discrete set); notedur `(0.040000 to
  10.000000)`; gapdur `Parameter[3] ... (0.020000 to 10.000000)`; pausedur
  `Parameter[4] ... (0.020000 to 10.000000)`; minset `(1.000000 to 48.000000)`;
  bottomnote `Parameter[6] ... (0.000000 to 11.000000)`; bottomoctave `Parameter[7]
  ... (-4.000000 to 4.000000)`; sortby `Parameter[10] ... (0.000000 to 4.000000)`.
- **Content cap:** minset 6 on 5 notes (3 pitch classes): `ERROR: Minimum size of note
  set (3) (after octave duplication elimination)`. Bad list value 300: `ERROR: INVALID
  DATA / ERROR: Cannot proceed`.
- **Breakpoints refused:** srate parameter 1, notedur parameter 2 (`Cannot read
  parameter 2 [b_nd.brk]: brkpnt_files not permitted.`), minset parameter 5, sortby
  parameter 10.
- Flags `-m -s -a -o` accepted together (exit 0). Mode gate: `Program mode value [5] is
  out of range [1 - 4].`
- Duration is combinatorial → duration_model expression names the aux param (`notes`),
  engaging the aux-param pre-flight skip (clicknew pattern); duration_row excluded.

### 4e. Drops within hfperm

- **hfchords 2** (grouped chords to several sndfiles): stem `grp.wav` wrote grp0.wav,
  grp1.wav, grp2.wav... (verified, exit 0) — multi-output, no single outfile argv.
- **delperm / delperm2 — DEAD BY DESIGN:** every invocation (with or without the
  banner's `0` mode digit) exits 255 `ERROR: ERROR: This program is currently
  malfunctioning.` Source: `gen_dp_output` opens with an unconditional
  `sprintf(errstr,"ERROR: This program is currently malfunctioning.\n"); return
  (PROGRAM_ERROR);` dated `/* JUNE 2004 */` (dev/hfperm/hfperm.c:1865) — TW's own
  kill-switch, unreachable code behind it. (With the mode digit passed, argv shifts and
  it dies earlier: `ERROR: Can't open file 0 to read data.`)
- **hfchords2** (chords from the notes AS VOICED, no range window): verified working —
  `hfperm hfchords2 4 midi5.txt h2c4.txt 2 0` exit 0 (`60  76  / 60  72  / ...`). Not
  curated (scope trim); recorded as an execute() sibling in both curated entries.

## 5. Pinned-row confirmations

| row | predicted | actual | note |
| --- | --------- | ------ | ---- |
| matrix matrix 3, analchans 1024/winoverlap 3, indur 2.0 | 2.0 | 2.0000 | sample-exact |
| matrix matrix 4, analchans 1024/winoverlap 3, indur 2.0 | 2.0 | 2.0000 | sample-exact |
| matrix matrix 2, inmatrixfile mtx4.txt (aux), indur 2.0 | 2.0 | 2.0000 | sample-exact; aux content in findings |
| hfperm hfchords 1 | — | 4.8416 | aux-driven combinatorial; row excluded |
| hfperm hfchords 4 | — | — | data output; row excluded |

## 6. process_impl spot-checks (engine level)

Run against the repo's `process_impl` with a temp sessions root and
CDP_PATH=/tmp/CDP8/NewRelease (harness mirrors tests/test_curation_formulas.py):

1. `matrix matrix 3` on a 2 s noise input → status ok, 2.0000 s wav.
2. `hfperm hfchords 4` (arity 0, notes aux `field.txt` = '69 67 64 62 60' descending)
   → status ok, .txt output, 41 chord lines ('60  69  ' / '60  67  ' / ...).
3. **Producer->consumer round-trip:** the step-2 OUTPUT PATH fed as curated
   `synth chord 1`'s `datafile` → status ok, 2.0000 s render; FFT top peaks
   261.5/293.5/329.5/392.0/440.0 Hz = C4 D4 E4 G4 A4 — exactly the pentatonic field
   {60,62,64,67,69}. Pinned in both entries.
4. `matrix matrix 2` with the 9-line analchans-4 matrix (`mtx4.txt`, content in the
   findings `duration_row_aux`) in the session data dir → status ok, 2.0000 s, peak
   0.796.

Loader after entry-writing: 431/432 entries (a parallel agent's entries appear), ZERO
malformed warnings; all five new triples resolve distinctly by exact
(program, mode, submode).

## Verdict

Curated 5: matrix matrix 2/3/4, hfperm hfchords 1/4.
Dropped 12 (evidence above): columns (family, ~100 ops enumerated), getcol, putcol,
vectors, cubicspline, smooth, newscales, histconv, matrix 1, hfperm hfchords 2,
hfperm delperm, hfperm delperm2. Recorded execute()-reachable siblings: hfperm
hfchords 3 (note-name score), hfperm hfchords2 (all modes).
