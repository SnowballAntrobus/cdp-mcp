# CDP-MCP: Phase 2 State + Code Audit — 2026-07-13

Audit of the full repo at HEAD (`d7776d5`, 2026-05-28) against design doc v9: source review
(~7,900 lines), git history, phase-2 docs, live-server probing, and a full test-suite run.

**Revision note:** an earlier draft of this audit (written before the repo root was available)
claimed the determinism sweep was missing and the test suite unverifiable. Both corrected below.

---

## 1. Where you left off

HEAD is `phase-2-task-09-combine-cross` (May 28), clean working tree. Phase 2 progressed
through numbered tasks; the plan doc itself is not in the repo (numbering reconstructed from
commits and code comments).

### Completed (per git history)
- **Task 01 — determinism sweep.** Done, then deliberately *removed* as a standing test in
  Task 6.7. Finding (via Task 2.5 flake forensics): all five Phase 1a entries are
  **sample-deterministic with header-only non-determinism** (CDP embeds a tick counter in
  output headers). Recorded in `docs/phase-2-determinism.md` with the explicit caveat that
  Phase 4 Task 12 must re-verify before relying on process-output cacheability. Sound call:
  the sweep guarded only a deferred, conditional feature while flaking ~2/10 in CI.
- **Task 02a/02b** — Linux test portability; `.ana` duration via `sfprops -d` (investigation
  corrected the design doc: `dirsf` was the wrong tool, `pvoc info` doesn't exist in r8).
- **Task 03 — `validate_node()` extraction** (`tools/node_validation.py`). Pure refactor;
  `process()` consumes it; `dry_run=True` stubbed for Task 11a.
- **Task 05 — `breakpoint_capable` curation review.** Empirically probed *per parameter*
  against real CDP r8 (methodology + environment in `docs/phase-2-breakpoint-review.md`),
  outcomes pinned as regression tests in `test_breakpoint_curation.py`. 7 of 23 params
  capable. A companion formula audit (`docs/phase-2-curation-audit.md`) caught and fixed a
  bug in CDP's own usage banner (`sweepfrq`: `infiledur/2` → `1/(2·infiledur)`), pinned in
  `test_curation_formulas.py`.
- **Task 06 — `breakpoint()` DSL** (live on the server), extended beyond spec with a
  `custom` pairs shape.
- **Task 09 — `combine cross`** curated entry + multi-input `process()` exercised
  (`test_combine_cross.py`, 180 lines incl. real-CDP acceptance cases).

### Implemented, then reverted (no written rationale — see §2.4)
- **Task 04 — PVOC cache-key extension** (window/overlap). Reverted `c804a03`.
- **Task 07 — `pad_with_fade` primitive** (`audio_align.py`, 124 lines + 236 test lines).
  Reverted `fb8fda6`.

Both reverts happened within 40 minutes on the final working day, immediately before
`combine cross` landed. The evident logic: `combine cross` needs no length alignment (CDP
natively truncates to the shorter input), so `pad_with_fade` had no consumer; and with
`_pvoc.window/overlap` exposure not landing this pass, the cache-key extension had no
consumer either. Consistent with the design doc's "rough end-to-end first" discipline.
Both are recoverable via `git revert` when their consumers arrive.

### Not started
- **Task 08** — honoring `breakpoint_duration_source: input2/max/min` (explicitly deferred
  in a `node_validation.py` comment: "no current consumer"; the resolver hardcodes input 1,
  which coincides with the only consumer's declared `input1`).
- **Task 11a** `graph(dry_run=True)`; **`graph()` full; `batch()`**.
- **Entire observation track**: `segments()`, `compare()`, `progression()`, verbose
  `analyze`, `visualize` modes beyond mel.
- Length-strategy engine wiring (`morph_morph`'s `"stagger:0"` is validated but unconsumed);
  `_seed` / `_stereo_link` (Phase 3 per doc — consistent).

### Test suite (verified by running it)
577 tests: **562 passed, 14 skipped, 1 deselected (slow), 25 s** — on Linux / Python 3.10
(dev was macOS / 3.13). Every skip is real-CDP-gated (correct behavior without CDP binaries
for this platform). Test:source ratio ≈ 9,400 : 7,900 lines. The Task 03 refactor's claim
that existing process-tool tests gate `validate_node` holds.

### Creative state
Sessions `speech_v0.5/0.6/0.7`; last activity 2026-05-28 (`speech_v0.7`: `capm.wav` +
`stereo_frogs.wav`, 5 graphs, 4 brassage velocity envelopes). The frog/IDM goal drifted
toward speech material.

---

## 2. Code quality verdict

**Substantially better than feared — including the process, not just the code.** Envelope
discipline is consistent, atomic writes and cache commitments are real, docstrings admit
their own compromises, curation claims were empirically verified against the binary and
pinned as regression tests, and dead-end work was reverted rather than left rotting. No file
needs a rewrite.

The real weaknesses cluster into themes that share one root: the codebase assumes **one
sequential tool call, never cancelled, one server process** — exactly the assumptions
`batch()`/`graph()` will break.

### 2.1 CRITICAL — fix before any Phase 2 orchestration work

**C1. `subprocess_core.py:168–250` — no `try/finally` around the subprocess lifecycle.**
On task cancellation (client stop/disconnect — routine in Claude Desktop) the CDP process
keeps running (timeout guarantee voided; output files appear later as surprises) and the
stdout/stderr/progress/watchdog tasks are orphaned — the progress task keeps firing on a
dead context. Fix: `finally` that kills the proc and cancels/awaits all four tasks.
Related: kill targets only the direct child (no process group), and post-kill stream awaits
have no timeout — a forking CDP binary could hang the call forever.

### 2.2 Moderate — real bugs, triage before/during Phase 2

- **M1 `security.py:255` — flag-attached path bypass.** `-e/Users/x/secret.wav` joins to
  session_root, resolves inside, passes — while CDP's flag parser strips `-e` and opens the
  absolute path outside the sandbox. Strip flag prefixes before the scope check.
- **M2 Event-loop blocking (breaks the project's own commitment):** sync `sha256_file` in
  `analyze.py:172`, `visualize.py:211`, throughout `pvoc.py`; `describe_workspace` `rglob`
  walks; `read_envelope` reads the whole file before truncating; `verify_output` decodes the
  entire wav to float64 + a flatten copy (~8 GB transient at cap) synchronously.
- **M3 Narrow exception handling around audio I/O:** `analyze`/`visualize` catch only
  `FileNotFoundError`/`ValueError`; `sf.LibsndfileError` (RuntimeError subclass), `EOFError`
  escape the envelope contract — including a path inside the visualize *cache-hit* branch.
- **M4 `combine_cross.json`:** `duration_model: static` contradicts its own `musical_use`
  ("output the duration of the shorter input") → wrong dry-run predictions for unequal
  inputs. Needs a `min(indur1, indur2)` expression model.
- **M5 `graph.py:366` `resolve_target` traversal-permissive** (graph_id `..`, node_index
  filenames, absolute paths accepted on existence). Safe today only via call-site
  discipline; `graph()` must not inherit this. Add containment in the resolver.
- **M6 `session.py`:** corrupt `config.json` → raw `ValidationError`; missing `config.json`
  with surviving siblings → `tags.json`/`journal.md` overwritten on next activation.
- **M7 `utils.atomic_write_text`:** deterministic `.tmp` name — two server processes sharing
  a sessions root can interleave and publish corrupt JSON. Random-suffix temp file.
- **M8 `config.py:68`:** canonical-binary check runs against a 32-entry truncated listing —
  a legit r8 install (hundreds of binaries) can fail detection. Check names directly.
- **M9 `describe_workspace` never got `history`/recent-graph summaries** the design doc
  claims shipped; `graph.py:276` docstring cross-references the nonexistent feature.
- **M10 `visualization.py` uses the pyplot state machine inside `asyncio.to_thread`** — not
  thread-safe under concurrent calls; switch to OOP `Figure`/`FigureCanvasAgg`.
- **M11 `duration_preflight.py:176`:** `TypeError` from simpleeval escapes the
  `DurationModelError` conversion — raw crash for exactly the curation-defect case the
  module exists to report cleanly.
- **M12 `knowledge/loader.py:34`:** duplicate (program,mode) keys — `_by_key` last-wins but
  `_by_category` keeps both. Raise or warn before Phase 3 curation scales.

### 2.3 Minor (selected)
Watchdog trusts pre-existing files at output_path and treats persistent stat failures as
transient forever; `os.access(X_OK)` passes directories as binaries; `execute()` doesn't
validate `timeout_seconds`; `output_exists` error text misleads on permission failures;
brassage `velocity` duration model ill-defined when velocity is itself a breakpoint (min 0.0
admits the degenerate value); `extend_loop` duration expr is an upper bound only;
`_make_graph_id` doesn't sanitize slug (`:` or `/` breaks the ref grammar);
`analysis_cache_key` treats `t_start=None` vs `0.0` as distinct entries; visualize builds
timestamps from two `datetime.now()` calls; `stagger:inf` passes schema validation;
pulse_train edge straddles can go non-monotonic at high count × low duty.

### 2.4 Process observations
- **The reverts of Tasks 04/07 have no recorded rationale** — not in commit messages, not in
  docs. The determinism-sweep removal (Task 6.7) shows the right pattern: decision + rationale
  + reactivation condition written into the doc it affects. The reverts deserve the same
  three lines somewhere (a future maintainer — or model — will otherwise re-litigate them).
- Design-doc drift: `visualize(mode=..., t_duration=...)` vs actual no-`mode`/`t_end`;
  `describe_workspace` `history` claimed but absent (M9); `dirsf` superseded by `sfprops -d`
  (code documents it; doc not updated); `schema.py:53` still claims breakpoint_capable is
  False everywhere.

---

## 3. Recommended order for finishing Phase 2

1. **Hardening pass (~1 day):** C1 (hard precondition for `batch()`), M1, M3, M11; offload
   M2's sync work through `run_with_progress`/`to_thread`; blockwise RMS for `verify_output`.
2. **Curation + doc fixes (small):** M4; decide `morph_morph`'s `stagger:0` fate; record the
   Task 04/07 revert rationale; fix stale docstrings (M9, schema.py:53); sync design doc.
3. **Task 11a `graph(dry_run=True)`** on `validate_node` — implement the dry-run branch (no
   side effects, per-node duration predictions). Add containment to `resolve_target` (M5)
   as part of this.
4. **`graph()` full execution** (topological order, bare intra-graph IDs vs `<graph>:nN`,
   lineage-hash cache lookups), then **`batch()`** (single graph dir, atomic recent_graphs
   event, `latest_batch[i]`). Decide explicitly whether batch elements run concurrently — if
   yes, M7 and `graph.add_node`'s read-modify-write get promoted to blockers.
5. **Observation track** (independent, can interleave): `segments()`, `compare()`,
   `progression()`, verbose `analyze`. Fix M10 before anything renders concurrently.
6. **When `_pvoc.*` exposure returns:** revert the Task 04 revert (`git revert c804a03`) to
   restore the cache-key extension *first* — the ordering constraint from design doc v9
   still applies. Likewise Task 07's `audio_align.py` is one revert away when a curated
   entry actually needs length alignment.

Determinism re-verification stays a Phase 4 Task 12 precondition per
`docs/phase-2-determinism.md` — nothing to do now.
