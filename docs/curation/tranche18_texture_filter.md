# Tranche 18 — texture depth + filter depth: probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (-fsigned-char rebuild; banners "CDP Release 7.1 2016"), Linux x86_64 sandbox.
- **Fixtures:** `/tmp/probe18a` — mono 44.1 kHz float32: `ping1` (0.5 s decaying 440 Hz sine, sharp attack — texture source), `ping2` (1 s), noise `n1/n2/n3` (1/2/3 s, edge-ramped + slow AM), `tone1/tone2`, stereo `st2`, `lo_sr.wav` (1 s noise @ 22.05 kHz).
- **Methodology:** tranche-2 verbatim — breakpoint proof = brk render differs from BOTH scalar endpoints (at the same seed where seeds exist); determinism pairs > 1.1 s apart; float64-decoded sha256; fresh output names; duration at ≥ 2 settings; refusals quoted verbatim. Probes wrapped in `timeout 30`.
- **Sources consulted:** `/tmp/CDP8/dev/filter/*` (ap_filter.c, filters0.c, fltpcon.c, fltprepro.c), `/tmp/CDP8/dev/cdp2k/parstruct.c` (param/flag ground truth), `/tmp/CDP8/dev/texture/*` (texprepro.c, texture4.c), `/tmp/CDP8/dev/include/{flags,txtucon,pnames}.h`; SoundThread process_help.json (no coverage of any tranche-18 filter mode); afta8 definitions.lua (fixed/iterated/phasing/bankfrqs/lohi coverage).

## Source ground truth (parstruct.c / filters0.c)

Param strings (`D` = brk-capable double, `d` = plain): EQ(fixed) modes 1/2 `0dd00`,
mode 3 `ddd00`; FSTATVAR(variable) `DdD00`; FLTBANKU(userbank) `Dd000` + special
FILTERBANK; FLTBANKV(varibank) `Dd0` + TIMEVARYING_FILTERBANK, vflags `thr`+`don`;
FLTBANKV2 `Dd0` + TIMEVARY2, vflags `t`+`dn`; FLTITER(iterated) `dddd00` + FILTERBANK,
vflags `srpa`(`ddDD`) + `dien`; ALLPASS(phasing) `0dD00`, vflags `ts`+`l`;
FLTBANKC(bankfrqs) modes 1-3 `00dd00`, 4-6 `00dd{d,i,d}0`, TEXTFILE_OUT.

**P5-1 vintage-hang scope resolved:** `filters0.c` sets `do_norm` ONLY for FLTBANKN
(always), FLTBANKV (`vflag[2]` = hidden `-n`), FLTBANKV2 (`vflag[1]` = hidden `-n`).
The pre-11cdcb4 OOB write (unguarded `FLT_FRQ_INDEX`/`FLT_TIMES_CNT` at indices 20/21,
now guarded "only for varybanks") sat inside the do_norm epilogue; varybank internal
param strings allocate through those slots, so only `bank` was ever OOB. **None of the
tranche-18 filter modes is vintage-sensitive** → version_sensitive false throughout.

