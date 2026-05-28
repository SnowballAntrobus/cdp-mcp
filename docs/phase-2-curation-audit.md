# Phase 2 — Curated-entry numeric/formula audit

## Why this exists

A manual Claude Desktop check of `breakpoint()` surfaced a curation bug: the `filter sweeping` entry told the LLM *"to sweep once over the range, set sweepfrq = infiledur/2"* — copied verbatim from CDP r8's own usage banner, which is dimensionally wrong (`infiledur/2` grows with file length; on a 7.2 s file it gives ~26 sweeps, not one). The agent caught the math and computed the correct value, but a less careful one would have shipped 26 sweeps.

That prompted an audit of every quantitative / formula claim across all five curated entries, verified empirically against the CDP r8 binary.

## Methodology

For each entry, read its `description`, `musical_use`, `duration_model`, and every parameter `description` for numeric or formula claims. Classify each by source (copied from CDP docs/banner vs. authored by us). Verify each empirically:
- **Duration formulas** — run real CDP via `process_impl` on a known-duration synthetic input, measure the output duration (`soundfile.info`), compare to the curated `duration_model` evaluated through the real preflight evaluator.
- **Sweep/direction claims** — run CDP and track the output's spectral centroid trajectory (`librosa`) to confirm direction and pass count.

The findings are pinned as CDP-gated regression tests in [tests/test_curation_formulas.py](../tests/test_curation_formulas.py).

## Test environment

- CDP version (`detect_cdp().version`): `r8`
- CDP install root: `cdpr8/_cdp/_cdprogs` (x86_64 under Rosetta on arm64 macOS)
- Host OS / arch: `Darwin 24.6.0 (arm64)`
- Python: `3.13.2`
- Repo commit SHA: `32ce5a1`

## Findings

| Entry | Claim | Source | Verdict |
| ----- | ----- | ------ | ------- |
| `filter sweeping` | sweepfrq `infiledur/2` for one sweep | CDP banner (copied) | **WRONG** → corrected to `1/(2·infiledur)` |
| `filter sweeping` | phase `0=rising, 0.5=falling` | CDP banner (copied) | ✓ correct — centroid: phase 0 rose 3844→6541 Hz; phase 0.5 fell 6343→3201 Hz |
| `filter sweeping` | acuity/gain `(1/3)^n / (2/3)^n` | CDP rule-of-thumb | advisory loudness-compensation heuristic, honestly labeled — **retained**, not falsifiable by a single run |
| `extend loop` | duration `cnt*len/1000` | ours (`duration_model`) | ✓ exact — cnt3×500ms → 1.500s; cnt5×200ms → 1.000s |
| `modify brassage` | duration `indur/velocity`; "0.5 doubles, 2.0 halves" | ours (`duration_model`) | ✓ correct — vel 0.5 → 3.934s, vel 2.0 → 1.010s (deltas are grain/splice overhead) |
| `morph morph` | static duration | ours | ✓ correct — two 2.0s inputs → 1.997s output |
| `blur blur` | — | — | no numeric/formula claims |

## Conclusion

Exactly one wrong formula across all five entries: `filter sweeping`'s `sweepfrq`. It was the only formula copied verbatim from a CDP usage banner *and* dimensionally wrong. Notably, the **other** claim copied from the same banner (phase direction) is correct — so the lesson is not "CDP docs are uniformly untrustworthy" but "verify any copied numeric formula against the binary; CDP's banners contain at least one known dimensional error."

Our own `duration_model` expressions (`extend loop`, `modify brassage`) and the `static` models (`blur`, `filter`, `morph`) all match CDP output. The `1/(2·infiledur)` correction is confirmed three ways: dimensional analysis, the original Claude Desktop spectrogram, and the centroid test now pinned in the regression suite.

### Action taken

- Corrected the `sweepfrq` description in [filter_sweeping.json](../src/cdp_mcp/knowledge/data/filter_sweeping.json) to `1/(2·infiledur)`, with concrete examples, a read-the-input-duration-first cue, and an explicit note that CDP's banner mis-states the formula.
- Added CDP-gated regression pins (duration-model consistency + filter sweep direction) so a future drift fails a test rather than reaching an LLM.
- Retained the acuity/gain heuristic as-is (advisory, correctly attributed to CDP docs).

## Caveats

- Single CDP build (r8). Re-verify if the install changes.
- Duration tolerances are relative (~5%) to absorb granular/splice/loop-boundary overhead in `modify brassage` and `extend loop`; the underlying formulas are exact in intent.
- The acuity/gain rule-of-thumb is a musical loudness heuristic, not a falsifiable formula — retained on trust, flagged here as unverified.
