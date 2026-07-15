# MIR Gap Analysis — what analyze() can and cannot perceive

**Date:** 2026-07-15 · **Scope:** empirical audit of the `analyze()` scorecard against the
perceptual claims made by the 43 curated knowledge entries
(`src/cdp_mcp/knowledge/data/*.json`). Analysis only — no source changes.

Method: extract the perceptual-claim vocabulary from every curated `description` /
`musical_use`; cluster it into perceptual dimensions; then render real before/after pairs
with the CDP 7.1 binaries (`/tmp/CDP8/NewRelease`) and measure whether the *current*
scorecard fields move when the claimed percept changes — versus a set of cheap candidate
features. All numbers below are measured, not estimated; commands are reproducible
(§3.0).

---

## 1. Vocabulary → perceptual dimensions

Term sweep over `description + musical_use` of all 43 entries (regex counts, entry
citations abbreviated):

| # | Dimension | Entries (n) | Representative claims |
|---|-----------|-------------|----------------------|
| D1 | **Noisiness / pitchedness** | 21 | focus_exag "by 10 … distinctly fuzzy and noisy", "toward pitched resonance or toward noise"; blur_spread "breathy, airy wash"; strange_glis "high values push noise into the result"; hilite_trace "ghostly … skeletal"; blur_suppress "noise constituents, reverberant tails"; distort_omit "dissolve … into crackle" |
| D2 | **Brightness / register** | 17 (+9 register) | filter_lohi "deep and rumbling", "thin"; strange_invert "much brighter timbre"; distort_fractal "sheen … floating above"; focus_fold "deep, muffled" vs "thin, slightly ringing"; modify_speed "deep, rich tones"; distort_divide "subsonically low" |
| D3 | **Roughness / texture / grain** | 26 | blur_avrg "grit and subtle roughening"; distort_divide "roughening without being too violent"; distort_average "mushy, watery"; distort_repeat "raw, grainy"; extend_scramble "smearing … into a texture"; modify_brassage "granular grain" |
| D4 | **Transient character** | 16 | blur_blur "softens transients", "percussive material into spectral pads"; envel_dovetail "smooth a click"; modify_stack "clearly defined attack"; modify_radical "swelling pre-attacks" |
| D5 | **Pitch / register motion** | 19 | strange_glis "endlessly glissandoing"; focus_accu "slow glissandos inside the spectrum"; modify_speed "glissandi, tape-wobble … airplane-takeoff"; distort_multiply "pitch rises with each increase of N"; modify_revecho "audible pitch bends" |
| D6 | **Harmonicity / inharmonicity** | 17 | stretch_spectrum "a harmonic sound becomes inharmonic … bell- or gong-like multiple pitches"; modify_stack "fuse … with new harmonic content"; strange_invert "more 'harmonic' quality"; modify_revecho "pitched resonances"; specfnu "ringing resonant bands" |
| D7 | **Temporal evolution** | 27 | blur_blur "dissolve gradually into its own ambience"; blur_scatter "disintegrate or re-materialise across its length"; combine_diff "sweep from intact to fully hollowed-out"; blur_drunk "wandering"; focus_exag "travels between the pitched-resonant and noisy states"; distort_average "slide … from intact to frozen" |
| D8 | **Dynamics envelope** | 21 | bounce_bounce "each repeat quieter, decaying to endlevel"; envel_dovetail "emerge slowly out of silence"; blur_suppress "drastic level loss … residue at −42 dBFS"; focus_accu decay/ring |
| D9 | **Stereo image** | 16 mention stereo; ~4 make image claims | texture_simple "output is always STEREO", `spread` 0–1; modify_revecho, modify_stack stereo-capable |
| D10 | **Density / pulse / repetition** | 13 | extend_doublets "pulsing, mechanical throb", "micro-stutter"; bounce_bounce "accelerating repeats"; extend_loop "regular pulsation"; texture_simple "cloud, stream, or chord"; focus_step "regular 'jangling'" |

Temporal evolution (D7) is the *largest* cluster — 27 of 43 entries describe how a sound
changes **across its length** (usually via breakpoint ramps) — and it is the dimension the
current design is blindest to, since every scorecard field is a whole-file mean.

---

## 2. Coverage matrix (current analyze())

