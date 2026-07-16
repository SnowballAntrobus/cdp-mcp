# Tranche 10a — spectral-lean SoundThread-covered singles probe transcript

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build; Groucho-family
  programs banner "CDP Release 7.1 2016"; `spectstr` prints no version banner), Linux
  x86_64 sandbox. Re-verified on macOS r8 by the CDP-gated suite after integration.
- **Inputs:** spectral fixtures reused from `/tmp/probe9` (all `pvoc anal 1` defaults,
  1024-point / 44.1 kHz, mono): `t9m_rich2.ana` (rich additive tone, sfprops 2.029070 s,
  synth round-trip 2.0230 s, 698 windows), `t9m_rich15.ana` (1.526163 s, 525 windows),
  `t9m_tone2.ana` (440 Hz-family tone), `t9_vow2.ana` (4-formant vowel). Fresh in
  `/tmp/probe10a`: `flat2.ana` = `pvoc anal 1` of the shared formula fixture's flat noise
  (`/tmp/probe/flat2.wav`, rng seed 0, 0.2 amp). Time-domain refusal probes use
  `/tmp/probe/n2.wav`. All outputs freshly named per run in `/tmp/probe10a`.
- **Methodology:** `docs/curation/tranche2_timedomain.md` verbatim. `.ana` outputs are
  compared by RIFF `data` chunk sha256 (never raw bytes — the LIST date chunk differs);
  durations measured by `pvoc synth` round-trip; determinism pairs launched 1.3 s apart;
  breakpoint proof = brk render differs from BOTH scalar-endpoint renders; duration models
  verified at two input durations (2.023 / 1.5209 s synth-basis).

Refusal errors quoted verbatim (stdout, exit 255 unless noted).

---

## 1. blur chorus — SEED HUNT + all seven modes, submode 5 curated

Usage families: mode 1 `infile outfile aspread`; modes 2–4 `infile outfile fspread`;
modes 5–7 `infile outfile aspread fspread`. ST exposes exactly mode 5
(`blur_chorus_5`, defaults aspread 30 / fspread 2); afta8 exposes all seven.

| probe | result |
| ----- | ------ |
| all 7 modes on rich2 (`30`, `2`, or `30 2`) | all exit 0, **pairwise-distinct** data chunks |
| duration (mode 5): rich2 / rich15 | 2.0230 / 1.5209 via synth — static, window-exact |
| direction check (tone, fspread 2): input amp-weighted mean frq 873.8 Hz | mode 2 754.8 (both ways), mode 3 955.7 (**up**), mode 4 551.2 (**down**) |
| amp scatter (rich2, mode 1 aspread 30) | channel-amp CV 2.90 → 4.89 |

**Seed hunt (the tranche-6/8 question): NO seed exists, and the process is DETERMINISTIC.**

- No seed argv slot (usage shows none; no flags at all).
- Mode 5 (`30 2`) twice 1.3 s apart → **byte-identical** data chunks; mode 2 (`2`)
  twice 1.3 s apart → **byte-identical**.
- Mechanism (source): `chor_preprocess` (dev/blur/ap_blur.c:466-472) is
  `set_chorus_processing_type` + `setup_randtables_for_rapid_rand_processing` and never
  calls `initrand48()` — the `drand48()` that fills the amp/frq random tables (ap_blur.c:520,
  537, 544, 548) and picks per-window table indices (blur.c:510, 521) is the osbind.c shim
  (`rand()/RAND_MAX`) running from `rand()`'s fixed default seed. The `initrand48()` at
  ap_blur.c:565 belongs to `drnk_preprocess` (blur drunk, already curated as clock-seeded).
  Same construction as distort reform 6. Entry `stochastic: false`,
  `version_sensitive: true`.

**Ranges (CDP-enforced, all probed):** aspread
`ERROR: Parameter[1] Value (0.500000) out of range (1.000000 to 1028.000000)` (same for
0, −1, 2000) — **DIVERGENCE:** afta8's "there is in fact no mathematical limit to the
values which can be entered" is wrong on this build; fspread
`ERROR: Parameter[1] Value (0.500000) out of range (1.000000 to 4.000000)` (same for 0, 5).
ST's slider ranges (1–1028, 1–4) match CDP exactly.

**Neutral values:** mode 1 at aspread 1 is **byte-identical to the input**; mode 5 at
`1 1` is NOT (frq side re-bins channels even at ×1) — documented in the entry.

