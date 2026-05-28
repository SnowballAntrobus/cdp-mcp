# Phase 2 — Curated-entry determinism findings

> **Status (Phase 2, Task 6.7): the standing determinism sweep was removed.**
> The test module and its param fixture that produced the findings below
> (`tests/test_determinism_sweep.py`, `tests/fixtures/determinism_params.json`)
> were deleted in Task 6.7. The sweep guarded only the Phase 4 Task 12
> process-output cache — a feature that is deferred *and* conditional — while
> generating disproportionate CI noise (flaky ~2/10 under full-suite load).
> This document is **kept** and recast as a CDP-behavior forensic record and a
> Phase 4 precondition input. The valuable, durable part is the CDP r8
> tick-timestamp finding (see **Test infrastructure forensics**); the test
> that produced it is not. Phase 4 Task 12 must redo this investigation
> against the then-current CDP version and curated entry set before relying
> on process-output cacheability — see **Implications for Phase 4 Task 12**.

## Why this existed

Phase 1b byte-verified that `pvoc anal` and `pvoc synth` are deterministic across runs (handoff §5.5). The other five Phase 1a curated entries — `blur blur`, `extend loop`, `filter sweeping`, `modify brassage`, and `morph morph` (sm1) — were presumed deterministic but never compared.

Phase 4 Task 12 (process-output cache reactivation) is gated on this verification: a content-addressed cache that materializes outputs by hardlink is only safe on byte-deterministic entries. The high-level design doc moved this sweep from Phase 3 to Phase 2 for that reason.

## Methodology (now-removed sweep)

The now-removed determinism sweep ran each curated entry twice with a canonical param config on a synthetic 2 s mono 44.1 kHz noise burst (exponential-decay envelope, seed 42; seed 43 for the `morph morph` secondary input). Per-entry parameters were pinned in an accompanying fixture.

The two paired calls used distinct `cache_root` paths so PVOC cache hits could not short-circuit the second invocation — it measured CDP-level determinism, not cache materialization.

Outputs were byte-compared via SHA-256. On a mismatch, a diagnostic helper classified the divergence:

- `.wav` outputs → read samples via `soundfile`, compare arrays directly.
- `.ana` outputs → audition-synth both via `pvoc.synth_for_audition` (itself byte-deterministic per Phase 1b §5.5.2), then compare the synthed wavs.

Result categories:

- `deterministic` — sha256 hashes match across runs.
- `non_deterministic_header_only` — decoded samples match across runs but raw bytes differ (likely an embedded timestamp or UUID in a chunk header). Safe to cache by decoded-sample equivalence; raw-byte caching would need adjustment.
- `non_deterministic_samples` — decoded samples themselves diverge. Not safe to cache.

## Test environment (point-in-time, when the sweep ran)

- CDP version (`detect_cdp().version`): `r8`
- CDP install root: `cdpr8/_cdp/_cdprogs` (in-repo copy used for verification; x86_64 binaries running under Rosetta)
- Host OS / arch: `Darwin 24.6.0 (arm64)`
- Python: `3.13.2`
- Repo commit SHA: `af6962e` (the change set adding the sweep module was uncommitted at verification time; the listed SHA is the parent of the sweep work)

## Results — preliminary Phase 2 snapshot (5 entries, CDP r8)

> **Caveat:** this is a point-in-time observation from the now-removed sweep,
> **not a maintained guarantee.** It covered only the five Phase 1a curated
> entries against a single CDP r8 build and one canonical param config per
> entry. Do not treat it as settling cacheability for any later entry set or
> CDP version — Phase 4 Task 12 must re-verify (see below).

All five curated entries observed **sample-deterministic with header-only non-determinism**.

Initial Phase 2 Task 1 verification reported all five entries as raw-byte `deterministic` (single paired run, captured under same tick). Phase 2 Task 2.5 follow-up investigation (after the sweep flaked at ~1-in-5 isolation rate and ~1-in-3 full-suite rate) found the divergence is in CDP-embedded tick-counter metadata; samples are bit-identical in every observed case. See **Test infrastructure forensics** below for the full trace.