Current concise scorecard: `duration_s, peak_dbfs, rms_db, lufs_i, spectral_centroid_hz,
spectral_flux, zero_crossing_rate, onset_count, n_channels, sample_rate`
(`src/cdp_mcp/analysis.py::extract_scorecard`). Verbose adds MFCC mean/std, chroma mean,
tempo_bpm, per-channel levels (`extract_verbose`).

| Dimension | Current fields that respond | Status |
|-----------|-----------------------------|--------|
| D1 noisiness | zcr, centroid (confounded proxies) | **Partial** — cannot distinguish "noisier" from "brighter" (§3.a vs §3.d) |
| D2 brightness | centroid | **Covered** (rolloff sharpens attribution, §3.e) |
| D3 roughness/grain | flux, weakly | **Uncovered** — no envelope-modulation measure |
| D4 transients | onset_count, flux | **Partial** — direction correct but coarse; centroid/zcr actively mislead (§3.c) |
| D5 pitch motion | — (means hide motion) | **Uncovered** statically; only via visualize() images |
| D6 harmonicity | — (chroma is pitch-class, not harmonicity) | **Uncovered** (§3.b) |
| D7 temporal evolution | — | **Uncovered** numerically (progression()/visualize() are PNG-only) (§3.f) |
| D8 dynamics envelope | peak/rms/lufs (static) | **Partial** — no shape; crest_db exists in compare() but not analyze() |
| D9 stereo image | n_channels; per-channel levels (verbose) | **Partial** — no decorrelation/width measure (§3.g) |
| D10 density/pulse | onset_count, tempo_bpm (verbose) | **Partial** — no pulse-strength/regularity |

---

## 3. Empirical discrimination tests

### 3.0 Setup (reproducible)

Probe sources (3 s, mono, 44.1 kHz, PCM-16, generated with numpy/soundfile):

- `tone.wav` — 220 Hz, 8 harmonics at 1/n amplitude
- `clicks.wav` — 4 ms noise-burst clicks at 6 Hz (17 events)
- `noise.wav` — white noise
- `seq.wav` — 1 s 200 Hz tone → 1 s white noise → 1 s 1400 Hz tone

CDP renders (`B=/tmp/CDP8/NewRelease`, CDP Release 7.1):

```
$B/pvoc anal 1 tone.wav tone.ana ; $B/pvoc anal 1 clicks.wav clicks.ana
$B/focus exag tone.ana exag10.ana 10           ; $B/pvoc synth exag10.ana exag10.wav
$B/stretch spectrum 1 tone.ana sspec.ana 250 2.5 1 ; $B/pvoc synth sspec.ana sspec.wav
$B/blur blur clicks.ana blur50.ana 50          ; $B/pvoc synth blur50.ana blur50.wav
$B/distort multiply tone.wav multN.wav N          # N = 2, 4, 8
$B/filter lohi 1 noise.wav lopass.wav -60 500 1000 -t0.05
$B/extend scramble 1 seq.wav scram.wav 0.08 0.25 3.0 -s1
echo 60 > note.txt
$B/texture simple 5 tone.wav tex.wav note.txt 3.0 0.08 2 0 1 1 40 100 0.15 0.5 48 84 0 -s0.9 -r1
```

Candidate features (all librosa/numpy): spectral flatness (mean), rolloff-85 %, bandwidth,
pyin f0 (median, p05–p95, voiced fraction, mean voiced probability), onset-strength
mean/max, attack sharpness (max positive frame-diff of the RMS envelope, normalised),
inharmonicity (mean relative deviation of the top-12 spectral peaks from a best-fit
harmonic grid, f0 grid-searched 60–450 Hz), envelope-modulation proxy (fraction of
RMS-envelope AC spectrum energy in 20–150 Hz; envelope at hop 64 → 689 Hz frame rate),
stereo width (1 − |corr(L,R)|), and a 16-point trajectory of {rms_db, centroid, flatness}.

### 3.a focus exag 10 — claim: "distinctly fuzzy and noisy" (D1)

| Feature | tone.wav | exag10.wav | Δ |
|---|---|---|---|
| centroid_hz (current) | 649.7 | 4477.9 | ×6.9 |
| zcr (current) | 0.0099 | 0.0841 | ×8.5 |
| flux (current) | 0.145 | 0.500 | ×3.4 |
| rms_db (current) | −11.7 | −35.6 | −23.9 dB (level confound) |
| **spectral_flatness** | 3.1e-9 | 9.4e-3 | **×3·10⁶** |
| **pyin voiced_prob_mean** | 0.777 | 0.463 | −40 % |
| env-mod proxy | 0.004 | 0.243 | ×61 |

