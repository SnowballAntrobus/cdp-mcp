# Phase 2 — Curated-entry determinism findings

## Why this exists

Phase 1b byte-verified that `pvoc anal` and `pvoc synth` are deterministic across runs (handoff §5.5). The other five Phase 1a curated entries — `blur blur`, `extend loop`, `filter sweeping`, `modify brassage`, and `morph morph` (sm1) — were presumed deterministic but never compared.

Phase 4 Task 12 (process-output cache reactivation) is gated on this verification: a content-addressed cache that materializes outputs by hardlink is only safe on byte-deterministic entries. The high-level design doc moved this sweep from Phase 3 to Phase 2 for that reason.

## Methodology

The test module [tests/test_determinism_sweep.py](../tests/test_determinism_sweep.py) runs each curated entry twice with a canonical param config on a synthetic 2 s mono 44.1 kHz noise burst (exponential-decay envelope, seed 42; seed 43 for the `morph morph` secondary input). Per-entry parameters are pinned in [tests/fixtures/determinism_params.json](../tests/fixtures/determinism_params.json).

The two paired calls use distinct `cache_root` paths so PVOC cache hits cannot short-circuit the second invocation — we measure CDP-level determinism, not cache materialization.

Outputs are byte-compared via SHA-256. On a mismatch, a diagnostic helper classifies the divergence:

- `.wav` outputs → read samples via `soundfile`, compare arrays directly.
- `.ana` outputs → audition-synth both via `pvoc.synth_for_audition` (itself byte-deterministic per Phase 1b §5.5.2), then compare the synthed wavs.

Result categories:

- `deterministic` — sha256 hashes match across runs.
- `non_deterministic_header_only` — decoded samples match across runs but raw bytes differ (likely an embedded timestamp or UUID in a chunk header). Safe to cache by decoded-sample equivalence; raw-byte caching would need adjustment.
- `non_deterministic_samples` — decoded samples themselves diverge. Not safe to cache.

## Test environment

- CDP version (`detect_cdp().version`): `r8`
- CDP install root: `cdpr8/_cdp/_cdprogs` (in-repo copy used for verification; x86_64 binaries running under Rosetta)
- Host OS / arch: `Darwin 24.6.0 (arm64)`
- Python: `3.13.2`
- Repo commit SHA: `af6962e` (the change set adding this test module is uncommitted at verification time; the listed SHA is the parent of the sweep work)
- Verification command: `CDP_PATH=cdpr8/_cdp/_cdprogs pytest tests/test_determinism_sweep.py -v` (5 passed in ~0.7 s across three consecutive runs)

## Results

All five curated entries verified `deterministic` — paired runs produced byte-identical outputs.

| Entry             | Status          | Output sha256 (both runs)                                          |
| ----------------- | --------------- | ------------------------------------------------------------------ |
| `blur blur`       | `deterministic` | `8303c00fa4e7050f6cd19899eefe8483fd3bf224350685c32ed6b078966ebad2` |
| `extend loop`     | `deterministic` | `7885b6dd2aa2039dd53004f1b06bbaa0be78feae523a5b65959460d950edff2a` |
| `filter sweeping` | `deterministic` | `733a15d7faa46da071eeb6017aa0e2a9d9845de19daa52d2d31dc41fd6fb90bc` |
| `modify brassage` | `deterministic` | `4a2abb19520394b4cc40456ee58ac6b96d5690035da69b886c00b80a6799c10b` |
| `morph morph`     | `deterministic` | `8591fcf9abd08ce54038bb9a194b23f6a82c5a105b5fc534eb29e25da537280b` |

## Implications for Phase 4 Task 12

Phase 4's process-output cache reactivation is unblocked on this curated set — the cache key construction in `cache.py` can safely hash raw output bytes for all five `(program, mode)` pairs without risk of stale-output divergence on replay. No `non_deterministic_header_only` adjustments (decoded-sample hashing) or per-entry cache exclusions are needed.

## Caveats

- One canonical param config per entry. Phase 4 may revisit with broader regimes if reactivation moves forward.
- Single synthetic input (2 s noise burst). Long inputs, sustained tones, or stereo material were not exercised here.
- Single CDP build. Re-verify if the CDP install changes.
- Curated-knowledge anomaly noted during planning: the `filter sweeping` knowledge JSON includes a `tail` parameter (`flag: "-t"`), but the upstream CDP docs ([cgrofilt.htm#SWEEPING](https://www.composersdesktop.com/docs/html/cgrofilt.htm#SWEEPING)) only list `-p phase` as an optional flag in SWEEPING mode. The determinism config omits `tail` to match the curated example. Worth checking against the binary's `--help` output in a future curation pass.