| Entry             | Status                              | Output sha256 (when within-tick)                                   |
| ----------------- | ----------------------------------- | ------------------------------------------------------------------ |
| `blur blur`       | `non_deterministic_header_only` ⁺ʰ | `8303c00fa4e7050f6cd19899eefe8483fd3bf224350685c32ed6b078966ebad2` |
| `extend loop`     | `non_deterministic_header_only` ⁺ʰ | `7885b6dd2aa2039dd53004f1b06bbaa0be78feae523a5b65959460d950edff2a` |
| `filter sweeping` | `non_deterministic_header_only` ⁺ʰ | `733a15d7faa46da071eeb6017aa0e2a9d9845de19daa52d2d31dc41fd6fb90bc` |
| `modify brassage` | `non_deterministic_header_only` ⁺ʰ | `4a2abb19520394b4cc40456ee58ac6b96d5690035da69b886c00b80a6799c10b` |
| `morph morph`     | `non_deterministic_header_only` ⁺ʰ | `8591fcf9abd08ce54038bb9a194b23f6a82c5a105b5fc534eb29e25da537280b` |

⁺ʰ Two paired runs that fall in the same CDP tick window produce byte-identical output (the sha256 column above); paired runs that straddle a tick boundary differ only in a handful of metadata bytes (PEAK chunk timestamp on `.wav`; a single byte in a `LIST/adtl/note/sfif DATE` ASCII-hex field on `.ana`). Decoded samples are identical in every case.

## Implications for Phase 4 Task 12

This is the primary forward-looking content of the doc. Two instructions to
whoever implements the process-output cache:

**1. Redo the determinism investigation before relying on cacheability.** The
snapshot above is preliminary and stale by Phase 4: it covered only the five
Phase 1a entries against one CDP r8 build, whereas the curated entry set will
be ~30 (post-Phase-3) by the time the cache is designed. Re-run the sweep
against (a) the **then-current CDP version** and (b) the **then-current curated
entry set**, with broader param regimes and input material than the single 2 s
noise burst used here. Treat the tick-timestamp finding below as a starting
point, not a settled result.

**2. Key the cache on sample-equivalence, not raw-file sha256.** CDP r8 output
is sample-stable but byte-unstable (the tick metadata — see forensics below).
Raw-byte keys would make most lookups miss (whenever the cached entry and the
current run fall in different ticks) and fragment the cache by tick window
rather than by actual computation. Two ways to implement decoded-sample
equivalence:

1. **Sample-hash cache keys.** For `.wav`, read via `soundfile.read` and hash the sample array bytes. For `.ana`, hash everything past the CDP RIFF-WAVE header (the data chunk starts after the `LIST/adtl/...` metadata).
2. **Header-stripped raw hash.** Identify the volatile-byte regions (one in `.wav`, one in `.ana`) and zero them before sha256.

Option 1 is the more durable choice — it survives any future CDP header-layout shift.

On the five-entry snapshot, no per-entry cache exclusions were needed; all five were safe to cache by sample equivalence. Whether that holds for the wider Phase 4 entry set is exactly what instruction 1 above must re-establish.

## Test infrastructure forensics

### The flake

The now-removed determinism sweep failed roughly 1-in-5 isolation runs and 1-in-3 full-suite runs when verifying against `cdpr8/_cdp/_cdprogs`. The failing parametrized case varied (`blur_blur`, `extend_loop`, `morph_morph`, `filter_sweeping` all observed). Phase 2 Task 2.5 investigated; Task 6.7 later removed the test entirely (this flake is what motivated the removal — it guarded only the deferred Phase 4 cache).

### Investigation outcome

CDP r8 binaries embed a tick-counter (likely Unix seconds or an internal monotonic) into every output file's metadata:

- **`.wav` outputs** carry the counter in two places:
  - 32-bit little-endian field inside the **PEAK chunk** (~byte 80 of the file).
  - ASCII-hex field inside a **`LIST/adtl/note/sfif DATE`** subchunk.
- **`.ana` outputs** (which use a RIFF-WAVE-style container) carry the same `DATE` ASCII-hex field at offset 179. Single-byte difference between consecutive ticks.

Paired runs that fall in the same tick window produce byte-identical output. Paired runs that straddle a tick boundary differ only in those metadata bytes. Decoded sample/frame data is bit-identical in every observed case.

### Diagnostic capture

Reproduced under a `CDP_MCP_DETERMINISM_DIAGNOSTICS=1` env-guarded instrumentation that lived in the now-removed sweep. Sample failure trace for `extend loop`:

