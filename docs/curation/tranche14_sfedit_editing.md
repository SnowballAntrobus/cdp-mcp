# Tranche 14 — sfedit depth + editing utilities probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (rebuilt 2026-07-15 with `-fsigned-char`, forensics
  P6-1 — textfile inputs parse on aarch64), Linux sandbox. Re-verified on macOS r8 by the
  CDP-gated suite after integration.
- **Inputs:** synthesized in `/tmp/probe14a` via python-soundfile, mono 44.1 kHz float32:
  noise bursts `n1/n2/n3` (1/2/3 s, 50 ms edge ramps + slow AM), tones `tone1/tone2`
  (440 Hz), stereo noise `st2` (2 s), multi-event `ev4` (3 s, four bursts at peaks
  .48/.25/.55/.39 with true silences), tone/hiss/tone `nt3` (2.1 s, hiss highpassed at
  6 kHz), glitch fixture `gl2` (2 s, tones + 4 ms click at 0.9 s in a silent gap),
  end-click fixture `ec2` (2 s, clicks at 2 ms and 1.9 s, body 0.4–1.4), flat noise
  `flat2` (matches the suite's `_write_noise`: standard-normal ×0.2, no ramps).
- **Methodology:** tranche-2 verbatim. Breakpoint proof = brk render differs from BOTH
  scalar endpoint renders; determinism = sha256 of float64-decoded samples, runs > 1.1 s
  apart; refusals quoted verbatim; fresh output names throughout.

---

## 1. sfedit cutend, submode 1 — CURATED

Working argv: `sfedit cutend 1 n2.wav out.wav 0.75` — exit 0.

| input | length | splice | frames | outdur | predicted `length` |
| ----- | ------ | ------ | ------ | ------ | ------------------ |
| n2 | 0.75 | dflt | 33075 | 0.75 | 0.75 |
| n2 | 1.5  | dflt | 66150 | 1.5  | 1.5 |
| n1 | 0.4  | dflt | 17640 | 0.4  | 0.4 |
| st2 | 0.75 | dflt | 33075 (2ch) | 0.75 | 0.75 |
| n2 | 0.75 | -w0 / -w100 | 33075 | 0.75 | 0.75 |
| flat2 | 0.75 | dflt | 33075 | 0.75 | 0.75 |

- **duration_model** `length` — sample-exact everywhere. `-w0` output allclose to
  `input[-length:]` (max diff 0.0); default splice: first sample 0.0, interior bit-equal.
- Ranges: length 2.5 on 2 s → `Parameter[1] Value (2.500000) out of range (0.000000 to
  2.000000)`; length 0 → `Edited portion is too short for specified splicelen.`;
  `-w-1`/`-w5001` → `Parameter[2] ... (0.000000 to 5000.000000)`; `-w600` on a 0.5 s keep
  → splicelen abort.
- Breakpoints refused: length `Cannot read parameter 1`; splice `Cannot read parameter 3`
  (numbering mismatch vs its `Parameter[2]` range refusal). Submodes 2/3 verified working
  (sample / grouped-sample counts). Deterministic; stereo accepted.

## 2. sfedit zcut, submode 1 — CURATED

Working argv: `sfedit zcut 1 tone2.wav out.wav 0.5 1.5` — exit 0.

- Durations: tone 0.5–1.5 → 44100 frames exactly; noise → 44099 (crossing snap −1);
  tone1 0.2–0.9 → 30870; submode 2 (`22050 66150`) → 44100.
- **Swap divergence:** `1.5 0.5` → `WARNING: end cut before startcut: reversing these
  times.` then exit 0, byte-identical to ordered call — zcut WARNS where sfedit cut swaps
  silently.
- Stereo refused `Application doesn't work with this type of infile.` → mono. start==end →
  `endcut = startcut: No cutting possible.`; end 2.5 → range 0–2 refusal. Brks refused
  params 1–2. No splice parameter. Deterministic.

## 3. sfedit zcuts — DROPPED (multi-output)

`sfedit zcuts 1 n2.wav zcs_out.wav zcts.txt` (3 time-pairs) → exit 0, writes
`zcs_out1.wav zcs_out2.wav zcs_out3.wav` (0.3/0.4/0.4 s); **`zcs_out.wav` is never
created** (ls confirms absent). One numbered file per pair, numbered from 1, index
inserted before `.wav`. Engine-incompatible; execute() with cwd control.

## 4. sfedit excises, submode 1 — CURATED

Working argv: `sfedit excises 1 n2.wav out.wav exc.txt` (exc.txt = `0.3 0.5` / `1.0 1.4`).

- Durations: 2.0 − 0.6 → **1.4000 (61740 frames, sample-exact)**; 3.0 → 2.4000; stereo
  1.4000; `-w0` identical length and allclose to numpy concat of kept regions (max diff 0).
- **Divergence from single excise:** end beyond EOF is CLAMPED — `0.3 2.5` on 2 s → exit 0,
  0.3075 s (excise refuses).
- Datafile refusals verbatim: out-of-order rows `Start and end of excised portions 1 & 2
  overlap.`; odd count `Start and End times not paired correctly in textfile exc_odd.txt`.
- splice brk → `Cannot read parameter 3 ... brkpnt_files not permitted.`; `-w-1` →
  `(0.000000 to 5000.000000)`. Submode 2 (sample counts) verified → 61740 frames.
  Deterministic. Model = aux skip sentinel (`excisefile`); duration row null.

## 5. sfedit masks, submode 1 — CURATED

Working argv: `sfedit masks 1 n2.wav out.wav exc.txt` — exit 0.

- **Static**, sample-exact: 2.0 → 2.0 (also 1.0, stereo, and with a region reaching past
  EOF: `1.8 2.5` → exit 0, 2.0). `-w0`: masked zones max |sample| = 0.0; unmasked samples
  bit-equal (row-index reference).
- Reversed pair → `starttime <= endtime for excise 1` (says "excise" — shared reader).
  `-w300` on a 0.2 s region → `Excised segment 1 too short for splices (shorten
  splices?)`. `-w5001` → 0–5000 refusal; splice brk → parameter 3. Deterministic.
- Duration row uses aux file `exc14.txt` = `0.3 0.5\n1.0 1.4\n` (static, so the row is
  assertable despite the aux param).

## 6. sfedit insert, submode 1 — CURATED

Working argv: `sfedit insert 1 n2.wav n1.wav out.wav 0.8` — exit 0.

| host | insert | time | splice | outdur | predicted `indur1+indur2-splice/1000` |
| ---- | ------ | ---- | ------ | ------ | ------ |
| n2 (2.0) | n1 (1.0) | 0.8 | dflt 15 | 2.985 (131638) | 2.985 |
| n3 (3.0) | n1 | 0.8 | dflt | 3.985 | 3.985 |
| n2 | n1 | 0.8 | -w0 | 3.0000 | 3.0 |
| n2 | n1 | 0.8 | -w100 | 2.9 | 2.9 |
| st2 | st2 | 0.8 | dflt | 3.985 (2ch) | 3.985 |

- `-w0` output allclose to `host[0:t]+insert+host[t:]` (max diff 0). `-o` (overwrite):
  output exactly 2.0000 = indur1 (model excluded). `-l0.5` works; level range verbatim
  `(0.000002 to 128.000000)`; time 1.99 → `Insert time beyond end of infile (allowing for
  splice)`; time 2.5 → range 0–2. Channel mismatch → `Incompatible channel-count in input
  file n1.wav.`. Brks refused: time 1, splice 3, level 4. Deterministic.

## 7. sfedit replace, submode 1 — CURATED

Working argv: `sfedit replace 1 n2.wav n1.wav out.wav 0.5 1.2` — exit 0.

- Durations: 2.0 − 0.7 + 1.0 → **2.3000 (101430 frames, sample-exact)**; 3 s host → 3.3;
  **splice-independent** (−w0/−w100 both 101430). `-w0` allclose to
  `host[0:0.5]+insert+host[1.2:]`.
- **REVERSED-BOUNDS LANDMINE (first-class):** `1.2 0.5` → exit 0, NO warning, output
  3.7000 s = indur1 + 0.7 + indur2 — the negative span EXTENDS the file, duplicating host
  material. No sibling behaves this way (cut/excise swap silently, zcut warns+swaps).
- endtime 2.0 → `Overwrite endtime is beyond end of infile (allowing for splice)`;
  endtime 2.5 → range 0–2; `-l200` → `Parameter[4] Value (200.000000) out of range
  (0.000002 to 128.000000)`. Brks refused params 1–4. Stereo+stereo exit 0. Deterministic.

## 8. sfedit insil, submode 1 — CURATED

Working argv: `sfedit insil 1 n2.wav out.wav 0.8 0.5` — exit 0.

| input | time | dur | splice | outdur | predicted `indur+duration-splice/1000` |
| ----- | ---- | --- | ------ | ------ | ------ |
| n2 | 0.8 | 0.5 | dflt | 2.485 (109588) | 2.485 |
| n1 | 0.5 | 1.0 | dflt | 1.985 | 1.985 |
| n2 | 0.8 | 0.5 | -w0 | 2.5000 | 2.5 |
| n2 | 0.8 | 0.5 | -w100 | 2.4 | 2.4 |
| st2 | 0.8 | 0.5 | dflt | 2.485 (2ch) | 2.485 |

- `-w0`: inserted zone exactly 0.0, flanks bit-equal. `-o` → exactly 2.0000 (static;
  model excluded). `-o` at 1.8+0.5 → `Insertion will cut off entire end of file: use
  sfedit cut`; with `-s` → WARNING `Insertion will cut sound at end of file: leaving a
  silent section there.`, exit 0, 2.485.
- **END-PAD BUG (first-class):** time 2.0 (== indur) → exit 0 but **4.0000 s** (appended
  silence = INDUR, not duration; head bit-equal, tail all-zero); time 1.99 → 3.99;
  1.5/1.9/1.95 all normal (2.485). duration 0 → `Inserted silence is too short for
  splices.` Brks refused params 1–3. Deterministic.

## 9. sfedit masks/excises shared: see 4–5. sfedit cutmany — DROPPED (multi-output)

`sfedit cutmany 1 n2.wav cm_a.wav cm.txt 15` (3 pairs) → exit 0, writes `cm_a1.wav
cm_a2.wav cm_a3.wav` (0.3/0.4/0.4 s); **`cm_a.wav` never created**. Same contract as
zcuts (numbered from 1). Splice-slot brk → `Cannot read parameter 1`. execute() only.

## 10. sfedit syllables — DROPPED (multi-output)

`sfedit syllables 1 n2.wav sylo.wav sylc.txt 20 15` (4 cut times) → exit 0, writes
`sylo1.wav sylo2.wav sylo3.wav` (0.33/0.33/0.43 s — dovetail overlaps); **`sylo.wav`
never created**. execute() only.

## 11. sfedit noisecut — CURATED

Working argv: `sfedit noisecut nt3.wav out.wav 15 6000 0.05 0.05` — exit 0.

- Static: 2.0999 → 2.0999; gl2 2.0 → 2.0. Content: hiss zone replaced by an exact zero
  run (1.116–1.403 s); tone RMS unchanged. `-n` inverts (zero fraction 0.14 → 0.76).
- **ALL-NOISE COLLAPSE:** flat2 → exit 0, **0-frame output**. Duration row therefore uses
  the static model but is EXCLUDED from the flat-noise suite fixture — row null, reason
  recorded (all-noise input yields an empty file).
- Stereo refused `Application doesn't work with this type of infile.` → mono. Ranges
  verbatim: splicelen `(0.000000 to 50.000000)` (tight!); noisfrq `(1000.000000 to
  22050.000000)`; maxnoise `(0.000000 to 50.000000)`; mintone `(0.000000 to
  1000.000000)`. Brks refused params 1–4. Deterministic.

## 12. sfedit joinseq — CURATED

Working argv: `sfedit joinseq n1.wav tone1.wav out.wav pat.txt` — exit 0.

- pat `1 2 1 1` → 3.955 s (174414 frames = 4×1.0 − 3×15 ms, sample-exact); 2 items →
  1.985; `-w0` → 2.0000 exactly, allclose to numpy concat; multi-line pattern
  byte-identical to one-line. st2+st2 → 3.985 (2ch). `-m2` → 1.985 (`-m0` → `(1.000000 to
  32767.000000)`); `-b -e` change content not duration.
- Pattern refusals verbatim: `Number '3' in sequence data does not correspond to any
  input soundfile`, same for '0' (1-based). Channel mismatch refused. `-w5001` →
  `Parameter[2] ... (0.000000 to 5000.000000)`; splice brk → parameter 3. Deterministic.
  Banner quirk: usage line headed `sfedit join`. Model = aux sentinel (`pattern`).

## 13. sfedit joindyn — CURATED

Working argv: `sfedit joindyn n1.wav tone1.wav out.wav dpat.txt` (`1 1.0 2 0.5 1 0.25`).

- 3 items → 2.9700 s (130976 frames, seam rule sample-exact). Gain verified: item-3 peak
  0.1249 = 0.25 × source peak 0.4996. Gain 3.0 ACCEPTED (>1 legal). Odd item count →
  `Data incorrectly paired in file dpat_odd.txt`. Deterministic.

## 14. sfedit twixt — mode 1 CURATED; modes 2/3 pinned; mode 4 DROPPED

Working argv: `sfedit twixt 1 n2.wav tone2.wav out.wav sw.txt 15` (sw = 0/0.5/1/1.5).

- Mode 1 content sample-exact: alternating half-second blocks n2/tone2/n2/tone2 bit-equal
  outside splices. Durations: equal 2 s pair → 2.0; 1 s pair → 1.0; n2+tone1 → 1.0;
  n3+tone2 → 2.0 → **indur_min** (multi-input rule pinned); times past EOF tolerated
  (2.0118, +0.6%).
- **splicelen range verbatim `(2.000000 to 15.000000)`** — tightest in the family; brk →
  `Cannot read parameter 1`. segcnt (modes 2/3) `(1.000000 to 10000.000000)`; weight `-w`
  `(1.000000 to 10.000000)`; `-w3` changes the render.
- **Deterministic-random (first-class):** modes 2/3 byte-identical 1.2 s apart (twice);
  `-r` byte-identical to unflagged. Source: `dev/editsf/twixt.c` draws `drand48()` (lines
  200/425) = osbind.c shim `rand()/RAND_MAX`; `initrand48()` (srand(time)) is called only
  on the randcuts/randchunks paths (`ap_edit.c:966` = randcuts_pconsistency,
  `cut.c:2709` = do_randchunks) — never for twixt/sphinx. No seed argv. version_sensitive.
- Unordered times → `Times 1 (1.000000) and 2 (0.500000) are not in ascending order`;
  channel mismatch refused; mode 1 deterministic.
- **Mode 4 DROP:** `twixt 4 n2.wav tone2.wav tw4_out.wav sw.txt 15` → exit 0 writes chunk 1
  at **tw4_out.wav** (0.5 s) and chunks 2–4 at **tw4_ou1/2/3.wav** (argv stem truncated by
  one char + index from 1, 0.515 s each). Argv file exists but is 1 of 4 — orphan
  outputs; also requires ≥2 infiles despite editing only file 1 (`Insufficient input
  files` with one). execute() only.

## 15. sfedit sphinx — mode 1 CURATED

Working argv: `sfedit sphinx 1 n2.wav tone2.wav out.wav sw2.txt 15` (2 columns × 4 rows).

- Output 1.4000 s = sum of traversed spans; segment 1 bit-equal to file1[0:0.4].
  Column-count mismatch → `Number of data-items per line (1) does not tally with number
  of infiles (2).`; channel mismatch refused; splicelen brk → parameter 1. Mode 1
  deterministic; mode 2 byte-identical 1.2 s apart (segcnt 6 → 3.185 s both) — same
  deterministic-random construction as twixt. Model = aux sentinel (`switchtimes`).

## 16. isolate — DROPPED (all 5 modes, contract pinned) / rejoin — CURATED (mode 2)

**isolate naming contract** (probes in `/tmp/probe14a/iso`):

- Mode 1, `isolate 1 n2.wav iso_a cuts.txt` (cuts 0.3–0.7, 1.1–1.6) → `iso_a0.wav`
  (0.715 s = end of seg 1 + splice; **silent until 0.285 s** = 0.3 − 15 ms splice, segment
  bit-equal to source interior), `iso_a1.wav` (1.615 s), `iso_a2.wav` = **remnant**
  (2.0 s, kept-zones silenced, outside bit-equal). Segments numbered from 0; remnant
  LAST.
- `outnam` with extension: `iso_b.wav` → `iso_b0.wav`... (index before `.wav`). **The
  argv name itself is NEVER created in any mode.**
- Mode 3 (`isolate 3 ev4.wav iso_c -30 -40`) → `iso_c0.wav` (2.865 s, the "ONE output
  file") **plus** `iso_c1.wav` remnant (3.0) — even the single-output mode writes two
  files, and the single output lands at `<outnam>0.wav`, not the argv path → **no
  single-output configuration exists**.
- Mode 4 (3 slices) → `iso_d0..3.wav` (0.5075/1.0075/1.5075/2.0 — each runs from 0 to its
  slice + splice; no remnant); mode 5 adds the 5 ms dovetail (0.52/1.02/1.52/2.0).
- Drop record: engine-incompatible in all 5 modes (self-named multi-output); execute()
  with cwd control; **rejoin is the pair's curated face**.

**rejoin** — working argv: `rejoin rejoin 2 iso_a0.wav iso_a1.wav iso_a2.wav out.wav`.

- **BANNER BUG:** usage line shows no outfile; the last argv IS a required outfile
  (verified created; 1 input + outfile → `Insufficient input files for this process`).
- **ROUND TRIP SAMPLE-EXACT:** rejoin 2 over isolate 1's three files reproduces n2.wav
  with max sample diff 2.98e-08 (float32 epsilon), length equal, corr 1.000000.
- Mode 1 = time-aligned sum: `rejoin 1 iso_a0 iso_a1 out` → 1.615 s = **indur_max**;
  allclose vs numpy sum of the padded segments. Mode 1 with all 3 files byte-identical to
  mode 2 (distinction is -r's remnant exemption; `-r` changes the render).
- `-g3` → `Parameter[1] Value (3.000000) out of range (0.000000 to 1.000000)`; gain brk →
  `Cannot read parameter 1 ... brkpnt_files not permitted.`; channel mismatch refused.
  Two-pass level check: non-clipping sum passes at unity (peak exactly 2× on doubled
  input). Deterministic.

## 17. manysil — CURATED

Working argv: `manysil manysil n2.wav out.wav sild.txt 15` (sild = `0.5 0.3` / `1.2 0.5`).

- Durations: 2.0 + 0.8 → **2.8000 (123480 frames)**; n3 → 3.8; st2 → 2.8 (2ch);
  **splicelen 0 and 15 identical** (no splice consumption — divergence from insil).
  splice-0 output allclose to numpy source/zero interleave.
- Refusals verbatim: out-of-order → `TIME (0.500000) OUT OF SEQUENCE OR INVALID, IN FILE
  sild_rev.txt.`; splicelen 5001 → `Parameter[2] ... (0.000000 to 1000.000000)`; splice
  brk → `Cannot read parameter 1`. **Time beyond EOF silently ignored** (2.5 on 2 s →
  exit 0, output 2.0000 unchanged). Deterministic. Model = aux sentinel (`silencedata`).

## 18. prefix silence — CURATED

Working argv: `prefix silence n2.wav out.wav 0.5` — exit 0.

| input | dur | outdur | predicted `indur + dur` |
| ----- | --- | ------ | ----------------------- |
| n2 | 0.5 | 2.5000 (110250) | 2.5 |
| n1 | 1.5 | 2.5000 | 2.5 |
| n1 | 0.3 | 1.3000 | 1.3 |
| st2 | 0.5 | 2.5000 (2ch) | 2.5 |

- Head exactly 0.0; source bit-equal after. dur −0.5 → `Parameter[1] Value (-0.500000)
  out of range (0.000000 to 23767.000000)` (23767 s ceiling!); dur 0 → `Zero-length
  silence added: There will be no change to the nput sound.` (CDP typo verbatim); dur
  4000 legally wrote a 706 MB file (removed — engine cap is the guard). Brk refused
  param 1. Deterministic.

## 19. constrict — CURATED

Working argv: `constrict constrict ev4.wav out.wav 50` — exit 0.

| input | constriction | outdur |
| ----- | ------------ | ------ |
| ev4 (3.0, real silences) | 50 | 2.2749 |
| ev4 | 100 | 1.6998 |
| ev4 | 200 | 0.7496 (overlap) |
| gl2 (2.0) | 50 | 1.552 |
| n2 / flat (no zeros) | 50 | 2.0 − **1 frame** (88199) |
| st2 | 50 | 2.0 − 1 frame (2ch) |

- Ranges verbatim: 250 / −10 → `(0.000000 to 200.000000)`.
- **BREAKPOINT-CAPABLE (first-class):** brk `0 10 / 3 190` → exit 0, 0.45 s, sha differs
  from BOTH scalar renders (10 → 2.735, 190 → 0.8446). In-brk range check verbatim:
  `Value (0.400000) out of range ... in brkpntfile b_len.brk.` form seen on dvdwind
  (shared reader). Deterministic; stereo accepted. Static model pinned on the
  no-silence bound (flat fixture, −1 frame).

## 20. dvdwind — CURATED

Working argv: `dvdwind dvdwind n2.wav out.wav 2 50` — exit 0.

| input | contraction | clipsize | outdur | predicted `(indur/contraction)*(1-5/clipsize)` | rel err |
| ----- | ----------- | -------- | ------ | ------ | ------- |
| n2 | 2 | 50 | 0.9048 | 0.9 | +0.5% |
| n3 | 2 | 50 | 1.3547 | 1.35 | +0.3% |
| n2 | 4 | 50 | 0.4549 | 0.45 | +1.1% |
| n2 | 2 | 20 | 0.7544 | 0.75 | +0.6% |
| n2 | 2 | 100 | 0.9549 | 0.95 | +0.5% |
| n2 | 1.5 | 50 | 1.2194 | 1.2 | +1.6% |
| st2 | 2 | 50 | 0.9048 (2ch) | 0.9 | +0.5% |

- The 5 is source-confirmed: `dev/science/dvdwind.c` `#define DVD_SPLICELEN (5)` (mS),
  spliced per clip.
- Ranges verbatim: contraction `(1.000000 to 3600.000000)` but exactly 1 →
  `No significant stretch (1.000000)` (INVALID DATA); clipsize `(10.000000 to
  2000.000000)`.
- **BOTH PARAMS BREAKPOINT-CAPABLE:** contraction brk 1.5→4 → 0.7543, differs from both
  scalars (1.2194/0.4549); clipsize brk 20→100 → 0.9083, differs from both
  (0.7544/0.9549). Out-of-range in-brk values refused `Value (0.400000) out of range
  (...) in brkpntfile b_len.brk.` — dvdwind/constrict are the tranche's only
  brk-capable editors. Deterministic; stereo accepted.

## 21. flatten — CURATED

Working argv: `flatten flatten ev4.wav out.wav 0.3 20` — exit 0.

- Static sample-exact: 3.0 → 3.0; gl2 → 2.0; flat2 → 2.0 (passes through). Content:
  bursts at 0.48/0.55/0.39 → 0.950; the 0.25 burst → 0.495 (boost cap ~2× observed).
- Mono only: `File st2.wav is not a mono soundfile`. Ranges verbatim: elementsize
  `(0.001000 to 100.000000)`; shoulder `(20.000000 to 50000.000000)` — banner's
  ELEMENTSIZE/2 ceiling NOT enforced (200 ms at elementsize 0.3 runs). `-t0.5` works.
  Brks refused params 1–3. Deterministic.

## 22. housekeep copy — submode 1 CURATED; submode 2 drop-noted

- `housekeep copy 1 n2.wav out.wav` → decoded sha equal to source (mono AND stereo) —
  bit-identical; static.
- Submode 2: `housekeep copy 2 n1.wav 3` (no outfile argv) → exit 0, writes
  `n1_001.wav n1_002.wav n1_003.wav` in cwd. Engine-incompatible; noted in the entry.

## 23. housekeep endclicks — CURATED

Working argv: `housekeep endclicks ec2.wav out.wav 0.1 15 -b -e` — exit 0.

- ec2 (clicks at both ends) → 1.8867 s, head max 0.0 (clicks trimmed, this is a TRIM);
  `-e` only → 1.904; n2 → 1.9494 (edge ramps eaten); **flat2 → 1.9849 (−0.75%)** — the
  static row's regime; st2 → 1.9495 (2ch, stereo accepted).
- Flagless → `Input file will be UNCHANGED.` (exit 255) — one of -b/-e REQUIRED (entry
  defaults both true). `-b` alone on ec2 → `At this gate level and splice length, entire
  file will be removed.` (content/parameter dependent, verbatim).
- Ranges verbatim: gate 1.5 → `(0.000000 to 1.000000)`; splicelen −5 → `(0.000000 to
  200.000000)`. Brks refused params 1–2. Deterministic.

## 24. housekeep deglitch — CURATED

Working argv: `housekeep deglitch gl2.wav out.wav 10 100 0.001 5 2` — exit 0.

- `glitches found = 1`; click zone → exact 0.0; tones preserved; static 2.0 → 2.0. `-s`
  report verbatim: `GLITCH length 5.96 ms : val 0.889873 : at (grouped)sample 39690 :
  time 0.900000 secs`.
- **Content refusals:** flat2 → `None of the sound will be gated.` (exit 255) — duration
  row null for the flat suite fixture; clean stereo (st2) same refusal with `glitches
  found = 0`; a stereo fixture WITH a glitch (dual-mono gl2) → found + gated, 2 ch out →
  channel `any`.
- Ranges verbatim: glitch `(0.022676 to 1000.000000)`; sil `(0.300000 to 1000.000000)`;
  thresh `(0.000000 to 1.000000)`; splice `(0.000000 to 50.000000)`; window `(0.022676 to
  4.000000)` mono / `(0.045351 ...)` stereo (floor = grouped-sample period,
  input-dependent; 15 refused — window is effectively 1–4). Brks refused params 1–5.
  Deterministic.

## 25. sfedit randcuts — DROPPED (no outfile argv + clock seed)

`sfedit randcuts n2.wav 0.5 2` (argv = infile chunklen scatter, NO outfile) → exit 0,
`INFO: creating file n2_0` ... writes `n2_0..n2_3.wav` next to the input (naming =
`<stem>_<N>.wav` from 0 — the banner's "truncated by 1 character" is wrong here).
**Clock-seeded** (source: `randcuts_pconsistency` calls `initrand48()` = `srand(time(0))`,
osbind.c): two same-second runs → identical chunk sets (32640/38760/6532/10268 frames
twice); a run 1.3 s later → different (36052/8354/23044/20750). Same-second collision
trap applies. execute() only.

## 26. sfedit randchunks — DROPPED (no outfile argv; input-collision naming)

`sfedit randchunks n2.wav 3 0.3` → naming IS "stem truncated by 1 char + index":
`n0.wav`, `n1.wav`, then chunk 3 tries to write **`n2.wav` = the input file itself** and
dies: `ERROR: Cannot open output file n2.wav` (exit 255 after writing 2 chunks). A
3-chunk run on any file named `<x>2.wav` cannot complete. Also clock-seeded
(`do_randchunks` calls `initrand48()`, cut.c:2709). execute() only, with naming care.

---

## Final row confirmations (pinned params)

| row | predicted | actual | rel err |
| --- | --------- | ------ | ------- |
| sfedit cutend 1, length 0.75, indur 2.0 | 0.75 | 0.7500 | 0.000% |
| sfedit zcut 1, 0.5/1.5, tone indur 2.0 | 1.0 | 1.0000 | 0.000% |
| sfedit insil 1, 0.8/0.5 (splice dflt 15), indur 2.0 | 2.485 | 2.4850 | 0.000% |
| sfedit masks 1 (static), exc14.txt, indur 2.0 | 2.0 | 2.0000 | 0.000% |
| sfedit joinseq w0 2×1 s (rule, no row) | 2.0 | 2.0000 | 0.000% |
| prefix silence, dur 0.5, indur 2.0 | 2.5 | 2.5000 | 0.000% |
| constrict (static bound), 50, flat 2.0 | 2.0 | 2.0000−1fr | 0.001% |
| dvdwind, 2/50, indur 2.0 | 0.9 | 0.9048 | 0.53% |
| flatten (static), 0.3/20, indur 2.0 | 2.0 | 2.0000 | 0.000% |
| housekeep copy 1 (static), indur 2.0 | 2.0 | 2.0000 | 0.000% |
| housekeep endclicks, 0.1/15 -b -e, flat 2.0 | 2.0 | 1.9849 | 0.755% |

21 entries curated; 7 dropped with evidence (zcuts, cutmany, syllables, randcuts,
randchunks, twixt mode 4, isolate all-modes) + housekeep copy 2 drop-noted inside the
copy 1 entry. twixt/sphinx modes 2/3 pinned as deterministic-random, left for a
submode tranche.
