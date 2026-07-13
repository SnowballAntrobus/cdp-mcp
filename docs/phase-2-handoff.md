# Phase 2 Handoff

> Companion to `docs/phase-1b-handoff.md` and `docs/phase-2-audit-2026-07-13.md`.
> Written 2026-07-13 at commit `817e477`. Suite: 622 passed, 14 skipped
> (real-CDP-gated), 1 deselected (slow), ruff clean — verified on Linux/py3.10
> AND the dev baseline was macOS/py3.13 (cross-platform per Task 2a).

## Shipped (this pass, commits d95d865..817e477)

**Hardening (post-audit, pre-orchestration):** subprocess lifecycle cleanup on
cancellation + process-group SIGKILL with strict pid validation (C1);
flag-attached path scope bypass closed (M1); event-loop offloads for
sha256/verify/disk-walks, capped `read_envelope`, blockwise RMS (M2); broad
audio-I/O exception guards → structured envelopes (M3); resolve_target
containment (M5); preflight TypeError family → structured (M11).

**Curation/doc truth:** `combine_cross` duration model → `expression:
"indur_min"` (evaluator injects pre-computed `indur_min`/`indur_max` — the
functions={} pattern); morph's dead `stagger:0` removed with rationale in
`known_issues`; `describe_workspace.history` implemented (design-committed);
Task 04/07 revert rationale recorded in the design doc (v9.1 note).

**DAG track:** `graph(dry_run=True)` (11a) — whole-DAG validation, bare-name
reference grammar, cycle detection, per-node duration predictions *chained
through the DAG* via `indur_overrides`. `graph()` full execution (11b) —
validates everything before spawning anything; one shared graph directory;
caller labels as node ids (auto-PVOC derives `<label>_pvocN`);
partial_success semantics; executes through the same
`execute_validated_node` path as `process()` (extracted, zero drift).
`batch()` (12) — validate-all-first short-circuit, independent element
execution, ONE atomic `recent_graphs` entry (`output_node: null`,
`batch_size: N`), `latest` untouched, `latest_batch[i]` in the reference
grammar.

**Observation track:** `segments()` (onset/novelty/silence + marked
spectrogram, both halves cached); `compare()` (lufs_i/lufs_m/peak loudness
matching to the quieter side, scorecard deltas, crest-factor warning, PIL
composite); `progression()` (ordered panels, 100 px/s, 8-panel cap + summary
panel); `analyze(verbose=True)` (MFCC/chroma stats, tempo, per-channel).

## Deliberate deviations from design doc v9 (all documented in-code)

- `analyze(verbose)` returns summary statistics, not per-frame matrices
  (context economy; see `extract_verbose` docstring).
- `batch()` auto-PVOC node ids are `n1_batch_i_pvoc1`, not the sketch's
  `n0_batch_i` (uniform derived-suffix scheme).
- `compare`/`progression` composites are uncached (rough end-to-end first).
- `lufs_m` is a 400 ms/100 ms-hop windowed approximation of momentary LUFS.
- `visualize` remains mel-only (`mode` param not added — no consumer asked;
  the cache key already carries a mode discriminator when it lands).

## Still deferred, with triggers

- **Task 04 revert (PVOC cache key window/overlap)**: re-land via
  `git revert c804a03` BEFORE exposing `_pvoc.*` engine controls.
- **Task 07 revert (`pad_with_fade`)**: re-land when a curated entry needs
  `_pvoc.length_strategy` (morph sidesteps via its own `-s` flag).
- **Task 8 (honoring `breakpoint_duration_source` input2/max/min)**: no
  consumer; resolver hardcodes input 1 (matches the only declared value).
- **Channel handling / stereo seed-linking**: Phase 3, with the first
  `phase_sensitive: true` curated entry.
- Audit moderates not yet fixed (all small): M6 session-config robustness,
  M7 atomic-write tmp-name collision (promote if batch/graph ever go
  concurrent — execution is sequential today), M8 detect_cdp 32-binary
  truncation, M10 pyplot-in-threads (single-call rendering is sequential;
  concurrent MCP clients rendering simultaneously is the risk), M12
  loader duplicate-key handling.

## Manual-test checklist (real CDP, your machine)

1. `pytest` — the 14 skips become real: curation formulas, breakpoint
   curation probes, combine-cross acceptance, Phase 1a acceptance.
   Also `pytest -m slow` for the keepalive stress test.
2. `graph(dry_run=True)` on a 3–4 node chain incl. one deliberate
   cap-buster — confirm the offending node is named with a sane prediction.
3. Same graph for real — check `history` in `describe_workspace`, node
   addressability (`<gid>:<label>`), `latest` after a partial failure
   (kill a node with a bad-but-validating param if you can find one).
4. `batch()` over 5+ speech snippets through `modify brassage` — confirm
   the single `recent_graphs` entry, `latest` preservation, and
   `latest_batch[2]` feeding a follow-up `process()`.
5. `segments(method="onset")` on `capm.wav`; feed a segment boundary into
   an `extend loop` start time.
6. `compare()` a brassage output against its source with default lufs_i;
   then a transient-heavy pair to see the crest warning.
7. `progression()` on the executed graph's id — panel order and labels.
8. Cancellation: start a long `process()`, hit stop in Claude Desktop,
   verify no orphaned CDP process (`ps | grep cdprogs`) — this is C1,
   only regression-tested with fakes.