```
DETERMINISM DIAGNOSTIC — extend loop: expected='deterministic', observed='non_deterministic_header_only'
  sha_a:    6ebded513f7a213df80863ff5f9271f150f20e2fe88d0bbee5339da6fc1ce80b
  sha_b:    bfc22202ca57f058a12d4eb67b91712e76dc2da9fe28326d7742692ea45ec2d8
  timing:   A→B start delta=0.016s
  head_a:   ...PEAK [...]3076176a[...]DATE\n30761764A1\n...
  head_b:   ...PEAK [...]3176176a[...]DATE\n31761764A1\n...
  samples identical (header-only divergence)
  cache_root_a: (empty)
  cache_root_b: (empty)
```

Sample failure trace for `blur blur` (`.ana` output, found via direct raw-byte comparison):

```
DIVERGENCE FOUND
file size: 2866662 bytes
Different byte indices: total: 1 bytes, first 20: [179]
ranges: [(179, 179)]
[179:180] A=45 (b'E')
[179:180] B=46 (b'F')
```

The single divergent byte at offset 179 lies inside the `LIST/adtl/note/sfif DATE` field of the `.ana` RIFF-WAVE container; the remaining 2,866,661 bytes (the spectral frame data) are bit-identical.

### Resolution

Per the Phase 2 Task 2.5 plan's Stage 1 interpretation guide ("All failures `non_deterministic_header_only` → jump to Stage 4 / Outcome 2"), no bisection or production-code change was needed.

At Task 2.5 the sweep's `DETERMINISM_EXPECTATIONS` was changed from `str` values to `frozenset[str]` per entry, accepting `{"deterministic", "non_deterministic_header_only"}` for all five entries — either outcome is correct given CDP's tick-based metadata, while a `non_deterministic_samples` observation would have fallen outside the set and failed loudly. That tolerance kept the sweep green but did not address the root annoyance (the test guarded a deferred feature at real cost), which is why Task 6.7 removed it outright. If Phase 4 re-introduces a sweep, this `frozenset` expectation shape and the `CDP_MCP_DETERMINISM_DIAGNOSTICS`-gated diagnostic dump are the patterns worth resurrecting — both are recorded here and in git history.

### Hypotheses ruled out during the audit

A pre-investigation audit ruled out several candidates before they were tested:

| Hypothesis | Status |
| ---------- | ------ |
| Numpy global RNG state | Ruled out — no `np.random.seed` or stdlib `random.seed` anywhere; all RNGs are instance-scoped. |
| Direct `os.environ[...]=` writes leaking across tests | Ruled out — only the two autouse fixtures write env vars, both with `finally`-block restore. |
| `tempfile.mkdtemp` without cleanup | Ruled out — no bare `mkdtemp` calls; everything uses pytest's `tmp_path`. |
| File-descriptor exhaustion | Ruled out — `ulimit -n = 1048576`. |
| `~/.cdp_mcp/cache/` import-time mkdir contaminates | Mechanically present at [server.py:77-78](../src/cdp_mcp/server.py) but irrelevant — no production code path consults that path; all caches kwarg-isolated. Worth fixing for hygiene as a future task. |
| `pytest-randomly` shuffles order | Ruled out — not installed. |

Cache isolation (kwarg-`cache_root` plumbing across `process_impl` and `synth_for_audition`) was confirmed working perfectly: every failure trace showed empty `cache_root_a` and `cache_root_b` directories.

## Caveats

- One canonical param config per entry. Phase 4 may revisit with broader regimes if reactivation moves forward.
- Single synthetic input (2 s noise burst). Long inputs, sustained tones, or stereo material were not exercised here.
- Single CDP build. Re-verify if the CDP install changes.
- All five entries report `non_deterministic_header_only` rather than raw-byte `deterministic`. The underlying samples are bit-identical — see **Test infrastructure forensics** above for the full mechanism. Phase 4's process-output cache must use decoded-sample equivalence, not raw-file sha256.
- Curated-knowledge anomaly noted during planning: the `filter sweeping` knowledge JSON includes a `tail` parameter (`flag: "-t"`), but the upstream CDP docs ([cgrofilt.htm#SWEEPING](https://www.composersdesktop.com/docs/html/cgrofilt.htm#SWEEPING)) only list `-p phase` as an optional flag in SWEEPING mode. The determinism config omits `tail` to match the curated example. Worth checking against the binary's `--help` output in a future curation pass.