**Clock-seed scope:** `fltpcon.c:87 filter_pconsistency()` calls `initrand48()` =
`srand(time(0))` (osbind.c:334) for every filter process — iterated's rand/pshift/ashift
paths (and bank's scat) are clock-seeded, unseedable, same-second collision trap.

**Texture placement:** `texture4.c:1032-37` — `GET_DECORNPOS` mask: PRE→`vflag[IS_PRE]=1`,
POST→0, plain decorated/ornate → `doperm(PM_ORNPOS)` random per note. `texprepro.c:387-99` +
1495-1525 pin notedata block order: pitch line → [line/timing motif if ORN_DEC_OR_TIMED] →
[HF block if modes 1-4] → [ornament/motif blocks if ornate/motifs; extras legal there,
elsewhere exact count enforced].

---

## FILTERS

### 1. filter iterated 1

Working: `filter iterated 1 n1.wav out.wav fbank.txt 50 1.0 0.3 3` (fbank = `440 1.0/660 0.5/880 0.25`) — exit 0, 3.7000 s.

- **BUFFER LANDMINE (first-class):** 2 s input FAILS at default buffer: `ERROR: INTERNAL ERROR: (Bug?)` + `ERROR: Failed to read all of source file: readsamps_with_wrap()` (exit 255); 1 s works. `CDP_MEMORY_BBSIZE=8000` → 2 s mono and stereo run clean. Whole input must fit one buffer (FLTITER bufcnt 4; default pool 1 MB ⇒ ~65536-sample ceiling ≈ 1.48 s mono @44.1k).
- **Duration:** onsets at multiples of delay strictly < dur; outdur = last onset + indur. Probes: (indur 1, delay .3, dur 3) → 3.7000; (dur 5) → 5.8000; (delay .7, dur 3) → 3.8000; (delay .5, dur 3) → 3.5000 exact; (indur 2, delay .3, dur 4) → 5.9000; stereo same. Model `indur + dur - delay`, exact at integer dur/delay (1-frame slop), under by < delay otherwise. dur runtime min = indur: `Parameter[5] Value (1.500000) out of range (2.000000 to 32767.000000)` on n2.
- **delay 0 HANGS** (timeout 124; range floor 0.000002 not applied to literal 0).
- **Determinism:** base pair identical; `-r0.5` pair differs (samples AND frames); `-p2` pair differs + length varies. Clock-seed source pinned above.
- **Breakpoints:** q/gain/delay/dur refuse (`Cannot read parameter 1/2/3/4`), prescale 7, rand 8; **pshift (-p) and ashift (-a) ACCEPT** (renders, 328466 bytes) — matches parstruct `ddDD`. afta8's "Q input=brk" is wrong.
- **Ranges verbatim:** Q + gain `(0.001000 to 10000.000000)`; delay `(0.000002 to 32767.000000)`; prescale `(-1.000000 to 1.000000)` (banner says 0-1); rand `(0.000000 to 1.000000)`; pshift `(0.000000 to 48.000000)` (banner ">=0", afta8 0-100); ashift `(0.000000 to 1.000000)`.
- **Datafile errors verbatim:** `Not enough values on line 1: file bad1.txt`; `Too many values on line 1: file bad2.txt`; `frq (30000.000) on line 1 out of range (0.1 to 22050.0):file bad3.txt`. `;` comments + `-6dB` amps OK. Mode 2 (MIDI `69 1.0`) runs, distinct sha.
- **Switches:** -d changes; -e changes (RMS .109→.019); -n changes (.109→.028); **-i byte-identical no-op at pshift 0** (interp only matters during pitch shift). Stereo accepted (2 ch out, duration matches).

### 2. filter userbank 1

Working: `filter userbank 1 n2.wav out.wav fbank.txt 50 1.0` — 3.0000 s.

- **tail default 1.0** (2→3.0000, 1→2.0000; -t2→4.0, -t0.5→2.5, sample-exact) → `indur + tail`.
- **tail 0 bug variant:** output ballooned to 244690 frames at BBSIZE 8000 (garbage tail length tracks buffer size; bank precedent was fixed 262144 at default).
- **Q brk CAPABLE:** brk 20→500 sha 33286c3f ≠ Q20 c48b8e57 ≠ Q500 bd36ad79. gain refuses (param 2), tail (param 6).
- Ranges verbatim Q/gain `(0.001000 to 10000.000000)`. Datafile error surface identical to iterated (incl. 0.1-22050 in-file pitch check). Raw bankfrqs output (no amps) refused `Not enough values on line 1`.
- -d changes render; stereo accepted; deterministic pair identical; mode 2 (MIDI) exists.

### 3. filter varibank 1

Working: `filter varibank 1 n2.wav out.wav vb.txt 50 1.0` (vb = `0.0 300 1.0 1200 0.5 / 1.5 600 1.0 900 0.8`) — 3.0000 s.

- tail default 1.0 (1 s → 2.0; -t2 → 4.0). Q brk capable (3b7f3c11 ≠ 5efb7c3e ≠ 9a57afa4). gain refuses param 2.
- **HIDDEN SWITCHES (first-class):** `-o` accepted (byte-identical no-op, DROP_OUT_AT_OVFLOW), `-n` accepted → runs `INFO: Assessing input level./Assessing output level.` pre-pass, RMS 0.0042→0.178. Banner lists only -d.
- -h3 -r-6 runs (changes render); rolloff range verbatim `(-96.000000 to 0.000000)` (both +5 and -100 refused).
- **Data errors verbatim:** `Too many entries in row 2 of file vbbad1.txt`; `Time is out of sequence on line 3`; a 0.5-start file RUNS (times need not start at 0).
- Stereo accepted; deterministic pair identical.

### 4. filter varibank2 1

Working: vb2 = varibank lines + `#` + `0.0 1 1.0 2 0.5 / 1.5 1 1.0 3.5 0.8` — 3.0000 s; 1 s → 2.0; -t2 → 4.0.

- **Errors verbatim:** missing `#` block → `FAILED TO GET SECOND SET OF DATA (PARTIALS INFORMATION) AFTER HASH SIGN`; 0.5-start pitch section → `FIRST TIME VALUE FOR PITCHES MUST BE ZERO` (stricter than varibank).
- Q brk capable (8f9b86ec ≠ ba98fd56 ≠ 6b6f2da2). Hidden `-n` accepted (5 INFO lines; RMS 0.0067→0.146).

### 5. filter fixed (modes 1/2/3)

Working: `filter fixed 3 n2.wav out.wav 400 -12 1000` → 3.0000; n1 → 2.0000; -t2 → 4.0000. Modes 1/2 (`-12 1000`, no bwidth) both run, distinct (mode 1 cut-below RMS .128, mode 2 cut-above .040); boost +12@500 works (.156).

- **No brks anywhere:** params 1/2/3 refuse; tail param 6.
- Ranges verbatim: boost/cut `(-96.000000 to 36.000000)`; freq `(0.100000 to 22050.000000)`; bwidth `(0.001000 to 22050.000000)`; prescale `(0.005000 to 200.000000)`.
- `-t0` legal, lands 2.0200 (constant ~20 ms slop, no bank garbage-tail). -s0.5 halves. Stereo ok; deterministic pair identical.
- **Curated fixed 3 only** (peaking band — the shape lohi/bank lack); modes 1/2 = shelving pair, probe data recorded, execute() (scope drop).

### 6. filter variable (modes 1-4)

Working: `filter variable 1 n2.wav out.wav 0.05 1.0 1000` → 3.0000; n1 → 2.0000; -t2 → 4.0000. Modes 2/3/4 all run, four distinct shas.

- **acuity brk capable** (eaba7c79 ≠ 5b889d85 ≠ bd151a2d); **frq brk capable** (c46562f6 ≠ e16889e4 ≠ 56564a55); gain refuses param 2; tail param 6.
- Ranges verbatim: acuity `(0.000100 to 1.000000)`; frq `(0.100000 to 22050.000000)`.
- Deterministic; stereo ok. **Curated variable 1 (NOTCH)**; 2-4 dropped for overlap (bandpass ≈ curated sweeping 2; lo/hi ≈ curated lohi).

### 7. filter phasing (modes 1/2)

Working: `filter phasing 2 n2.wav out.wav 0.6 30` → 3.0000; n1 → 2.0000; -t2 → 4.0000.

- **delay brk capable** (eadcab98 ≠ 60ff02ea ≠ 027ec53a); gain refuses param 2. `-l` changes render under a delay brk (103f4332 vs eadcab98).
- **gain 1.0 → RMS 0.0000** (banner's total-cancellation warning verified). Ranges verbatim: gain `(-1.000000 to 1.000000)`; delay `(0.022676 to 1000.000000)` ms; prescale `(-1.000000 to 1.000000)` (banner 0-1).
- Mode 1 (allpass) same args: RMS 0.134 vs source 0.144 — magnitude-transparent phase rotation; **dropped for scope** (mode 2 curated).
- Deterministic; stereo accepted; -s0.5 live.

### 8. filter bankfrqs (modes 1-6)

Working: `filter bankfrqs 1 n2.wav bf1.txt 200 2000` → text: `200.000000/400.000000/...` (one `%.6f` per line). Mode 5 reproduces tranche-9 geometric spacing (200, 290.84, ...); mode 6 semitone steps; mode 3 subharms (2000, 1000, 666.666667, 500); mode 4 offset (200, 430, 630, 830).

- lof range verbatim `(0.100000 to 22050.000000)`; **srate/3 NOT enforced** (22.05 kHz file accepted hif 8000); **hif<lof silently swapped** (byte-identical list); brk refused `Cannot read parameter 3`; deterministic (byte-identical rerun); stereo input ok.
- userbank refuses the raw output (`Not enough values on line 1`) — amps must be appended.
- **Curated as data output** (.txt, getlevel-3 precedent), submode 1.

---

## TEXTURES

Shared verification per curated mode (ping1 source, mode 5): working argv exit 0; stereo
output always; mono-only input (`Application doesn't work with this type of infile.`);
seed working (-r5 pair 1.2 s apart byte-identical, -r9 differs, unseeded differs); outdur
honesty at 5 and 8; **full per-parameter brk sweep** (every positional + -a/-p/-s);
flag-order enforcement (`option flag -a out of order on cmdline.` on ornate); atten range
`(0.000002 to 1.000000)` (param 17 refusal, ornate).

Brk sweep result, all seven curated modes: **outdur (param 1), gpspace (14), contour (17),
centring (26, decor family), seed (30) REFUSE; everything else + -a/-p/-s ACCEPTS** —
identical numbering to the decorated/grouped precedents. Onset-varying param verified
against both endpoints at seed 5 per mode: ornate/preornate*/postornate* skiptime, motifs
packing, timed skiptime, tgrouped skip, tmotifs skip, predecor/postdecor skiptime (* =
accept re-verified, differ-endpoints proof on the plain sibling).

### 9. texture ornate/preornate/postornate 5

Working: `texture ornate 5 ping1.wav out.wav nd_orn.txt 5 1.5 1 1 64 64 0.1 0.3 0 1 1 0 0 0.5 1.5 -r5`
(nd_orn = `60 / #2 line / #3 ornament`). outdur 5 → 6.1438 (+23%); outdur 8 → 8.7879 (+9.9%).
preornate: 6.2362/8.6105; postornate: 6.3073/8.7391.

- **Placement byte-proof:** seed 5, same notedata: ornate e0a76479, preornate 02bb1994, postornate 3392ba49 — all distinct; preornate re-run byte-identical to its own seed-5 pair. Matches texture4.c (random perm vs forced pre/post) → three curated entries, no redundancy drop available.
- multlo/multhi range verbatim `(0.010000 to 100.000000)` (params 15/16); multlo brk accepted.
- contour range 0-8 (`Parameter[14] Value (9.000000)...`); gpspace 0-5 (param 11).
- Notedata: < 2 blocks → `Insufficient motifs in notedata file.` (both pitch-line-only and line-only); 3 blocks legal (extra ornaments = vocabulary).
- Switches: -w changes (+0.3 s tail), -d changes; -i/-h/-e byte-identical no-ops (single input, chord-free line). Same for pre/post (-w/-d change).
- skiptime 0: exit 0, valid render (contrast decorated-curation hang — content-dependent).

### 10. texture motifs 5 (+ motifsin drop)

Working: `texture motifs 5 ping1.wav out.wav nd_mtf.txt 5 0.8 0 0 1 1 64 64 55 70 0 1 1 0 0 0.5 1.5 -r5`. outdur 5 → 5.2048 (+4.1%); 8 → 8.6089 (+7.6%). packing brk differ-endpoints at seed 5 (768275c8 ≠ f91027ac ≠ 3724aac4).

- multlo range verbatim (param 17 here). -w/-d change; **-i accepted though absent from the usage line** (byte-identical no-op single-input). Pitch-line-only notedata → `Insufficient motifs in notedata file.`
- **motifsin DROP:** `texture motifsin 5 ...` → `Program mode value [5] is out of range [1 - 4].` (no free mode); motifs 1 vs motifsin 1 at seed 5 with an HF notedata: SAME frame count (236885), different shas (4d07a89e vs 87b9bbb2) — distinct only in HF handling (start notes vs all notes), and HF modes are execute()-only family-wide.

### 11. texture timed 5

Working: `texture timed 5 ping1.wav out.wav nd_tim.txt 5 1.0 1 1 64 64 0.1 0.3 55 70 -r5` (nd_tim = `60 / #2: 0 …, 0.5 …`). outdur 5 → 6.2790 (+26%); 8 → 9.1162 (+14%).

- **CYCLING CONTENT-VERIFIED:** onset detection on the seed-5 render → attacks at 0.0, 0.5, 1.5, 2.0, 3.0, 3.5, 4.5, 5.0, 6.0 — cell restarts at last-cell-onset + skiptime (period 1.5 = 0.5 + 1.0), NOT skiptime from cell start.
- Notedata exact-count both directions verbatim: `Incorrect number [0] of motifs in notedata file (expected 1).` / `Incorrect number [2] ... (expected 1).`
- position enforced 0-1 (`Parameter[13] Value (2.000000)...`). Only switch is -w (changes render). skiptime brk differ-endpoints at seed 5. skiptime 0 exit 0 here.

### 12. texture tgrouped 5

Working: `... nd_tim.txt 5 1.0 1 1 64 64 0.1 0.3 55 70 0 1 1 0 0 2 5 20 80 1 7 -r5`. outdur 5 → 6.3882 (+28%); 8 → 9.2203 (+15%). skip brk differ-endpoints (70477515 ≠ 4fdce934 ≠ b948cc50); gpsizehi brk accepted. -w changes, -d changes, -i no-op. Timed-family notedata (one timing block).

### 13. texture tmotifs 5 (+ tmotifsin drop)

Working: `... nd_tmtf.txt 5 1.0 1 1 64 64 55 70 0 1 1 0 0 0.5 1.5 -r5` (nd_tmtf = pitch line + timing block + motif block). outdur 5 → 6.1578 (+23%); 8 → 9.3147 (+16%). skip brk differ-endpoints (b7abfd8a ≠ 1028f2e8 ≠ 24070266). -w/-d change, -i no-op.

- **tmotifsin BANNER BUG + DROP:** its usage line omits outdur/skiptime but the binary REQUIRES them — without: `Insufficient cmdline parameters.`; with: runs (6.7284 s). tmotifs 1 vs tmotifsin 1, same seed + 4-block HF notedata: same frames (296723), different shas (5fe6cc51 vs f16a49ba). Modes 1-4 only → execute().

### 14. texture predecor/postdecor 5 (+ decorated byte-proof)

Working: `texture predecor 5 ping1.wav out.wav nd_dec.txt 5 1.5 1 1 64 64 0.1 0.3 0 1 1 0 0 2 5 20 80 3 8 0 -r5` (nd_dec = decorated-line file). Seed-5 triple: decorated 4812007a, predecor b0dd3cdd, postdecor 58ff4922 — all distinct (placement forced pre/post vs random). predecor outdur 5/8 → 6.2906/8.7216; postdecor → 6.5161/8.8912; seed pairs byte-identical, -r9 differs.

- Banner errors re-verified in-mode: centring `(0.000000 to 6.000000)` (param 21; banner says 0-7); position `(0.000000 to 1.000000)` (param 23; banner says -1..1); atten param 22 family range.
- Full brk sweep incl. centring refusal (param 26). Switches -w/-d/-k change render.
- **skiptime 0 re-probed across the family with these fixtures: decorated, predecor, postdecor, timed, tmotifs, tgrouped, ornate ALL exit 0** — the decorated-curation hang is content-dependent; the family warning stands (never map 0).

---

## Duration rows (pinned)

| row | predicted | actual | note |
| --- | --------- | ------ | ---- |
| filter iterated 1, q 50/gain 1/delay 0.5/dur 3, indur 1 | 3.5 | 3.4999 | integer dur/delay point; engine spot-check identical |
| filter userbank 1, q 50/gain 1/tail 1, indur 2 | 3.0 | 3.0000 | sample-exact |
| filter varibank 1, q 50/gain 1/tail 1, indur 2 | 3.0 | 3.0000 | sample-exact |
| filter varibank2 1, q 50/gain 1/tail 1, indur 2 | 3.0 | 3.0000 | sample-exact |
| filter fixed 3, 400/-12/1000/tail 1, indur 2 | 3.0 | 3.0000 | sample-exact |
| filter variable 1, 0.05/1/1000/tail 1, indur 2 | 3.0 | 3.0000 | sample-exact |
| filter phasing 2, 0.6/30/tail 1, indur 2 | 3.0 | 3.0000 | sample-exact |
| filter bankfrqs 1 | — | — | data output, no audio duration |
| texture ornate 5, outdur 8, seed 5, indur 0.5 | 8.0 | 8.7879 | tol 0.2 |
| texture preornate 5, outdur 8, seed 5 | 8.0 | 8.6105 | tol 0.2 |
| texture postornate 5, outdur 8, seed 5 | 8.0 | 8.7391 | tol 0.2 |
| texture motifs 5, outdur 8, seed 5 | 8.0 | 8.6089 | tol 0.2 |
| texture timed 5, outdur 8, seed 5 | 8.0 | 9.1162 | tol 0.3 |
| texture tgrouped 5, outdur 8, seed 5 | 8.0 | 9.2203 | tol 0.3 |
| texture tmotifs 5, outdur 8, seed 5 | 8.0 | 9.3147 | tol 0.3 |
| texture predecor 5, outdur 8, seed 5 | 8.0 | 8.7216 | tol 0.2 |
| texture postdecor 5, outdur 8, seed 5 | 8.0 | 8.8912 | tol 0.2 |

## Engine spot-checks (process_impl, real binaries, session data/ aux)

- texture ornate 5 (nd_orn.txt aux, seed 5): status ok, stereo 270940 frames — byte-count identical to the probe render.
- filter varibank 1 (vb.txt aux, normalize=true): status ok, 2.0 s from 1 s input (pinned tail default emitted).
- filter bankfrqs 1: status ok, .txt output `110.000000/220.000000/...` (data-output path).
- filter iterated 1 (fb.txt aux, 1 s input, delay 0.5/dur 3): status ok, 3.49998 s vs predicted 3.5 (expression model evaluates in-engine).
- Loader: zero malformed warnings; 280 curated entries listed (parallel-tranche entries present).

## Drops (evidence recorded above)

- **texture motifsin** — no mode 5 (`Program mode value [5] is out of range [1 - 4].`); HF-only variant of curated motifs (same-length/different-sha byte-proof at mode 1); HF modes are execute()-only family-wide.
- **texture tmotifsin** — same rationale + banner bug (usage line omits required outdur/skiptime).
- **filter fixed 1/2** — shelving pair, fully probed (ranges/dur model identical to curated mode 3 minus bwidth); scope drop, execute().
- **filter variable 2/3/4** — probed working/distinct; overlap with curated sweeping (bandpass) and lohi (lo/hi-pass); scope drop.
- **filter phasing 1** — raw allpass, magnitude-transparent standalone (RMS 0.134 vs 0.144 source); scope drop.
- **filter vfilters** — data→data utility (makes varibank fdata from pitch files), out of tranche scope, untouched.