**Verdict: current-weak (ambiguous).** The scorecard *moves*, but the same centroid/zcr
signature is produced by a purely harmonic brightening: `distort multiply 8` yields
centroid 7722 Hz and zcr 0.0794 — *higher* than exag10 — while remaining harmonic
(inharmonicity 0.0006). Nothing in the current scorecard can tell "went noisy" from "went
bright". Flatness (relative change six orders of magnitude) plus the voiced-probability
drop name the claim directly. (Note the 24 dB level drop from focus exag — compare()'s
loudness matching is the right harness for strict A/B; the spectral ratios here survive
it.)

### 3.b stretch spectrum (divide 250 Hz, maxstretch 2.5) — claim: "harmonic becomes inharmonic … bell-like" (D6)

| Feature | tone.wav | sspec.wav | Δ |
|---|---|---|---|
| centroid_hz (current) | 649.7 | 813.7 | +25 % |
| zcr (current) | 0.0099 | 0.0159 | +61 % |
| flux (current) | 0.145 | 0.751 | ×5.2 (beating, not attribution) |
| onset_count (current) | 28 (spurious) | 69 (spurious) | meaningless |
| **inharmonicity** | 0.0019 (grid f0 110.0) | **0.0140** (grid collapses to 73.5) | **×7.2** |
| **pyin voiced_prob_mean** | 0.777 | 0.389 | halved |
| spectral_flatness | 3.1e-9 | 2.2e-5 | still ≈0 — *correctly* says "not noise" |

**Verdict: current-blind.** A +25 % centroid shift is indistinguishable from mild EQ; the
flux jump reflects partial beating but attributes nothing. The harmonic-grid deviation is
the only feature that states the claim ("partials no longer sit on a harmonic series"),
and flatness staying near zero correctly separates *inharmonic* from *noisy* — the two
D1/D6 axes the scorecard currently conflates. Bonus finding: **onset_count reports 28
onsets on a 3 s steady tone** — librosa's default peak-picking on near-silent novelty
curves is unreliable on sustained material; worth a documented caveat regardless of any
feature additions.

### 3.c blur blur 50 on a click train — claim: "softens transients" (D4)

| Feature | clicks.wav | blur50.wav | Δ |
|---|---|---|---|
| onset_count (current) | 17 (= ground truth events) | 4 | −76 % ✓ |
| flux (current) | 4.58 | 0.88 | ÷5.2 ✓ |
| centroid_hz (current) | 3039 | 4119 | **UP — misleading** |
| zcr (current) | 0.011 | 0.157 | **×14 — misleading** (reads "noisier") |
| **attack_sharpness** | 1.00 | 0.087 | **÷11.5** |
| onset_strength_max | 65.6 | 22.0 | ÷3.0 |
| crest_db | 35.5 | 23.7 | −11.8 dB |
| **env-mod proxy** | 0.707 | 0.005 | **÷141** — the pulse literally vanishes |

**Verdict: partially covered.** onset_count and flux move in the right direction, so the
agent isn't blind — but two of five spectral fields move the *wrong* way (blurring smeared
click energy into a continuous hiss-wash, raising zcr and centroid). Attack sharpness and
the envelope-modulation proxy are monotonic, unambiguous, and near-free to compute.

### 3.d distort multiply N = 2/4/8 — claim: "pitch rises with each increase of N" (D5)

| Feature | tone | N=2 | N=4 | N=8 |
|---|---|---|---|---|
| zcr (current) | 0.0099 | 0.0198 | 0.0397 | 0.0794 — **exactly ×2/×4/×8** |
| centroid_hz (current) | 650 | 2265 | 4379 | 7722 |
| rolloff85_hz (candidate) | 1313 | 3727 | 8261 | 15450 |
| **pyin f0 median** | 220.1 | 220.1 | 220.1 | 220.1 — **fails** |
| pyin voiced_prob_mean | 0.777 | 0.754 | 0.683 | 0.424 |