**Breakpoints (mode 5):** aspread brk (1→1000) exit 0, differs from both endpoint
renders → **capable**; fspread brk (1→4) exit 0, differs from both → **capable**
(banner-confirmed: "aspread and fspread may vary over time").

**Misc:** emits `WARNING: Zero-amp spectral window(s) encountered: orig window(s)
substituted.` on sources with silent windows (exit 0). wav input refused
`Application doesn't work with this type of infile.` flat2.ana run: 2.0230 s.

**Curation:** submode 5 curated (ST's mode). Modes 1–4, 6–7 dropped with evidence
(see findings JSON) — all verified running and distinct, afta8-only priors, reachable
via execute().

## 2. blur noise

Working argv: `blur noise t9m_rich2.ana out.ana 0.5` — exit 0.

- **Mechanism (source-settled):** `specnoise` (dev/blur/blur.c:976-991) —
  `amp' = amp + (meanamp − amp) * noise` per window. **Nothing random is added**; the
  banner's "PUT NOISE IN THE SPECTRUM" misleads — the process flattens channel amps
  toward the window mean. ST's help text ("making the data in every channel equally
  loud") is the accurate description.
- **Content verified:** noise 1 collapses channel-amp CV 2.90 → 0.103, amp-weighted mean
  frq → 11024.5 Hz (flat-spectrum centre); noise 0.5 intermediate (CV 1.455);
  **noise 0 is a byte-identical passthrough** (data chunk == input).
- **Deterministic:** 0.5 twice 1.3 s apart → byte-identical.
- **duration_model `static`:** 2.0230 / 1.5209 at both fixtures. flat2.ana: 2.0230.
- **Ranges:** `ERROR: Parameter[1] Value (-0.100000) out of range (0.000000 to 1.000000)`
  (same for 1.5). Omission: `Insufficient parameters on command line.`
- **Breakpoints:** noise brk (0→1) exit 0, differs from both endpoints → **capable**
  (banner-confirmed).
- wav input refused `Application doesn't work with this type of infile.`

## 3. blur shuffle

Working argv: `blur shuffle t9m_rich2.ana out.ana ab-abab 1` — exit 0.

| domain-image | grpsize | in windows | out windows | rule check |
| ------------ | ------- | ---------- | ----------- | ---------- |
| ab-abab | 1 | 698 | 1393 | 1 + 348×4 ✓ |
| ab-a | 1 | 698 | 349 | 1 + 348×1 ✓ |
| abc-cba | 1 | 698 | 697 | 1 + 232×3 ✓ |
| ab-abab | 4 | 698 | 1393 | 1 + 87×16 ✓ |
| ab-ab | 1 | 698 | 697 | identity loses 1 window ✓ |
| ab-abab | 50 | 698 | 1201 | 1 + 6×200 ✓ |
| ab-abab | 1 | 525 | 1049 | 1 + 262×4 ✓ |

- **Duration rule (empirical, exact in all seven probes):**
  `outwindows = 1 + floor((inwindows − 1) / (dmncnt × grpsize)) × imgcnt × grpsize` —
  window 0 always copied through, trailing incomplete domain block **silently dropped**
  (even `ab-ab` → 697). Approximation `indur × imgcnt/dmncnt`. Synth: ab-abab g1 →
  4.0403 s from 2.023 (flat2 same); ab-abab on rich15 → 3.0418.
- **DROPPED AT SPOT-CHECK — missing engine machinery.** A full entry was drafted
  (duration expression naming the str param, submix-mix skip precedent) and loaded
  cleanly, but the end-to-end `process_impl` spot-check failed:
  `param_type: Parameter 'domain_image' got str 'ab-abab'.` — the engine's
  `validate_params` accepts strings only for `.brk` paths and `aux_file` params
  (`processing.py` `_check_type`), and CDP parses the mapping directly from argv with no
  file fallback (`cdp2k/tklib3.c:646` `read_shuffle_data`/`get_domain_and_image`), so an
  `aux_file` re-model is impossible. specfnu ships its optional `-o` str switch as
  documented execute()-only; that dodge doesn't work here because domain-image is the
  entry's REQUIRED core parameter — every `process()` call would fail. Entry withdrawn;
  what's missing is plain-string parameter support in `_check_type`. Probe findings above
  retained for the eventual unblocking; reachable today via execute().
- **Data validation (verbatim):** `ERROR: INVALID DATA / ERROR: Image symbol [c] not in
  domain.` (`ab-abc`); `ERROR: Bad string for shuffle data: separator missing` (`abab`);
  `ERROR: Duplicated symbol [a] in domain string.` (`aab-ab`); case-sensitive
  (`ab-ABBA` → `Image symbol [A] not in domain.`). `a-aaaa` legal (freeze-stutter).
- **Ranges:** grpsize `ERROR: Parameter[2] Value (0.000000) out of range (1.000000 to
  32767.000000)` (same for −1); runtime `ERROR: CANNOT ACHIEVE TASK: / ERROR:
  Insufficient data in soundfile to do this shuffle.` at grpsize 400 ×domain 2 on 698
  windows. Omitting grpsize: `Insufficient parameters on command line.` — required
  positional (entry default 1).
- **Breakpoints:** grpsize brk →
  `ERROR: Cannot read parameter 1 [bg.brk]: brkpnt_files not permitted.`
- **Deterministic** (abc-cab g3 twice 1.3 s apart byte-identical). wav refused.

## 4. focus focus

Working argv: `focus focus t9_vow2.ana out.ana -p7 16 0.3` — exit 0. (ST: -p 7, pk 16,
bw 0.3.)

- **Formant flag is REQUIRED and POSITION-ENFORCED:** with neither -f nor -p —
  `Formant parameter missing on cmdline.` (no ERROR prefix); flag placed AFTER the
  positionals (`16 0.3 -p7`) — same refusal; both flags —
  `ERROR: Cannot read parameter 1 [-f4]`. Same mechanism as curated strange glis.
- **-f vs -p renders distinct.** -p13 → `ERROR: INVALID DATA / ERROR: Too many
  formant_bands requested: max for this file is 12`; -f1000 → `... max for this file is
  256`; **-f0 crashes**: `ERROR: INTERNAL ERROR: (Bug?) / ERROR: Formant array too small:
  set_specenv_frqs()`; -p0 accepted (exit 0, distinct render, undocumented meaning).
- **Ranges (CDP-enforced):** pk `(1.000000 to 16.000000)` (0/17 refused); bw
  `(0.083333 to 10.000000)` (0/12 refused; min = 1/12 octave — ST's 0.1 floor advisory);
  -b/-t `(5.000000 to 22050.000000)` (−5 / 30000 refused; Nyquist ceiling); -s
  `(2.000000 to 4097.000000)` (1/4098 refused).
- **-s default 9 pinned by rendered equivalence:** flag-less run **byte-identical** to
  `-s9`; `-s100` differs → stability averaging is always on, -s resizes it.
- **-b3000 -t500 silently swapped:** byte-identical to `-b500 -t3000`.
- **-i (quicksearch) is live** (render differs).
- **Breakpoints:** bw brk (0.1→6), bt brk (100→2000), tp brk (1000→8000) all exit 0 and
  differ from both endpoint renders → **capable** (banner-confirmed: "bandwidth, bottom
  frequency & top frequency may vary over time"); pk brk →
  `ERROR: Cannot read parameter 1 [fb_pk.brk]: brkpnt_files not permitted.`; -s brk →
  `... parameter 5 ...`; -p brk → `Cannot read count of formant_bands.`
- **Deterministic** (1.3 s apart byte-identical). **duration_model `static`:** 2.0230 /
  1.5209; flat2.ana runs (2.0230). wav refused
  `Application doesn't work with this type of infile.`

## 5. spec cut

Working argv: `spec cut t9m_rich2.ana out.ana 0.5 1.5` — exit 0.

| input (synth dur) | start | end | outdur (synth) | pred `end − start` | rel err |
| ----------------- | ----- | --- | -------------- | ------------------ | ------- |
| rich2 (2.0230) | 0.5 | 1.5 | 0.9956 | 1.0 | −0.44% |
| rich2 | 0.25 | 1.75 | 1.4948 | 1.5 | −0.35% |
| rich15 (1.5209) | 0.2 | 0.9 | 0.6995 | 0.7 | −0.07% |
| flat2 | 0.5 | 1.5 | 0.9956 | 1.0 | −0.44% |

- **duration_model `expression: endtime - starttime`** — window-quantised slightly short,
  worst −0.44%.
- **NO SILENT SWAP (divergence from sfedit cut):** `1.5 0.5` and `1.0 1.0` both refused
  `ERROR: INCORRECT USE / ERROR: Incompatible start and end times for cut.`
- **Ranges (input-dependent, verbatim):** start
  `ERROR: Parameter[1] Value (-0.500000) out of range (0.000000 to 2.023039)`; end
  `ERROR: Parameter[2] Value (99.000000) out of range (0.002902 to 2.025941)` — and
  **end = the sfprops duration itself (2.029070) is refused** with the same bound; the
  max legal cut is 0 → 2.025941 (697 of 698 windows, exit 0).
- **Breakpoints:** both refused (`Cannot read parameter 1/2 [...]: brkpnt_files not
  permitted.`).
- **Deterministic.** wav refused. ST expresses start/end as percentages (UI conversion);
  CDP takes seconds.

## 6. spec gain

Working argv: `spec gain t9m_rich2.ana out.ana 2.0` — exit 0.

- **Content verified:** channel-wise median amp ratio exactly 2.0 (gain 2) / 0.5
  (gain 0.5) against the input; **gain 1.0 byte-identical passthrough**; gain 0 legal
  (exit 0, silence); gain 10000 legal.
- **Ranges:** `ERROR: Parameter[1] Value (-1.000000) out of range (0.000000 to
  10000.000000)` — ST's 0.001–2 slider advisory. Omission:
  `Insufficient parameters on command line.`
- **Breakpoints:** gain brk (0.1→4) exit 0, differs from both endpoints → **capable**
  (banner-confirmed).
- **Deterministic** (1.3 s apart byte-identical). **duration_model `static`:** 2.0230 /
  1.5209; flat2 2.0230. wav refused.

## 7. spectstr stretch

Working argv: `spectstr stretch t9m_rich2.ana out.ana 2 0 0` — exit 0, **.ana output**
(5.73 MB from a 2.86 MB input; synth 4.0490 s).

- **BANNER BUG (first-class):** the usage line is `spectstr stretch time infile outfile
  timestretch d-ratio di-rand`, but the literal `time` token is rejected by the binary
  itself: `ERROR: INTERNAL ERROR: (Bug?) / ERROR: Failed tp parse input file time`
  (CDP's own "tp" typo, verbatim). The working argv has NO `time` — exactly the engine's
  `[program, mode, inputs, output, params]` shape, so **no new engine machinery is
  needed** (the drop-contingency in the task brief does not trigger).

| input | timestretch | outdur (synth) | pred `indur × ts` | rel err |
| ----- | ----------- | -------------- | ------------------ | ------- |
| rich2 (2.0230) | 2 | 4.0490 | 4.0460 | +0.07% |
| rich2 | 0.5 | 1.0101 | 1.0115 | −0.14% |
| rich15 (1.5209) | 2 | 3.0447 | 3.0418 | +0.10% |
| flat2 (2.0230) | 2 | 4.0490 | 4.0460 | +0.07% |

- **duration_model `expression: indur * timestretch`** (worst +1.2% against the nominal
  2.0 s fixture duration — same window padding as stretch time).
- **Ranges:** timestretch `(0.000100 to 10000.000000)` (0/−1/10001 refused) — identical
  to stretch time; d-ratio `(0.000000 to 1.000000)` (2/−0.5 refused); di-rand
  `(0.000000 to 1.000000)` (2/−1 refused). All three positionals required
  (`ERROR: Insufficient parameters on cmdline.`).
- **timestretch 1 is NOT a passthrough** (data chunk differs from input — windows
  re-interpolated).
- **d-ratio inert without di-rand:** `2 0.5 0` **byte-identical** to `2 0 0`.
- **Discohere deterministic:** `2 0.5 1` twice 1.3 s apart → byte-identical; source
  (dev/science/spectstr.c:1675) uses `drand48()` with no initrand48/srand anywhere in the
  file — the osbind shim's fixed-seed rand() again. Channels are sorted by ascending
  loudness and the quietest `d-ratio × clength` get frq = channel centre ± di-rand/2
  (spectstr.c:1650-1683).
- **Breakpoints:** timestretch brk (1→4) exit 0, output size between the endpoint sizes
  and distinct from both → **capable** (banner: "TIMESTRETCH may itself vary over
  time"); d-ratio / di-rand refused (`Cannot read parameter 2/3 [...]`).
- wav refused `ERROR: INVALID DATA / ERROR: File /tmp/probe/n2.wav is not of correct type`.

## 8. strange waver, submode 1 curated

Working argv: `strange waver 1 t9m_rich2.ana out.ana 4 2 100` — exit 0. Mode 2 appends
an `expon` positional.

- **Mechanism (source):** specwaver/do_waver (dev/strange/strange.c:585-645) — per
  vibrato cycle the stretch factor ramps linearly 1 → stretch → 1 over
  `round(1/(vibfrq × frametime))` windows; frequencies above botfrq stretched by position
  in the spectrum; mode 2 applies `pow(location, expon)` (WAVER_SPECIFIED). **No rand
  anywhere in the waver path.**
- **Mode 2 at expon 1 is byte-identical to mode 1** (verified) — mode 1 is the expon = 1
  special case; expon 3 differs; expon 0 refused
  `ERROR: Parameter[4] Value (0.000000) out of range (0.020000 to 50.000000)`.
- **Ranges (verbatim):** vibfrq **input-dependent at both ends** —
  `ERROR: Parameter[1] Value (0.000000) out of range (0.493598 to 172.265628)` on the
  2.03 s fixture, `(0.656250 to 172.265628)` on the 1.53 s fixture (min ≈ 1/duration,
  max = half the window rate) — **DIVERGENCE: ST's 0.01–150 slider floor is below every
  real file's minimum**; stretch `(1.000000 to 2205.000000)` (0.5 refused; ST/afta8's
  1–4 advisory); botfrq `(5.000000 to 22050.000000)` (−5/30000 refused).
- **stretch 1 is NOT a passthrough** (channel-reassignment fingerprint; differs from
  input).
- **Breakpoints:** vibfrq brk (1→12) and stretch brk (1→3) exit 0, each differs from
  both scalar endpoints → **capable** (banner-confirmed: "vibfrq and stretch may vary
  over time"); botfrq brk refused (`Cannot read parameter 3 [...]`); expon brk (mode 2)
  refused (`Cannot read parameter 4 [...]`).
- **Deterministic** (1.3 s apart byte-identical). **duration_model `static`:** 2.0230 /
  1.5209; flat2 2.0230. Content: on the tone fixture the per-window amp-weighted mean frq
  deviates cyclically with large inharmonic excursions (spikes to 4.3/6.4 kHz from a
  ~1 kHz baseline at the stretch peaks). wav refused
  `Application doesn't work with this type of infile.`
- **Curation:** submode 1 (ST's `strange_waver_1`). Mode 2 dropped (generalisation of
  mode 1, byte-identical at expon 1; execute() reaches it).

---

## Final row confirmations (shared flat-noise fixture, indur 2.0 → analysis 2.023 s)

| row | predicted | actual (synth) | rel err |
| --- | --------- | -------------- | ------- |
| blur chorus 5 (static), aspread 30 / fspread 2 | 2.0 | 2.0230 | 1.15% |
| blur noise (static), noise 0.5 | 2.0 | 2.0230 | 1.15% |
| focus focus (static), -p7 pk 16 bw 0.3 | 2.0 | 2.0230 | 1.15% |
| spec cut, 0.5 → 1.5 | 1.0 | 0.9956 | 0.44% |
| spec gain (static), gain 2.0 | 2.0 | 2.0230 | 1.15% |
| spectstr stretch, ts 2 / 0 / 0 | 4.0 | 4.0490 | 1.22% |
| strange waver 1 (static), 4 / 2 / 100 | 2.0 | 2.0230 | 1.15% |

blur shuffle absent from the row table: DROPPED at the process_impl spot-check (required
free-string parameter the engine cannot pass — see section 3). Measured on the same
fixture anyway: `ab-abab` grpsize 1 → 4.0403 s (rule-exact, 1 + 348×4 windows).

Eight targets probed; 7 entries shipped (blur chorus pinned to submode 5, strange waver
to submode 1); dropped records: blur shuffle (missing engine machinery), blur chorus
submodes 1–4/6–7, strange waver submode 2.

## process_impl spot-checks (engine end-to-end, flat-noise fixture)

| entry | predicted | actual (engine synth path) | rel err |
| ----- | --------- | -------------------------- | ------- |
| blur chorus 5, aspread 30 / fspread 2 | 2.0 | 2.0230 | 1.15% PASS |
| spec cut, 0.5 → 1.5 | 1.0 | 0.9956 | 0.44% PASS |
| spectstr stretch, ts 2 | 4.0 | 4.0490 | 1.22% PASS |
| strange waver 1, 4 / 2 / 100 | 2.0 | 2.0230 | 1.15% PASS |
| blur shuffle, ab-abab / 1 | — | **FAILED param_type** | dropped |
