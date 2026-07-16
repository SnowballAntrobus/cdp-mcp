# Tranche 19 — grain depth + FOF family probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (-fsigned-char rebuild; Groucho banners "CDP Release 7.1 2016"; psow/fofex/iterfof/tweet print no release banner), Linux x86_64 sandbox.
- **Fixtures (`/tmp/probe19b`, python-soundfile, mono 44100 float32 unless noted):**
  - `ct2`/`ct3` — 2 s / 3 s click-burst trains (0.2 s grid, 50 ms decaying 2 kHz pings, amp 0.9);
    `ctalt2` — alternating 0.9/0.15 amp bursts (gate probes); `ct2w` — 0.3 s grid; `ct2st`/`ct2wst` — stereo duals.
  - `vow2`/`vow3`/`vow2b` — 2 s / 3 s / 165 Hz synthetic vowels (220 Hz glottal pulse train through 650/1080/2650 Hz formant resonators); `vgl2` — 220→277 Hz gliding vowel.
  - Pitch traces `pch220.txt` ("0.0 220.0 / 2.0 220.0"), `pch220_3.txt`, `pgl.txt` ("0.0 220 / 2.0 277").
  - `rr2` — 30 Hz iterative ping train (r_extend); `vh2` — tone|hiss|tone sandwich (noise_extend).
  - Reused from `/tmp/probe`: `n2` (flat noise 2 s), `tone2` (440 Hz sine 2 s), `st2` (stereo noise), `syl2` (4-syllable train: 0.25 s syllables at 0.5 s spacing).