**Verdict: covered by current — and the fancy candidate loses.** zcr tracks the wavecycle
multiplication perfectly. pyin reports 220.1 Hz at every N because the waveform stays
220 Hz-*periodic* (each wavecycle is replaced by N copies inside its own span); the
perceived pitch rise is spectral, not periodicity-based. Two lessons: (1) the existing
scorecard genuinely covers this claim; (2) an f0 tracker must ship with the documented
caveat that it measures periodicity, and should be read *alongside* zcr/centroid, never
instead of them. voiced_prob again supplies the useful extra axis ("less cleanly pitched
as N grows").

### 3.e filter lohi lowpass (pass 500, stop 1000, −60 dB) on noise — claim: "deep and rumbling" (D2)

| Feature | noise.wav | lopass.wav | Δ |
|---|---|---|---|
| centroid_hz (current) | 11021 | 1007 | ÷10.9 ✓ |
| **rolloff85_hz** | 18747 | 1702 | ÷11 — and directly interpretable: "no energy above ≈1.7 kHz" |
| bandwidth_hz | 6372 | 1694 | ÷3.8 |
| spectral_flatness | 0.560 | 0.0077 | ÷73 — caveat: flatness conflates "lowpassed noise" with "tonal" |
| zcr (current) | 0.497 | 0.021 | ÷24 |

**Verdict: covered.** Centroid alone answers the claim. Rolloff's value is attribution —
it is a *frequency in Hz an agent can act on* (e.g. choose the next filter's pass-band),
where centroid is a weighted abstraction. The flatness collateral drop is the documented
caveat for D1: flatness must be read jointly with rolloff/centroid.

### 3.f extend scramble on a 3-section sequence — claim: "jumbled version of the source" (D7)

Static means (the whole current scorecard view):

| Feature | seq.wav | scram.wav | Δ |
|---|---|---|---|
| rms_db | −9.48 | −9.63 | 0.15 dB |
| centroid_hz | 4289 | 4788 | +12 % |
| flatness | 0.185 | 0.190 | +2.5 % |
| zcr | 0.191 | 0.197 | +3 % |
| onset_count | 1 | 12 | sees the splices, not the wandering |

16-point centroid trajectory (Hz):

```
seq:   203  202  202  202  202  9284 11053 11035 11067 11068 7861 1401 1401 1401 1401 1402
scram: 11048 4009  536  843 10213 11094 5368 1402  6725 2936  6814  205 1027  409 10116 3867
```

Flatness trajectory tells the same story (seq: 0,0,0,0,0,.42,.56,.56,.56,.56,.34,0,0,0,0,0
— clean tone→noise→tone; scram: 12+ reversals). Quantified: centroid total variation
20.6 kHz (seq) vs 67.8 kHz (scram) — **×3.3**; 3 monotonic plateaus vs ~13 direction
reversals.

**Verdict: current-blind by construction.** Whole-file means are (approximately)
permutation-invariant; no added *static* feature fixes this. The time axis is the answer,
and 48 numbers (16 × 3 features) suffice where currently only progression()/visualize()
PNGs carry the information. This blindness also afflicts **cluster()** — its 28-dim vector
(MFCC μ/σ, centroid μ, RMS μ) would place `seq.wav` and `scram.wav` in the same cluster.

### 3.g texture simple — claim: "output is always STEREO … cloud" (D9/D10)

| Feature | tone.wav (source) | tex.wav |
|---|---|---|
| n_channels (current) | 1 | 2 — says stereo *exists*, nothing about the image |
| **stereo_width = 1 − \|corr(L,R)\|** | n/a | **0.40** — genuine decorrelation measured |
| onset_count | — | 24 (density claim partially served) |

**Verdict: current-weak.** Channel count and per-channel levels can't distinguish a
dual-mono bounce (width 0.0) from a spatialised cloud (0.40 here).

---

## 4. Recommendations (ranked)

Measured compute cost on a 3 s mono 44.1 kHz file (containerised Linux; first-STFT warm-up
excluded where shared):

| Feature | Cost | Feature | Cost |
|---|---|---|---|
| spectral_flatness | 3 ms | inharmonicity (peak/grid) | 11 ms |
| rolloff-85 | 4 ms | env-mod proxy | 1 ms |
| bandwidth | 6 ms | 16-pt trajectory ×3 | 6 ms |
| attack sharpness | 1 ms | stereo width | <5 ms |
| crest_db | ~0 (peak & rms already computed) | **pyin f0 block** | **2224 ms** (≈0.75× realtime — the only expensive one) |

### 4.1 Concise scorecard additions (cheap, always-on)

1. **spectral_flatness** — the D1 axis for ~21 entries; ×3·10⁶ in §3.a while correctly
   staying ≈0 in §3.b. Report as `flatness_db = 10·log10(flatness)` (raw values span 1e-9
   … 0.9; dB reads better and avoids "0.0" rounding). 3 ms.
2. **spectral_rolloff85_hz** — interpretable spectral-edge in Hz; ÷11 in §3.e, ×N-tracking
   in §3.d; directly actionable for choosing filter bands. 4 ms.
3. **crest_db** — free (fields already computed; `compare()` already derives it privately
   in `_crest_db`). One-number transient/dynamics summary: 35.5→23.7 dB in §3.c.

### 4.2 Verbose additions

1. **f0 block** (pyin: `f0_median_hz`, `f0_p05_p95_hz`, `voiced_fraction`,
   `voiced_prob_mean`) — `voiced_prob_mean` is the pitch-salience axis, monotone in every
   probe (§3.a 0.78→0.46, §3.b 0.78→0.39, §3.d 0.75→0.42). Ship with the §3.d caveat
   (periodicity ≠ perceived spectral pitch). 2.2 s → verbose-only.
2. **inharmonicity** (+ best-grid f0) — the only feature that names D6; ×7.2 in §3.b.
   11 ms.
3. **env_mod_20_150** (roughness/pulse proxy) — D3 + D10 (throb, pulsing, grain); ÷141 in
   §3.c, ×61 in §3.a. 1 ms.
4. **attack_sharpness + onset_strength_max** — D4; ÷11.5 in §3.c where centroid/zcr
   misled. 1 ms.
5. **stereo_width** (1 − |corr(L,R)|, stereo only) — D9; 0.40 measured on texture simple
   output. <5 ms.
6. **spectral_bandwidth** — secondary D2 attribution (÷3.8 in §3.e). 6 ms. Lowest
   priority; drop first if the block feels crowded.

### 4.3 Trajectory block (the time-axis decision)

**Recommend: a `trajectory` key inside `analyze(verbose=True)` — not a new tool, not a new
mode.** Shape: **16 points × {rms_db, centroid_hz, flatness}** = 48 rounded numbers
(~120–180 tokens), computed in 6 ms from arrays the other features already produce.
Rationale:

- It is the *only* fix for D7 (27/43 entries) — §3.f shows static stats blind at ≤12 %
  while the trajectory shows ×3.3 total variation and 13 reversals vs 3 plateaus.
- It numerically verifies every "breakpoint ramp" claim (dissolve/disintegrate/sweep)
  that today can only be eyeballed via `progression()`/`visualize()` PNGs — the
  token-cheap complement, not a replacement, for those tools.
- A new analyze mode would add API surface with zero compute saving (6 ms); a separate
  tool would duplicate target resolution/auto-synth plumbing. If the verbose payload ever
  needs trimming, an 8-point `rms_db`-only mini-trajectory in the concise scorecard is the
  defensible subset.
- These three features were chosen empirically: rms_db carries D8 shapes
  (bounce/dovetail/decay), centroid carries D2/D5 motion (gliss, sweeps), flatness carries
  D1 evolution (dissolve-into-noise). f0 trajectory was considered and rejected: pyin cost
  ×1, and §3.d shows its blind spot.

### 4.4 Explicitly NOT recommended

- **Beat/tempo machinery beyond the existing `tempo_bpm`** (tempogram, beat grids, PLP):
  the corpus is sound-design vocabulary; no entry makes a metric claim finer than
  "pulsing/accelerating", which onset_count + env-mod + the rms trajectory already cover.
  beat_track already returns junk on drones — invest nothing more here.
- **Key detection / key labels**: `chroma_mean` exists in verbose; zero curated claims
  mention key or tonality. texture_simple's harmonic *fields* are inputs, not outputs to
  detect.
- **Genre/instrument taggers or learned embeddings (VGGish/CLAP/PANNs)**: heavy
  dependencies, opaque axes; nothing in the vocabulary needs them, and cluster() needs
  interpretable dimensions more than discriminative ones.
- **Full per-frame matrices in tool output**: thousands of floats; the 16-point trajectory
  is the deliberate compromise (same reasoning already in `extract_verbose`'s docstring).
- **Formal psychoacoustic roughness models (Daniel–Weber, Sethares)**: the 1 ms
  envelope-band proxy achieved ÷141 discrimination in §3.c; a model adds a dependency for
  marginal gain on this vocabulary.
- **More onset machinery (backtracking, adaptive thresholds)**: instead *document* the
  measured caveat that onset_count is unreliable on sustained material (28 spurious onsets
  on a 3 s steady tone, §3.b) and let flux/attack_sharpness carry D4.
- **LRA / momentary-loudness stats**: crest_db + the rms trajectory cover every D8 claim in
  the corpus at a fraction of the tokens.

### 4.5 cluster() feature vector

`_extract_features` (28-dim: MFCC 13 μ+σ, centroid μ, RMS μ,
`src/cdp_mcp/tools/cluster.py:367`) shares the scorecard's two blind spots. Additions that
would improve cluster separation, in order: **flatness μ** (D1 — currently a noisy pad and
a bright tone can co-cluster), **centroid total-variation and flatness σ over time** (D7 —
§3.f proves ordered vs scrambled variants are currently indistinguishable),
**env_mod_20_150** (D3/D10 — separates throbbing textures from steady beds), **rolloff μ**
(cheap D2 sharpening). All are O(ms) and reuse arrays already computed.

---

## Appendix: full measured feature table

| file | centroid | flux | zcr | onsets | flatness | rolloff85 | bw | f0med | vprob | inharm | attack | env-mod | crest dB | rms dB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tone | 649.7 | 0.145 | 0.0099 | 28 | 3.1e-9 | 1313 | 510 | 220.1 | 0.777 | 0.0019 | 0.163 | 0.004 | 5.7 | −11.7 |
| exag10 | 4477.9 | 0.500 | 0.0841 | 65 | 9.4e-3 | 12481 | 6096 | 220.1 | 0.463 | 0.0056 | 0.168 | 0.243 | 15.7 | −35.6 |
| sspec | 813.7 | 0.751 | 0.0159 | 69 | 2.2e-5 | 1394 | 1577 | 226.5 | 0.389 | 0.0140 | 0.164 | 0.016 | 8.9 | −12.5 |
| clicks | 3039 | 4.578 | 0.0112 | 17 | 0.888 | 5195 | 1805 | — | 0.003 | 0.0020 | 1.000 | 0.707 | 35.5 | −38.6 |
| blur50 | 4119 | 0.881 | 0.1571 | 4 | 0.740 | 7291 | 2530 | — | 0.004 | 0.0031 | 0.087 | 0.005 | 23.7 | −40.0 |
| mult2 | 2265 | 0.230 | 0.0198 | 2 | 2.4e-4 | 3727 | 3413 | 220.1 | 0.754 | 0.0013 | 0.167 | 0.161 | 5.7 | −11.7 |
| mult4 | 4379 | 0.254 | 0.0397 | 1 | 1.1e-3 | 8261 | 4711 | 220.1 | 0.683 | 0.0010 | 0.177 | 0.129 | 5.6 | −11.7 |
| mult8 | 7722 | 0.252 | 0.0794 | 1 | 9.9e-3 | 15450 | 6084 | 220.1 | 0.424 | 0.0006 | 0.180 | 0.246 | 5.8 | −11.8 |
| noise | 11021 | 1.005 | 0.4973 | 4 | 0.560 | 18747 | 6372 | — | 0.009 | 0.0014 | 0.174 | 0.716 | 13.1 | −19.2 |
| lopass | 1007 | 0.962 | 0.0210 | 5 | 0.0077 | 1702 | 1694 | — | 0.010 | 0.0181 | 0.239 | 0.729 | 12.1 | −37.4 |
| seq | 4289 | 0.532 | 0.1909 | 1 | 0.185 | 6967 | 2317 | 803.8 | 0.569 | 0.0035 | 0.190 | 0.443 | 9.5 | −9.5 |
| scram | 4788 | 1.306 | 0.1965 | 12 | 0.190 | 8010 | 2766 | 1397.4 | 0.525 | 0.0023 | 0.178 | 0.426 | 9.6 | −9.6 |
| tex (stereo, width 0.40) | 1154 | 0.742 | 0.0345 | 24 | ~0 | 2180 | 1161 | 171.7 | 0.043 | 0.0159 | 0.117 | 0.500 | 13.7 | −16.7 |

f0med "—" = voiced fraction ≈ 0 (pyin found nothing to track). All features computed on
mono downmix at native sr, matching `extract_scorecard`'s conventions.