- **Methodology:** tranche-2 verbatim — breakpoint proof = brk render differs from BOTH scalar endpoints (sha256 of float64-decoded samples); determinism pairs > 1.1 s apart; fresh output names throughout (one probe block was invalidated by CDP's no-overwrite refusal `Cannot open output file` and re-run with fresh names); duration models at ≥ 2 indurs; refusals quoted verbatim (stdout, exit 255 unless noted).

## 1. grain count / assess — DROPPED (stdout-only, no outfile argv)

- `grain count ct2.wav` → exit 0, "10 grains found at this gate level." on stdout only.
  With an outfile argument: `Unknown parameter 'cnt.txt'` (exit 255).
- `grain assess ct2.wav` → "Maximum grains found = 9 at gate value 0.859600 and windowlen 50ms";
  with outfile: `Too many parameters on command line.` — and the estimate is MISLEADING: gate 0.3 finds all 10 grains on the same file.
- Default-gate evidence via count on ctalt2: unflagged → 5; -l0.1 → 10; -l0.3 → 5; -l0.95/-l1.0 → 1. Unflagged == 0.3, NOT the banner's "default 1".
- Verdict: both dropped (no output-file argv, standing multi-output/info-output rule); `grain find` subsumes count.

## 2. grain find (curated, .txt data output)

- `grain find ct2.wav f.txt -l0.3` → text file of ascending onset seconds (10 lines, 0.000295/0.200295/...).
- Default == -l0.3 (byte-identical text; differs from -l0.1: 5 vs 10 lines on ctalt2). -x drops one line (10→9).
- gate brk (0.05→0.5) → exit 0, 4-line list ≠ both endpoints (5- and 10-line) → **capable**.
- Ranges verbatim: len `Parameter[1] Value (0.001000) out of range (0.100000 to 2.000000)`; gate `Parameter[2] ... (0.000000 to 1.000000)`; minhole `Parameter[3] ... (0.032000 to 2.000000)`; winsize `Parameter[4] ... (0.000000 to 2000.000000)`.
- Tone refuses `ERROR: CANNOT ACHIEVE TASK: / ERROR: No grains found.`; flat noise passes (2 pseudo-onsets 0.0458/1.9176 — edge ramps); stereo accepted.

## 3. grain omit (curated)

| keep/out_of | input | outdur | note |
| --- | --- | --- | --- |
| 1/2 | ct2 2.0 | 0.9927 | gaps CLOSED, not silenced |
| 3/4 | ct2 2.0 | 1.6000 | 8 of 10 grains kept |
| 1/2 | ct3 3.0 | 1.6000 | 8 of 15... (0.2 grid ×8) |
| 1/4 | ct2 2.0 | 0.5928 | +19% vs indur*keep/out_of |
| 2/2 | ct2 2.0 | 2.0000 | pass-through |

- Model `indur * keep / out_of` (quantisation honesty in known_issues). keep brk (1→3 @ out_of 4) → 1.0000 s ≠ both endpoints → **capable** (banner "Keep may vary"). out_of brk: `Cannot read parameter 2 [oo.brk]: brkpnt_files not permitted.`
- Ranges: keep `(1.000000 to 63.000000)`; out_of `(2.000000 to 64.000000)`; keep>out_of → `ERROR: INVALID DATA / ERROR: A value of 3 grains-to-keep out of each 2 is impossible.`
- Tone (1 grain): exit 0, 2.0000 intact. Flat noise: 1.9101 (truncation landmine live). Stereo accepted (1.9610, 2ch). Deterministic. Default gate == -l0.3 byte-identical; gate brk differs-from-both on ctalt2 → capable.

## 4. grain repitch (curated, submode 1)

- `grain repitch 1 ct2.wav out.wav trA.txt` (trA = "12") → 1.9925 s; ct3 → 2.9925 (static −0.4%).
- Centroid proof: ct2 2217 Hz → +12: 4248 Hz, −12: 1511 Hz.
- Mode 2: 2-value list → 3.9922 s (each grain at every transposition).
- Range: "50" → `ERROR: INVALID DATA / ERROR: Ratio (50.000000) out of range (-48.000000 - 48.000000)` (dash form).
- gate default byte-check + gate brk differs-from-both (ctalt2) → capable. Deterministic; stereo accepted (2ch).

## 5. grain reorder (curated)

- `adb:c` → 1.8000; `ab:c`/`a:b`/`abcd:e` → 2.0072; `ac:b` → 2.8000 (grain reuse +40%).
- Refusals verbatim: `abc` → `Reorder sequence does not contain a separator`; `ba:a` → `Reorder sequence does not advance (last entry [A] <= first [B])`; `a:a`, `ab:a`, `aA:a` same shape; `a1:a` → `Reorder sequence contains non-alphabetic characters`.
- Advance rule: post-colon letter must be strictly later than the FIRST pattern letter. Case-insensitive.
- gate brk differs-from-both (ctalt2, code `ab:c`) → capable. Tone: exit 0 (~2.01). Deterministic; stereo accepted.

## 6. grain remotif (curated, submode 1)

- `tm1.txt` = "12 0.5 / -12 2.0": mode 1 → 2.4923 (rerhythm arithmetic: 5×0.1 + 4×0.4 + head/tail); mode 2 → 4.9921.
- Refusals: `Time-ratio (2000.000000) out of range (0.001000 - 1000.000000)`; `Pitch-ratio (50.000000) out of range (-48.000000 - 48.000000)`; odd count → `Pitch and time ratios not paired correctly.`
- gate brk differs-from-both → capable; stereo accepted (2ch).

## 7. grain align (curated, 2-input)

- `grain align ct2w.wav ct2.wav out 0 0.3` → 2.0006 s; onsets verified on file1's 0.3 s grid (0.015/0.301/0.601/...); first grain nudged with `WARNING: 1st grain moved by 0.014717 secs (649 samps) to allow for startsplice`.
- Duration: offset 0.5 → 2.5006; file1=3 s → 2.0003 (file2's 10 grains exhaust); file2=3 s → 2.0006. `indur_min + offset` fits all four (≤ +0.03%).
- gate2 brk and gate (-l) brk each differ-from-both → **both capable** (banner "Gate and Gate2 may vary over time"). offset brk: `Cannot read parameter 1 [oo.brk]: brkpnt_files not permitted.` Ranges: offset `(0.000000 to 32767.000000)`; gate2 `(0.000000 to 1.000000)`.
- **CHANNEL LANDMINE:** mono+stereo → exit 0, MONO output 4.0008 s (doubled); stereo+mono → 1.0004 s; stereo+stereo → correct 2.0006 s 2ch. (Flat stereo noise as file2 also refused `1st grain starts beyond end of sound buffer`.) Entry requires matched channel counts.
- Tone as file2: exit 0 (single grain placed). Deterministic.

## 8. grain grev (curated: submodes 1 REVERSE + 5 TIMESTRETCH; 2/3/4/6/7 recorded)

- syl2 (4 troughs at samples 2207/24260/46309/68358 per mode 6 GET — **sample counts, not seconds**): banner "Number of grains found = 4".
- grev 1: 1.0000 s from 2.0 — **first unit + head/tail dropped** (source: grain1.c GREV_REVERSE `for(n = envcnt - 2*gp; n > 0; n -= gp)` never emits unit 0; nothing outside pa[0]..pa[last] is written). ct2 → 1.4000.
- grev 1 gpcnt 2 (= envcnt/2) → **zero-length output, exit 0**, `WARNING: Can't close output sf-soundfile : can't truncate SFfile`.
- grev 1 gpcnt brk (1→2) → 0.5000 s ≠ gpcnt1 (1.0000) ≠ gpcnt2 (empty) → **capable**.
- grev 5: ×2 → 3.0000; ×0.5 → 0.7500; ×3 → 4.5001; ct2 ×2 → 3.2000 — all = trough-span × tstretch (indur×tstretch −25%/−20% on syl2). tstretch brk (1→3) → 2.3251 ≠ both → **capable**. gpcnt INERT in mode 5 (1 vs 3 byte-identical; source: TSTRETCH loop advances per-trough).
- grev 2: repets 2 → 3.0000; repets brk (1→3) → 2.5000 ≠ 1.5000/4.5001 → capable (recorded). grev 3 → 1.0000; grev 4 → 1.5000 (silence-fill).
- Ranges verbatim: tstretch `(0.010000 to 100.000000)`; trof 1.5 → `(0.000002 to 0.999998)` **but 0 and 1.0 accepted** (exit 0); wsiz `(0.181406 to 666.666667)` on 2 s (= indur/3 ms); gpcnt `(1.000000 to 100.000000)`.
- wsiz/trof brks: `Cannot read parameter 1 [ws.brk] / 2 [tf.brk]: brkpnt_files not permitted.`
- Refusals: tone `ERROR: NO PEAKS IN THE FILE`; flat noise `ERROR: INSUFFICIENT VALID TROUGHS IN THE FILE.`; stereo `Application doesn't work with this type of infile.` → mono. Deterministic.

## 9. grain r_extend — DROPPED

- Mode 1 argv from banner (`stt end te pr rep get asc psc rit reg`): pr=1 (the banner's own "try 1") refused `Parameter[4] Value (1.000000) out of range (2.000000 to 100.000000)`; rep=1 refused the same way earlier (floor 2 despite banner "try 1-2").
- With pr=2: runs, prints `Original number of segments found = 28 / Reduced to = 2` (undocumented reduction).
- Duration unmodelable: (indur 2.0, span=end−stt) te 2.0/S 1.0 → 3.4000; te 3.0 → 4.3334; te 2.0/S 0.5 → 2.4000; **te 1.0 (identity) → 2.4667 (+23% vs 2.0)**. No closed form fits; identity case fails worst.
- Verdict: drop with evidence (banner/binary divergence on pr and rep floors, opaque segment reduction, unfittable duration model).

## 10. grain noise_extend — DROPPED

- `NO NOISE FOUND` (exit 255) on: flat white noise n2, tone2, and the vh2 tone|hiss|tone sandwich — all at the banner's own suggested minfrq 6000.
- syl2 at minfrq 6000: **HANG** — killed at 15 s (exit 124), zero-length output after "INFO: Generating output."
- Works only at minfrq 2000 on vh2: duration 3.0 → 3.4521; 5.0 → 5.1525; -x → 2.9611 (≈ duration). Without -x the duration param does not map to output duration in any consistent way (residuals +0.4521 vs +0.1525).
- Source (grain1.c grab_noise_and_expand): wavecycle-length noise test with stale-index run bookkeeping; "random-reads" expansion is deterministic on this build (unseeded pair identical — drand48 shim).
- Verdict: drop with evidence (hang risk + hair-trigger detection + unmodelable duration).

## 11. psow stretch / dupl / delete / strtrans (all curated)

Working argv (all): `psow <mode> infile outfile pitchfile <params>`; pitchfile = time/frq text pairs (pch220.txt for vow2). MONO only: `ERROR: INVALID DATA / ERROR: File st2.wav is not of correct type (must be mono)`. All deterministic (pairs 1.2 s apart identical).

| mode | probe | outdur | model | err |
| --- | --- | --- | --- | --- |
| stretch | ×2 seg1 vow2 | 3.9911 | indur*timestretch | −0.22% |
| stretch | ×2 seg4 | 3.9791 | | −0.52% |
| stretch | ×0.5 | 1.0012 | | +0.12% |
| stretch | ×2 vow3 | 5.9911 | | −0.15% |
| stretch | ×2 gliding vgl2+pgl | 3.9932 | | −0.17% |
| stretch | ×2 flat noise + fake trace | 3.9927 | | −0.18% (**garbage-through**) |
| dupl | ×2 seg1 | 3.9956 | indur*repeats | −0.11% |
| dupl | ×3 / ×4 | 5.9935 / 7.9913 | | −0.11% |
| dupl | ×2 vow3 / noise | 5.9956 / 3.9971 | | −0.07% |
| delete | /2 seg2 | 1.0024 | indur/propkeep | +0.24% |
| delete | /4 / /6 | 0.5040 / 0.3403 | | +0.8% / +2.1% |
| delete | /2 vow3 / noise | 1.5069 / 1.0127 | | +0.5% / +1.3% |
| strtrans | ×2 tr 0/+12/−12 | 3.9956/3.9979/3.9911 | indur*timestretch | ±0.1% |
| strtrans | ×1 tr12 / ×2 vow3 | 2.0001 / 5.9956 | | exact |

- **Breakpoint proofs (differs-from-both, float64 shas):** stretch timestretch (1→3 → 5.9710); dupl repeats (2→4 → 5.9834); delete propkeep (2→6 → 0.5676); strtrans timestretch (1→3 → 5.9892) AND trans (0→12 ramp ≠ tr0 ≠ tr12). segcnt refuses everywhere: `Cannot read parameter 3 [sc.brk]: brkpnt_files not permitted.`
- **Content proof (strtrans):** autocorrelation f0 vow2 220.5 → tr+12: 441.0, tr−12: 110.0 Hz; duration unchanged (formant-preserving PSOLA).
- **Ranges verbatim:** timestretch `(0.100000 to 10.000000)`; segcnt `(1.000000 to 256.000000)`; dupl repeats `Parameter[2] Value (1.000000) out of range (2.000000 to 256.000000)` (identity refused); delete propkeep `(2.000000 to 20.000000)` (afta8 0-1000 wrong); strtrans trans `(-24.000000 to 24.000000)` (afta8/ST ±48 wrong).
- **BANNER BUG:** delete's usage line says `psow del` — `psow del ...` exits 255 with an EMPTY error; only `psow delete` works.
- Pitch file traps: frequency-zero rows legal (verified exit 0); junk → `ERROR: No data in brkpnt file pbad.txt`.

## 12. fofex (extract 2 curated; extract 1/3 + construct dropped)

- extract 1 verified DUAL OUTPUT: `fb1.wav` (fofbank, 5.4153 s) + `fb1.wav.txt` (fofinfo) from one outfiles arg → drop (standing rule). extract 3 = N files → drop. construct consumes 1's pair → drop (execute()-territory).
- **extract 2 banner bug:** usage omits fofcnt; without it `Insufficient parameters on cmdline.`; real argv `fofex extract 2 in out pitchfile time fofcnt [-w]`.
- Output = single FOF: 0.00454 s from steady 220 Hz vowel (= 1/220); gliding vowel at t 0.3 vs 1.7 → 0.02193 vs 0.00372 s (times differ, content differs). fofcnt 1/2/3 → byte-identical durations (inert on all probed material). -w changes render. time range `Parameter[2] Value (5.000000) out of range (0.000000 to 2.000000)`. MONO only. Deterministic (pair 1.2 s apart identical).

## 13. iterfof (submode 3 curated)

- `iterfof iterfof 3 fof.wav out mid60.txt 4` (fof = fofex extract 2 packet) → 4.0015 s of MIDI-60 vowel tone; 48→72 line → gliss; outduration 2 → 2.0011; 0.01 → 0.0122.
- **Overrun:** last iteration completes — 2 s inputs (syl2/vow2/n2) at outduration 4 → 5.9970 (+50%). set_by pinned with honesty; duration row null.
- Mode 4 (stepped) ≠ mode 3 (interpolated) on the same gliss file (shas differ). Mode 1 runs with a semitone line ("0 0 / 4 0").
- **Seed semantics INVERTED (first-class):** rand 0 (default) → fully deterministic (pair 1.2 s apart identical). With -r0.5: `-s5` twice 1.2 s apart → DIFFERENT (durations 4.0027/4.0041!); `-s5` vs `-s9` differ; `-s5` twice within the SAME SECOND → identical; unseeded pairs differ. Seed is clock-mixed; banner honestly says "similar output".
- Flag ranges verbatim: -p13 → `Parameter[3] ... (0.000000 to 2.000000)`; -a2 → `Parameter[4] ... (0.000000 to 1.000000)`; -r2 → `Parameter[8] ... (0.000000 to 1.000000)`; -s300 accepted.
- **Mode-3 flag refusals (all individually verified):** -g/-G/-F/-f/-S/-P/-i each → `ERROR: INCORRECT USE / ERROR: Unknown variant flag -g` (etc.) — stepped-mode-only flags despite the shared banner; -p0/-a0/-r0/-t0.003/-T0.002/-E1/-s5 accepted.
- linedata MIDI unchecked (200 accepted silently). Vibrato flags change render AND duration (3.6379 at outduration 4). Stereo refused `must be MONO`.

## 14. tweet (submode 1 curated; 2/3 recorded)

- `tweet tweet 1 vow2.wav out 0 pch220.txt 0 10 0` → 1.9939 s (static −0.3%); vow3 → 2.9939; noise + fake trace → 1.9800 (garbage-through). Modes 2 (fixed frq) and 3 (noise, no pkcnt/chirp) verified running.
- pkcnt 10 vs 40 differ; chirp 0 vs 5 differ; -w differs. Deterministic; stereo refused `(must be mono)`.
- Ranges verbatim: pkcnt `(1.000000 to 200.000000)`; chirp `(0.000000 to 30.000000)`; minlevel `Parameter[2] Value (200.000000) out of range (-60.000000 to 0.000000)` (**negative dB**; −10 accepted).
- **EXCLUDE SEGFAULT (first-class):** exclude file "0.5 1.0" → `timeout: the monitored command dumped core` (SIGSEGV, exit −11, 0-byte output); two-pair file same; sample-count pairs refused `Time (44100.000000),in file excs.txt, is beyond end of infile (2.000000).` (seconds are the intended — and crashing — format). Entry pins exclude = 0.

## Engine spot-checks (process_impl, real preflight/argv/verification)

| entry | fixture | result |
| --- | --- | --- |
| grain omit (keep 1/2) | ct2 (articulated) | ok, 0.9927 s |
| psow stretch ×2 | vow2 + pch220.txt aux | ok, 3.9911 s |
| grain grev 5 ×2 | syl2 | ok, 3.0000 s |
| iterfof 3 (mid60.txt, outdur 4) | fofex-extracted packet | ok, 4.0015 s (after removing stepped-mode flags from the entry — the argv builder emits curated defaults, and -P0 was refused `Unknown variant flag -P`) |
| psow delete /2 | vow2 | ok, 1.0024 s |
| fofex extract 2 | vow2 | ok, 0.00454 s |
| grain find | ct2 | ok, .txt with 10 onsets |
| tweet 1 | vow2 | ok, 1.9939 s (exclude re-typed int min=max=0: engine str values are .brk-reserved) |

Loader: clean, zero malformed warnings (403→406 entries during the session — a parallel agent's tranche landing alongside). `grain grev` submodes 1 and 5 resolve as distinct exact triples.
