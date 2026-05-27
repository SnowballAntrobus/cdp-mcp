# Phase 1b Handoff

**Last commit:** `0138f17` (Task 13). All Phase 1b work is on `main`.

This document is the engineering record of Phase 1b: what shipped, what didn't, why, what to know before touching the code, and what Phase 2/3/4 should expect. It exists because the design doc captures *what was intended* and the commit history captures *what changed* — but the *why behind every non-obvious decision*, the *forensic findings from real CDP behavior*, and the *deliberate deferrals with their reactivation triggers* don't live anywhere else.

Audience: future maintainers (including future-you), Phase 2/3/4 contributors, and Claude conversations starting fresh.

---

## Contents

1. [Executive summary](#1-executive-summary)
2. [Phase 1b outcome: what shipped vs the original 15-task slate](#2-phase-1b-outcome)
3. [Repository map](#3-repository-map)
4. [Cross-cutting architecture](#4-cross-cutting-architecture)
5. [Forensic discoveries (institutional knowledge)](#5-forensic-discoveries)
6. [Deferred work and reactivation triggers](#6-deferred-work)
7. [Development and operations guide](#7-development-and-operations-guide)
8. [Phase 2 / 3 / 4 implications](#8-phase-2--3--4-implications)
9. [Known limitations and open questions](#9-known-limitations-and-open-questions)

---

## 1. Executive summary

**Phase 1b shipped 11 tasks of an originally-planned 15.** Two tasks were dropped during planning (Task 9, Task 12) for sound engineering reasons; two more were deferred at phase closeout (Task 14, Task 15) on the same "no consumer in Phase 1b" rationale that retired Task 12. The codebase is in a clean, production-quality state on the same nine-tool surface that Phase 1a shipped.

**Headline numbers:**

| Metric | Phase 1a end | Phase 1b end | Delta |
|---|---|---|---|
| Tests passing | ~260 | 466 (default) + 1 (slow stress) | +207 |
| Default `pytest` runtime | seconds | seconds (slow tests deselected) | — |
| `ruff check` | clean | clean | — |
| Production code (`src/cdp_mcp/`) | ~3700 lines | 6121 lines | +2400 |
| Test code (`tests/`) | ~3300 lines | 7905 lines | +4600 |
| Curated knowledge entries | 5 | 5 (same set, one entry's `duration_model` corrected) | — |
| Commits on main | 8 (Phase 1a) | 19 (Phase 1a + 1b) | +11 |

**What's production-quality now that wasn't before:**

- **Reliability**: pre-flight duration check + reactive disk watchdog cover both curation-correct and curation-wrong failure modes
- **Performance**: derivative caches (PVOC, analysis, visualizations, audition) give 15× to 1231× speedups on repeat operations
- **Observability**: structured error taxonomy with action-oriented `fix` text; `recent_graphs` deque with `prev_N` aliases; CDP version mismatch warning on session reload
- **Safety**: defensive breakpoint compilation; expression evaluator sandboxed; env-var-configurable resource caps; MCP keepalive regression-gated
- **Test infrastructure**: real-CDP acceptance suite, fake-CDP fault-injection (refuse-clobber, die-on-dot-path, silent-output), Apple Silicon arch wrapping autouse-fixtured, slow-test marker for opt-in long runs

**What's NOT production-quality** (intentional Phase 1b non-goals, not gaps to fix):

- The tool *surface* is unchanged. Same 9 tools as Phase 1a. Phase 2 adds `graph()`, `batch()`, `segments()`, `compare()`, `progression()`, `breakpoint()`.
- The *knowledge layer* is unchanged in scope. Same 5 curated entries. Phase 3 expands to ~30, then ~100.
- *Cross-session intelligence* is intentionally absent. PVOC/analysis/viz/audition caches cross sessions; process outputs deliberately do not (compositional vs derivative distinction — see §4).

---

## 2. Phase 1b outcome

### What shipped (11 tasks)

| # | Commit | Description | Net new tests |
|---|---|---|---|
| 1 | `0971415` | `flag_kind` required on `ParameterSpec` + the 5 existing entries updated. Pydantic catches curator omission at validation time. | +8 |
| 2 | `253dae7` + `81677d7` | Test-double upgrades (`--cdp-refuse-clobber`, `--cdp-die-on-dot-path`, `--cdp-silent-output`) + Apple Silicon arch-wrapping autouse fixture. | +1 |
| 3 | `f9ee26c` | `recent_graphs` deque (maxlen=5) + `prev_1`..`prev_4` aliases. Per-process, not persisted. | +21 |
| 4 | `036be56` | CDP version detection (path-component regex fallback) + mismatch warning on `set_session()`. **Empirically uncovered that stock CDP r8 has no `cdp` binary** — every prior session was recording `cdp_version: "unknown"`. | +19 |
| 5 | `85257a1` | Stderr pattern parsing (4 patterns: `output_exists`, `channel_mismatch`, `usage_banner_returned`, `silent_output`). **Empirically refined to search stdout + stderr** because real CDP r8 emits errors to stdout. | +33 |
| 6 | `39cb634` | Pre-flight `duration_model` evaluation in `process()` via `simpleeval`. Three structured failure modes. Migrated `extend loop`'s `duration_model` from mis-specified linear to expression. | +27 |
| 7 | `7fd8506` | Disk watchdog + env-var-configurable resource caps (`CDP_MCP_OUTPUT_SIZE_CAP_BYTES`, `CDP_MCP_DURATION_CAP_S`). | +15 |
| 8 | `d6f26b1` + `a835d3c` | Polymorphic parameters (constant / relative-time tuples / absolute-time tuples / pre-existing `.brk` paths). Defensive breakpoint compilation (sort, dedupe, auto-append). `source_wav_duration_s` recorded on auto-PVOC nodes. New `read_envelope` tool. | +39 |
| 10 | `f121bb1` | Derivative caches: PVOC, analysis, visualizations under `~/.cdp_mcp/cache/`. Per-tier lib-version composition. Hardlink-on-POSIX materialization. **Speedups**: PVOC 15×, viz 120×, analyze 1231×. | +36 |
| 11 | `51f4901` | Audition synth cache (`.ana → .wav`). Unlocks param-variation speedup: `visualize(t_start=0)` then `visualize(t_start=5)` reuses the audition wav. **7.5× speedup on the param-variation case**, cross-tool sharing verified by monkeypatch on `run_cdp_command`. | +9 |
| 13 | `0138f17` | MCP timeout stress test (`@pytest.mark.slow`). 80s subprocess sleep exercises the clock-driven keepalive across Claude Desktop's ~60s boundary. Substituted `fake_subprocess` for real CDP because real PVOC scales nonlinearly — 10 min mono analyzes in ~5s on M-series, would have needed multi-hour audio. | +1 (slow) |

**Total: 466 tests + 1 slow-marked stress test. Default `pytest` collects 466 passing, 1 skipped (when `CDP_PATH` unset).** `pytest -m slow` adds the keepalive test (~100s wall clock).

### What got dropped or deferred (4 tasks)

| # | Disposition | Why |
|---|---|---|
| 9 | **Dropped** | "15-recent + auto-pinning" for `available_sources`. In branching exploration each step has a different input, so the auto-pin heuristic ("referenced by a later graph") would match nearly every node — heuristic provides no useful filtering signal. Phase 4's explicit `tag()` is the proper solution for "I care about this." Current 5-slot tracker covers conversational continuity; describe_workspace's `history` field covers session-wide recall. If 5 slots turns out tight in practice, `maxlen=10` is a one-line change. |
| 12 | **Deferred** | "Process-output cache" (session-local, compositional). Cache key requires same `(program, mode, submode, input_hashes, params, cdp_version)` — but the dominant exploration workflow is "vary one thing at a time," so hits would be rare (~5-15%). Task 10's PVOC cache already covers the slow path; the marginal benefit (replace "fast main op" with "instant hardlink") doesn't justify the complexity (step reordering in process.py, ~30 tests, two new lineage fields). Phase 4's `tag()` + `history` address the "I lost a graph" use case more directly. |
| 14 | **Deferred** | "Dependency index for `cleanup()`". Maintains `session/dependency_index.json` on every successful `process()` with cross-graph references, but the only consumer is `cleanup()` — a Phase 4 tool that doesn't exist yet. Bookkeeping cost on every call with no user-facing benefit in Phase 1b. Phase 4 will build it alongside its consumer with full context. |
| 15 | **Deferred** | "`pad_with_fade` time-domain padding primitive". Designed for multi-input PVOC alignment, but the wiring into morph/cross/combine/convolve paths is explicitly Phase-2-opportunistic per the design doc. Primitive without consumer in Phase 1b. Phase 2 builds it when adopting one of those operations. |

**The pattern these four share** is "infrastructure for a future task with no consumer in Phase 1b." All four are real engineering — schema migration, atomic-write contracts, ~30+ tests — that would land cleanly today but produce zero observable behavior until their consumer arrives. The decision in each case was: defer until the consumer ships, build alongside it with full context, save the schema-migration overhead.

---

## 3. Repository map

```
src/cdp_mcp/
├── __init__.py
├── __main__.py                Entry: `cdp-mcp` console script
├── server.py             149  FastMCP server. Wires tools, sessions, latest_tracker, cdp_config, cache_root.
├── schema.py             310  Pydantic models. ParameterSpec, KnowledgeEntry, NodeLineage, ResultEnvelope, etc.
├── session.py            295  SessionManager + Session + cdp_version_mismatch_warning. Filesystem layout.
├── config.py             138  detect_cdp() + _detect_version() (probe + path-component regex fallback).
├── security.py           277  3-check security gate: binary location, shell metachars, path scope.
├── knowledge/
│   ├── __init__.py
│   ├── loader.py              Loads JSON entries → KnowledgeEntry Pydantic models at import time.
│   └── data/                  5 curated entries: blur_blur, modify_brassage, morph_morph, extend_loop, filter_sweeping.
├── subprocess_core.py    325  run_cdp_command. asyncio subprocess with clock-driven progress emitter and disk watchdog.
├── processing.py         307  validate_params, build_cdp_argv, _check_type, _format_value, _argv_path (cwd-relative).
├── pvoc.py               416  maybe_insert_pvoc + synth_for_audition. Auto-inserts pvoc anal/synth nodes. PVOC + audition caches.
├── error_parsing.py      176  parse_cdp_errors. 4 patterns matching combined stderr + stdout.
├── duration_preflight.py 242  check_duration_preflight via simpleeval. Static / set_by / linear / expression kinds.
├── breakpoint_compiler.py 464 Polymorphic param compilation: relative/absolute tuples → .brk content-addressable files.
├── limits.py              59  OUTPUT_DURATION_CAP_S, OUTPUT_FILE_SIZE_CAP_BYTES. Env-var-overridable.
├── graph.py              517  GraphDir, LatestTracker (deque maxlen=5 + prev_N aliases), resolve_target, verify_output, build_context_block.
├── analysis.py           124  extract_scorecard (librosa MIR features).
├── visualization.py      174  render_spectrogram (matplotlib Agg, programmatically forced).
├── progress.py            99  run_with_progress: sync work in async tools via asyncio.to_thread + ctx.report_progress.
├── utils.py               41  sha256_file + small helpers.
└── tools/
    ├── __init__.py
    ├── introspection.py   83  list_categories, list_programs, get_program_info.
    ├── workspace.py      248  set_session, describe_workspace, read_envelope (Task 8 addition).
    ├── execute.py        230  Raw CDP escape hatch under the security gate.
    ├── process.py        750  Curated CDP invocation. Validates → preflight → graph dir → auto-PVOC → breakpoint → subprocess → verify → lineage.
    ├── visualize.py      372  Renders spectrograms; auto-synths .ana inputs via audition cache.
    └── analyze.py        314  Extracts MIR scorecard; auto-synths .ana inputs via audition cache.

tests/
├── conftest.py                Session-scoped autouse fixtures: isolate sessions_root, disable arch-wrap.
├── fixtures/
│   └── fake_subprocess.py     Fault-injection fake CDP. --cdp-refuse-clobber, --cdp-die-on-dot-path, --cdp-silent-output, --cdp-grow-file, --sleep, --stderr-lines, --write-wav, --write-ana.
├── test_*.py             27 test files
└── test_stress.py             @pytest.mark.slow keepalive verification (deselected by default).

Cache layout at runtime
~/.cdp_mcp/cache/
├── pvoc/                      .ana files keyed by sha256(audio_bytes + argv + cdp_version)
├── analysis/                  scorecard JSON keyed by sha256(audio_bytes + feature_set + lib_versions)
├── visualizations/            PNGs keyed by sha256(audio_bytes + mode + render_params + lib_versions)
└── audition/                  .ana → .wav synthesized for visualize/analyze, keyed by sha256(ana_bytes + cdp_version)

Session layout at runtime
~/cdp_sessions/<name>/
├── config.json                CDP version recorded at creation
├── inputs/                    User-supplied audio
├── graphs/<timestamp-name>/   One per process() call
│   ├── graph.json             User intent
│   ├── node_index.json        Atomic write
│   ├── lineage.json           Atomic write — argv, inputs+hashes, output_path+hash, params, cdp_version, source_wav_duration_s, compiled_breakpoints, timings
│   └── n1_*.{wav,ana}         Process output(s)
├── envelopes/                 Compiled .brk files (content-hashed names)
├── tmp/                       Transient intermediates (audition cache misses write here before populate)
└── visualizations/            PNG outputs (independent of global viz cache)
```

**Atomic-write contract**, used by `node_index.json`, `lineage.json`, and the breakpoint compiler: write to `<path>.tmp`, then `os.replace(<path>.tmp, <path>)`. POSIX `replace` is atomic at the filesystem layer; concurrent writers producing identical content can't corrupt each other.

---

## 4. Cross-cutting architecture

### 4.1 The two-tier cache (the design's central concept)

**Derivative artifacts go global**, in `~/.cdp_mcp/cache/`. PVOC `.ana` files, MIR features, spectrograms, audition synths. These are *pure functions* of `(input_bytes, parameters, software_versions)`. Identical regardless of which session triggered them. Cross-session deduplication. Per-tier lib version composition: PVOC cache keys depend on `cdp_version` only; analysis caches mix in `librosa/numpy/scipy/pyloudnorm` versions; visualizations mix in `librosa/numpy/matplotlib`. A library bump invalidates only the tiers that depend on it.

**Compositional artifacts stay session-local**, in `<session>/graphs/`. Process outputs (`n1_*.wav`, `n2_*.ana`). These are *intentional creative products* tied to the graph and session that produced them: the chosen inputs, the parameter intent, the tag context (Phase 4+), the lineage to the upstream nodes. Deleting a session should delete its outputs. **In Phase 1b, process outputs are NOT cached** — Task 12 was deferred. They live entirely in their graph directory with no cross-session reuse.

**Cache write failures are non-fatal.** Every `cache_populate` call wraps the disk write in try/except. On failure, a stderr warning fires and the operation proceeds. This is enforced by `tests/test_cache.py::test_cache_populate_failure_returns_false_with_warning` — a real `chmod 0555` test on a real cache dir.

**Materialization helper for cache hits that need a graph-dir file**: `materialize_cached_artifact(src, dst)` in `cache.py`. Tries `os.link()` (POSIX hardlink, zero disk cost) first, falls back to `shutil.copy2` (preserves mtime — matters if Phase 4 cleanup adds age-based eviction). Verified on macOS by `st_ino` equality in Tasks 10 and 11.

### 4.2 Sessions, graphs, and the per-call mini-graph model

Each `process()` call creates a new graph directory: `<session>/graphs/<timestamp>-<program>-<mode>/`. The directory contains:

- `graph.json` — user intent, opt-in
- `node_index.json` — registry of nodes added (e.g., `n1`, `n2`) with their output filenames; atomic-write
- `lineage.json` — full provenance dict (atomic-write): argv (post arch-wrapping), inputs with sha256, output_path with sha256, params, cdp_version, started_at, finished_at, duration_ms, exit_code, `source_wav_duration_s` for auto-PVOC nodes, `compiled_breakpoints` for breakpoint params
- `n1_*.{wav,ana}`, `n2_*.{wav,ana}` — the actual audio nodes

**Cross-graph references** work via `<graph_id>:nN` syntax. The resolver (`graph.resolve_target`) takes a string and produces an absolute Path. Aliases `latest`, `prev_1`, `prev_2`, `prev_3`, `prev_4` route through the `LatestTracker` deque (Phase 1b Task 3). The tracker is **per-process** — never persisted, reset on server restart.

**`recent_graphs` durability rules** (locked, document in code):
- Pruned by `cleanup()` (when it exists, Phase 4) — entries don't shift forward on removal; `prev_2` stays meaning what it meant
- Slot-aged off by the 5-entry cap (when a 6th is added, the oldest drops)
- Failures don't update the tracker (`latest` always points at the most recent *successful* output)

**`build_context_block`** (in `graph.py`) returns the `ContextBlock` attached to every tool envelope. It contains `active_graph`, `latest`, `recent_graphs`, and `available_sources`. Three lists with three distinct purposes:
- `recent_graphs` — live conversational subset (5 entries, with `latest`/`prev_N` aliases)
- `available_sources` — working set (recent + inputs, deduplicated)
- `history` — complete session record (built from filesystem at `describe_workspace` time)

### 4.3 The PVOC lifecycle (auto-insertion)

CDP's phase-vocoder pipeline has been the engine's most error-prone area. Phase 1a shipped auto-insertion in single-input chains; Phase 1b layered caching on top.

When `process()` gets a spectral op on a `.wav` input, `maybe_insert_pvoc` adds a `pvoc anal` node upstream (e.g., `n1_pvoc-anal.ana`), then runs the main op as `n2_*`. The auto-inserted node is first-class addressable — `visualize("<graph_id>:n1_pvoc-anal")` resolves correctly by auto-synthing back to `.wav` via the audition cache.

The reverse direction works too: a time-domain op on `.ana` input gets `pvoc synth` upstream.

**Two caching layers stack here:**
1. **PVOC cache** (Task 10, `~/.cdp_mcp/cache/pvoc/<sha>.ana`): a single `pvoc anal` invocation's output is cached globally and hardlinked into any future graph dir that needs an analysis of the same wav under the same CDP version.
2. **Audition cache** (Task 11, `~/.cdp_mcp/cache/audition/<sha>.wav`): the `.ana → .wav` synth needed by `visualize()` and `analyze()` for spectral targets is cached globally, keyed by `sha256(ana_bytes + cdp_version)`.

The audition cache enables a workflow Task 10 alone couldn't speed up: `visualize(target=ana, t_start=0)` then `visualize(target=ana, t_start=5)`. Both calls miss the visualization cache (different `t_start`), but the second hits the audition cache → skips `pvoc synth` → ~7.5× speedup.

**Pre-delete contract** (shipped Phase 1a, still load-bearing): CDP r8's `pvoc synth` refuses to overwrite existing output files and exits 255. The engine unconditionally `unlink(missing_ok=True)`s any output path before invoking CDP in a re-invocation path. The `output_exists` stderr pattern (Task 5) is the structured detection of this when it does fire.

### 4.4 Subprocess core: keepalive + watchdog

`subprocess_core.run_cdp_command` is the single chokepoint for every CDP invocation. It does three things in parallel:

1. **stdout drain** (`asyncio` task)
2. **stderr drain** (`asyncio` task, also feeds `state["latest_stderr_line"]` for progress messages)
3. **progress emitter** — calls `ctx.report_progress(progress=tick, total=None, message=latest_stderr_line)` every 5 seconds. **Clock-driven**, not CDP-driven (`asyncio.sleep` is what determines firing cadence). Without these, Claude Desktop closes the connection at ~60s.

When `output_path` and `size_cap_bytes` are both provided, a **fourth task** spawns: `_disk_watchdog`, polling `os.path.getsize(output_path)` every second. If the file crosses `size_cap_bytes`, the watchdog SIGKILLs the subprocess and the post-wait cleanup unlinks the partial output. `SubprocessResult.size_cap_exceeded` is set to True; `triggered_at_bytes` records the size at kill time.

**Error precedence** in `process.py` and `pvoc.py`: `size_cap_exceeded` outranks `timed_out` outranks `subprocess_error`. The SIGKILL-induced negative exit code doesn't double-report — the size cap breach is the real cause.

**PVOC-specific watchdog message** in `pvoc.py`: when the cap fires on a PVOC step, the error includes "PVOC artifacts can be 10-20× the source wav size — long stereo inputs are the usual cause." Action-oriented context, not generic.

The stress test (Task 13) regression-gates the keepalive: 80s sleep + ≥5 progress calls in the `[60s, 180s]` window. Lower bound proves the test actually exercised the mechanism; upper bound catches silent latency regression.

### 4.5 Knowledge layer and the schema

`src/cdp_mcp/knowledge/data/*.json` files are loaded at import time by `knowledge/loader.py` into Pydantic `KnowledgeEntry` models. **Schema validation is strict** — Pydantic catches curator omissions (e.g., a missing `flag_kind` field would fail to load and the server would crash at startup). This is the right tradeoff: silent default values for curator omissions would let drift accumulate.

**`flag_kind` was made required** in Task 1 (no default). Two values: `"attached_value"` (e.g., `-s0.5`) and `"no_value"` (e.g., `-b`). Phase 1a's 5 entries were updated in the same commit.

**`duration_model` is a discriminated union** of four kinds:
- `static`: `outdur = max(known_indurs)`, or `None` (skip) if all unknown
- `set_by`: `outdur = float(params[param])`
- `linear`: **same as set_by in Phase 1b** — the schema doesn't yet encode a multiplier. Kind tag preserved for future schema work
- `expression`: `simpleeval(expr)` over `{indur, indur1, ..., **params}`. Single-input convenience: `indur` is the lone input duration

`extend_loop`'s `duration_model` was migrated from `{kind: linear, param: cnt}` (under-predicts: says `outdur = cnt` seconds when it's actually `cnt * len / 1000`) to `{kind: expression, expr: "cnt * len / 1000"}` as part of Task 6.

**`simpleeval` is configured with `functions={}`** — no `math.sqrt`, no `int()`, no attribute access. The threat surface is curator-authored JSON, not user input, so the safety story is defense in depth.

**Polymorphic parameters** (Task 8): a param value can be a scalar, a list of `(time, value)` tuples with relative time `0.0-1.0`, a list with `"abs:"` prefix for absolute seconds, or a path to an existing `.brk` file. The compiler sorts, dedupes near-identical timestamps (`1e-6` threshold), auto-appends a final point, and writes a content-hashed `.brk` to `session.envelopes_dir`. The compiled `.brk`'s content sha is what makes the cache key correctly sensitive to input duration changes — *not the raw tuple*. (Comment in source documents this; load-bearing for cache correctness.)

### 4.6 Error envelope contract

Every action tool returns a `ResultEnvelope`:

```json
{
  "status": "ok" | "failed" | "partial_success",
  "output": "<path or null>",
  "stdout": "...",
  "stderr": "...",
  "exit_code": 0,
  "errors": [
    {"type": "channel_mismatch", "message": "...", "fix": "..."}
  ],
  "warnings": [...],
  "cached": false,
  "duration_ms": 1240,
  "context": { /* ContextBlock */ }
}
```

**Structured error types** added in Phase 1b:
- `predicted_duration_evaluation_failed`, `predicted_duration_negative`, `predicted_duration_exceeds_cap` (Task 6)
- `size_cap_exceeded` (Task 7)
- `output_exists`, `channel_mismatch`, `usage_banner_returned`, `silent_output` (Task 5)
- `param_breakpoint_*` family for breakpoint validation failures (Task 8)

**Additive composition**: stderr pattern parsing adds *specific* entries alongside the existing *generic* ones (`subprocess_error`, `output_verification_failed`). For example, `silent_output` coexists with `output_verification_failed` — the specific entry's `fix` field gives the LLM the actionable hint; the generic entry remains as residual confirmation. No deduplication in Phase 1b. If this turns out noisy in practice, dedup is a small follow-up.

**Action-oriented `fix` wording**: every structured error includes `fix` text that names a specific remedy ("Reduce the parameter values that drive duration", "Run housekeep stereo or housekeep mono upstream", "Consider regenerating outputs you intend to use further"). The Task 3 manual-verification observation that LLMs translate action-oriented wording into action more reliably than vague caveats has held across all subsequent tasks.

### 4.7 Security gate (three checks, all collected)

`src/cdp_mcp/security.py:validate_command` runs three independent checks and collects all violations into one envelope:

1. **Binary location** — `argv[0]` must be a bare CDP program name or absolute path inside `$CDP_PATH`. Symlinks resolved before checking.
2. **Shell metacharacter denylist** — any element of `command[1:]` containing `;|&$\`><()\n\r\0` is rejected. CDP's argv-style invocation means shell-injection is impossible at the subprocess layer (`shell=False`); this denylist is defense-in-depth.
3. **Path scope** — any element of `command[1:]` with an audio/spectral/envelope/data extension must resolve inside the session tree or the CDP cache.

The cwd-relative argv path trick (Task 2 / Phase 1a forensic finding — see §5) interacts with check #3: paths inside the session tree get rendered as `n1_op.wav` (relative); paths outside (cache directories) stay absolute. The security gate resolves both forms against `session.root` before checking.

### 4.8 Apple Silicon arch wrapping

CDP r8 binaries are x86-only. `subprocess_core` auto-wraps subprocesses with `arch -x86_64` on arm64 Darwin, controlled by env var `CDP_MCP_DISABLE_ARCH_X86_64`. Test infrastructure uses a session-scoped autouse fixture in `conftest.py` (`_disable_apple_silicon_arch_wrapping`) to disable wrapping for the test suite — the venv's Python interpreter that exec-runs `fake_subprocess.py` isn't a fat binary, so wrapping it would fail with "Bad CPU type in executable."

A handful of `test_subprocess_core.py` tests that exercise the arch-detection logic itself use `monkeypatch.delenv` to remove the env var for their scope.

### 4.9 Test infrastructure

- **`tests/fixtures/fake_subprocess.py`** is the workhorse. Executable Python script that simulates CDP behavior: writes wav/ana files, emits stderr lines, sleeps, exits cleanly or fails specific ways. Flags are named `--cdp-<simulated-behavior>` for self-documentation: `--cdp-refuse-clobber`, `--cdp-die-on-dot-path` (uses SIGTERM not SIGILL — see §5.2), `--cdp-silent-output`, `--cdp-grow-file`.
- **`tests/conftest.py`** has two session-scoped autouse fixtures: `_isolated_sessions_root` (redirects `CDP_MCP_SESSIONS_ROOT` to `tmp_path` so test runs never touch the developer's real session dir) and `_disable_apple_silicon_arch_wrapping`.
- **Acceptance test** (`tests/test_acceptance.py`) exercises the full frog chain end-to-end against real CDP under the deliberately-dotted session name `frog_acceptance_v1.0` (locks in the brassage path-mangling regression).
- **Stress test** (`tests/test_stress.py`, `@pytest.mark.slow`) — opt-in long test (`pytest -m slow tests/test_stress.py`). 80s subprocess sleep, ≥5 progress calls, duration in `[60s, 180s]`.

---

## 5. Forensic discoveries (institutional knowledge)

These are findings made through real implementation work that would otherwise be lost. They're indexed so they can be cited by source file when relevant. Each one represents hours of investigation that a future contributor shouldn't have to repeat.

### 5.1 CDP-specific behavior

**5.1.1 — Stock CDP r8 has no `cdp` binary.** The closest binary names are `cdparams`, `cdparse`, etc. Before Task 4, every production session recorded `cdp_version: "unknown"` because `_detect_version()` looked for `cdp --version`. Phase 1b's fix: probe primary, fall back to walking `cdp_path.parts` in reverse for a `cdp[_-]?r?\d+(\.[\w.]+)?` pattern match. Most installs match `cdpr8` directly → version becomes `"r8"`. Documented in `config.py`.

**5.1.2 — CDP r8 emits error-class messages to STDOUT, not stderr.** Verified empirically with `pvoc synth` refuse-to-clobber and `sndinfo chandiff` channel mismatch. The error parser (Task 5) searches `combined = stderr + "\n" + stdout` for the two patterns that benefit. Documented in `error_parsing.py`.

**5.1.3 — Real CDP error phrasings (Task 5 refinement):**
- Refuse-clobber: `"Cannot open output file ..."` (uses "open" not "create" — the broader regex matches both)
- Channel mismatch: `"Process only works with STEREO files."` or `"Process only works with MONO files."`
- "Application doesn't work with this type of infile" was considered as a `channel_mismatch` pattern and **rejected as too generic** — it could mean wrong sample rate, wrong format, wrong encoding, anything. A misleading `fix` hint is worse than no specific entry.

**5.1.4 — `pvoc anal` and `pvoc synth` are byte-deterministic** for the same input + CDP version. Verified empirically by hashing outputs across multiple runs in Tasks 10 and 11. The entire derivative cache premise rests on this; both directions confirmed. SHA of test PVOC anal output: `e4e6954…`. SHA of test PVOC synth output: `26fb3dba…`.

**5.1.5 — Real PVOC scales nonlinearly with input duration.** Empirically on Apple Silicon M-series, 10 minutes of mono 44.1 kHz wav analyzes in ~5 seconds. The naive linear extrapolation from "37ms for a few-second wav" gives multi-hour estimates for 60+ seconds of PVOC work, which is wrong by orders of magnitude. There must be substantial per-call overhead that dominates at small sizes, then very efficient streaming behavior at larger sizes. **Don't extrapolate PVOC timings linearly.** (Forced the Task 13 plan substitution from real CDP to `fake_subprocess`.)

**5.1.6 — `modify brassage` SIGILLs (silently, no stderr) on absolute paths whose ancestry contains a `.`** Root cause is brassage's `_cdptemp1` sibling-derivation logic. Phase 1a workaround: cwd-relative argv paths for in-session writes; absolute for cache reads outside the session tree. The acceptance test uses session name `frog_acceptance_v1.0` to lock the regression. Documented in `processing.py:_argv_path` and `tests/test_acceptance.py`.

**5.1.7 — PVOC `.ana` files are 10-20× the source WAV size.** Window-dependent. Surfaced when the 1 GB output cap kept firing on long-input PVOC steps. Watchdog message in `pvoc.py` mentions this. Phase 3 should grow per-program `pvoc_analysis_expansion_factor` hints.

**5.1.8 — CDP binaries are inconsistent about exit codes when printing the usage banner.** Some exit 0, others 1, 2, or 255. The right invariant is *behavioral*: "expected output missing AND 'Usage:' in stderr OR stdout", regardless of exit code. Documented in `error_parsing.py` for `_USAGE_BANNER_RE`.

**5.1.9 — `extend loop` may be silent during execution.** The design doc flagged this as an open question for stress-testing the keepalive. Task 13 sidestepped by using `fake_subprocess --sleep 80 --stderr-lines 20` instead — the keepalive is clock-driven, not stderr-driven, so the empirical question is moot for that test's purpose.

### 5.2 macOS-specific behavior

**5.2.1 — macOS's ReportCrash routes SIGILL/SIGABRT/SIGSEGV/SIGBUS/SIGFPE/SIGTRAP through a crash dialog.** Test fakes simulating CDP crashes should use **SIGTERM** (or SIGKILL/SIGINT/SIGHUP) to avoid triggering the dialog during every test run. Task 2's `--cdp-die-on-dot-path` was originally `--cdp-sigill-on-dot-path` and used SIGILL; the rename and signal change preserve the test's purpose (production only checks `exit_code != 0`, doesn't care about the specific signal) while avoiding ReportCrash noise. Documented in `_trigger_signal_death` docstring.

**5.2.2 — macOS `/var → /private/var` symlink.** When test fixtures put cache directories under `tmp_path` (which resolves to `/var/folders/...` on macOS but `/private/var/folders/...` after `Path.resolve()`), the security gate's path-scope check fails because it compares resolved vs unresolved paths. Fix: `Path.resolve()` on the cache root before constructing the SessionManager in tests. Surfaced in the Task 10 verification driver and documented there.

### 5.3 Python / packaging behavior

**5.3.1 — `pip install -e ".[dev]"` may install into a different Python's site-packages.** Task 6's verification surfaced this: the venv's active Python was 3.11, but `pip install -e ...` installed into `python3.13/site-packages` (system-wide). The fix is `python -m pip install ...` which binds the install to the active interpreter. Worth flagging if you ever see "module not found" errors after a fresh install in a multi-Python-version environment.

**5.3.2 — `monkeypatch.setattr("module.X", ...)` doesn't catch from-imports.** If you do `from module import X` in caller code, you have to patch `caller_module.X`, not `module.X`. This bit Task 7 when patching `OUTPUT_FILE_SIZE_CAP_BYTES`: must patch BOTH `cdp_mcp.limits.OUTPUT_FILE_SIZE_CAP_BYTES` AND `cdp_mcp.tools.process.OUTPUT_FILE_SIZE_CAP_BYTES` because process.py from-imports.

**5.3.3 — `importlib.reload(module)` is required to test env-var rebinding.** Module-level constants computed at import (like `OUTPUT_DURATION_CAP_S = _resolve_positive_float(...)`) are frozen at first import. A test like "set env var, expect new constant value" needs `importlib.reload(limits)` after `monkeypatch.setenv`. The Task 7 test `test_env_var_override_round_trip` does this. Without that, future "lazy import" optimizations could silently break env-var overrides without test coverage.

**5.3.4 — `matplotlib.use("Agg")` must be called programmatically at server entry, before any pyplot import.** The `MPLBACKEND=Agg` environment variable is unreliable across launch wrappers (`uvx`, `npx`, IDE-spawned servers may drop or override it). A GUI backend on a headless server hangs `visualize()` indefinitely on first call. `server.py` does this at module top. Documented in `visualization.py` and the design doc.

**5.3.5 — `audioread` deprecation in Python 3.14.** `audioread` (transitive via librosa) deprecates `aifc` and `sunau` in 3.14. Mitigation: rely on `soundfile` exclusively (already in deps; librosa prefers it when available). `LIBROSA_AUDIO_BACKEND=soundfile` env var available in librosa 0.10+ for explicit selection. No `audioread=False` parameter on `librosa.load()` — that was a v6 mis-attribution in the design doc.

### 5.4 Test infrastructure findings

**5.4.1 — Test fakes should fail in the same ways production fails.** Phase 1a's `fake_subprocess.py` initially overwrote outputs unconditionally; production was broken on the same path (`pvoc synth` refuses-clobber). Task 2 added `--cdp-refuse-clobber` etc. Naming convention: `--cdp-<simulated-behavior>` (observable behavior, not implementation detail).

**5.4.2 — Phantom session in cache dir.** `list_sessions()` returns every subdir of `sessions_root`. If tests put a cache directory under `tmp_path` that gets used as a sessions_root, the cache appears as a "session." Fix: use `tmp_path_factory.mktemp("cache")` outside the sessions root, or `tmp_path / "cache"` (separate dir). Pattern documented in `tests/test_workspace.py`.

**5.4.3 — `monkeypatch.setattr` on `run_cdp_command` directly is the right way to prove "subprocess didn't run."** Timing-based "second call was faster" leaves room for filesystem cache, GC, etc. Patching the entry point and asserting it wasn't entered is direct empirical proof. Used in Task 11 for the cross-tool audition cache verification ("analyze hits viz-populated audition cache without subprocess").

**5.4.4 — `pytest-timeout` as belt-and-suspenders.** Global `timeout = 30` in `pyproject.toml` catches async-coordination bugs that would otherwise hang. The stress test uses a longer per-test override via `@pytest.mark.timeout(200)` (added to the `markers` config list in Phase 1b Task 13).

**5.4.5 — Substrate choice depends on what the test verifies.** Tests verifying MECHANISMS (clock-driven keepalive, atomic-write contract, hardlink behavior) use synthetic substrate. Tests verifying END-TO-END properties (regex matching real CDP outputs, real PVOC determinism, security boundary against real path traversal) need real CDP. The Task 13 plan-vs-implementation divergence (substituted `fake_subprocess` for real PVOC) is the clearest case: the test verifies the clock loop fires across 60 seconds, which is a mechanism property, so synthetic substrate is *purer* than real with variable timing.

### 5.5 Determinism findings (cache correctness)

**5.5.1 — PVOC anal: deterministic** (`e4e6954…` across runs)
**5.5.2 — PVOC synth: deterministic** (`26fb3dba…` across runs)
**5.5.3 — `blur blur`: NOT independently verified** in Phase 1b. The frog acceptance test confirms it produces correct-shaped output, but byte-determinism across runs hasn't been measured. Same caveat for `modify brassage`, `extend loop`, `filter sweeping`, `morph morph`. None are marked `phase_sensitive: true`, so they're assumed deterministic. **Phase 3 should verify each** as part of the curation-expansion work — empirical confirmation of determinism is what makes Phase 4's process-output cache (if revived) safe to enable.

---

## 6. Deferred work and reactivation triggers

Each deferred task has a specific signal that should trigger its reactivation. These aren't "we'll get to it eventually" deferrals — they're "build alongside the consumer" deferrals.

### Task 9: Auto-pinning + 15-recent `available_sources`

**Reactivation trigger:** real usage data showing the 5-slot `recent_graphs` tracker is too tight for a common workflow.

**What "too tight" looks like:** the LLM forgetting a graph it should reference because it fell off the deque, and the human having to manually retype `<graph_id>:nN`. If this happens occasionally, bump `maxlen=10` (one-line change). If it happens systematically, Phase 4's `tag()` is the proper solution — explicit pinning beats heuristic pinning.

**What NOT to do:** revive the auto-pin heuristic ("any node referenced by a later graph"). In branching exploration, nearly every node ends up referenced by something, so the heuristic provides no filtering. Phase 4's `tag()` + `history` is the durable answer.

### Task 12: Process-output cache (session-local, compositional)

**Reactivation trigger:** observed conversation-replay or "I'm re-creating the same call" patterns becoming common.

**Specific signals:**
1. Claude.ai users editing past messages and re-running long chains becoming a common workflow. (The cache makes replay near-instant.)
2. Telemetry (if added) showing 15%+ of `process()` calls match a previous call's full key.
3. User reports of "this is taking forever, I'm re-doing the same thing" patterns.

**Design notes for the future implementation** (preserves the Task 12 plan thinking):
- Cache key: `sha256(program + mode + submode + input_hashes + params_hash + cdp_version)`. Submode included from the start (Phase 3 future-proofing); `null` submode hashes as empty string `""`.
- Input hashes are of the *original* user-provided inputs (pre-PVOC). PVOC is an internal detail and is itself cached.
- `params_hash` uses **compiled `.brk` content sha** for breakpoint params, NOT raw tuple lists. Same tuple on different input durations → different `.brk` → different sha → different key. Comment this in source — invariant is load-bearing.
- Hit semantics: create a new graph dir with fresh timestamp, materialize the cached output via hardlink, write a fresh lineage with `cache_hit=True` and `cached_from=<source_gid>:<nN>`. Skip auto-PVOC and the main op entirely.
- `cache_index.json` is session-local with atomic write. Missing/corrupted → treated as empty (no rebuild logic in v1; Phase 4 cleanup_cache adds the rebuild predicate).
- Stale entries (cache_index points at a graph that's been `rm -rf`'d) → opportunistic purge on lookup.

### Task 14: `dependency_index.json` for cleanup safety

**Reactivation trigger:** Phase 4's `cleanup()` tool is being built.

The work is small (an atomic-write file maintained on every process() with cross-graph refs, ~10 unit tests, no schema changes). Build it alongside cleanup so the consumer and producer ship together with full context. Spec lives in the design doc.

### Task 15: `pad_with_fade` time-domain padding primitive

**Reactivation trigger:** Phase 2 (or Phase 3) is wiring multi-input PVOC alignment into the morph/cross/combine/convolve paths.

The design doc is explicit that the wiring is opportunistic — defer until a multi-input spectral op becomes a frequent operation. The primitive ships in P1 / wiring stays Opportunistic was v7's resolution; phase 1b inverts that to "defer both," but the primitive is no extra cost when its consumer arrives.

---

## 7. Development and operations guide

### 7.1 Running tests

```bash
# Default: 466 fast tests, slow stress test deselected
pytest

# Just the unit tests for one module
pytest tests/test_cache.py -v

# Acceptance test against real CDP (skips without CDP_PATH)
CDP_PATH=/path/to/cdpr8/_cdp/_cdprogs pytest tests/test_acceptance.py -v

# Slow stress test (~100s wall clock)
pytest -m slow tests/test_stress.py

# Everything, including slow
pytest -m ''

# Lint
ruff check src tests
```

### 7.2 Adding a curated knowledge entry

1. Drop a JSON file under `src/cdp_mcp/knowledge/data/<program>_<mode>.json`. Schema is `KnowledgeEntry` in `schema.py`.
2. Required fields with no default: `flag_kind` on each `ParameterSpec`, `submode` (use `null` if not applicable), `duration_model` (with discriminator), `channel_constraint`, `domain`, `input_arity`.
3. Pydantic loads at import time. Schema violations crash the server at startup, not silently — this is intentional.
4. **Verify determinism** before relying on caches (Phase 3 task). Run the program twice with same inputs/params/version, byte-compare outputs.
5. Add an end-to-end test in `tests/test_process.py` (or expand `test_acceptance.py` if it should run in the frog chain).
6. Update README's tools list if the entry adds a new program (not a new mode of existing program).

### 7.3 Adding a new stderr error pattern

1. Edit `src/cdp_mcp/error_parsing.py`. Add a regex constant at the module level.
2. In `parse_cdp_errors`, add an `if RE.search(combined):` block that appends a new `ErrorEntry`.
3. Conservative bias: false positives (misleading `fix` hints) are worse than false negatives (falling back to generic `subprocess_error`).
4. If the pattern needs `expected_output` or `verification`, document the precondition. `execute()` passes `None` for both.
5. Add a unit test in `tests/test_error_parsing.py` and an integration test via fake CDP if applicable.
6. Verify against real CDP output (manual check) before claiming the pattern is empirically grounded. Mark grounded vs speculative in regex comments.

### 7.4 Adding a new cache tier

1. Add subdirectory under `~/.cdp_mcp/cache/<tier>/` (created lazily on first write via `_ensure_tier_dir`).
2. New `<tier>_cache_key(...)` function in `cache.py`. Per-tier composition: include only software-version components that actually affect output. Document the omissions.
3. New tier name in `cache_size_bytes`'s known-tiers dict.
4. Call site: `cache_lookup` before the expensive op, `cache_populate` after success.
5. `cache_populate` failures are non-fatal — stderr warning, proceed.
6. If hits need a graph-dir artifact (like PVOC), use `materialize_cached_artifact(src, dst)`. If hits return data directly (like analyze JSON), read from cache path and return.
7. Add unit tests in `tests/test_cache.py` + integration test in the consumer's test file.

### 7.5 Debugging guide

**"Tests pass but real CDP fails."** Check the `_disable_apple_silicon_arch_wrapping` fixture — if your real-CDP run isn't disabling it appropriately, the venv Python interpreter wrapping issue will surface. Acceptance test sets `CDP_PATH` and runs against real binaries; per-tool tests use `fake_subprocess`.

**"Cache hit isn't firing when I expect."** Three checks:
1. Confirm the cache key includes all the right ingredients (`cache.py` key builders are pure functions; print them in a debug script).
2. Inspect `~/.cdp_mcp/cache/<tier>/` — is the artifact actually there?
3. Check `_LIB_VERSIONS` — has librosa/numpy/matplotlib been bumped since the cache was populated?

**"Subprocess seems to hang."** Almost always the MCP client gave up on a silent connection, not actual compute hanging. Per the forensics maxim: check whether the underlying work has completed. If `ctx.report_progress` isn't firing on a long subprocess, the keepalive is broken (regression — Task 13 should have caught it; run the slow stress test).

**"Path-with-dot SIGILL."** `modify brassage` and likely others have a `_cdptemp1` sibling-derivation bug that mangles paths with `.` in absolute ancestry. The cwd-relative argv trick in `processing.py:_argv_path` handles in-session paths. Session names with `.` in them (like `frog_acceptance_v1.0`) test this regression.

**"Watchdog seems to kill legitimate runs."** Check `CDP_MCP_OUTPUT_SIZE_CAP_BYTES`. PVOC analysis is 10-20× source wav size; a long stereo input legitimately produces a multi-GB `.ana`. Either reduce input duration, lower output cap to force the user to chunk, or override the cap via env var.

**"`pip install -e` doesn't see my new dependency."** Use `python -m pip install` to bind the install to the active interpreter. The bare `pip` might be in a different Python's `site-packages`.

### 7.6 What to do if real CDP changes (CDP9 etc.)

1. `_detect_version()` will report whatever the new install directory is named (e.g., `r9` if it's `cdpr9/`). The path-regex fallback handles it.
2. The mismatch warning fires automatically on sessions created under r8 (advisory, not refusal).
3. The PVOC cache key includes `cdp_version` — r8 artifacts won't accidentally serve to r9 runs.
4. Run the acceptance test against r9. If it fails, the curation may need adjustment (e.g., a CDP9 binary that changed argv shape would need a `version_sensitive: true` entry).
5. Phase 4's `cleanup_cache({type: "cdp_version", value: "r8.x"})` predicate is the planned tool for retiring r8 artifacts after the upgrade.

---

## 8. Phase 2 / 3 / 4 implications

### Phase 2 needs

- `graph()` for one-shot DAG materialization (with `dry_run=True` validation).
- `batch()` with `latest_batch[i]` aliases; `recent_graphs` accommodates batch entries.
- Three-mode stereo seed-linking (`linked`, `related` hash-salt default, `independent`) — `phase_sensitive: true` entries need `_stereo_link` engine option.
- `segments()`, `compare()`, `progression()` observation tools.
- Verbose `analyze()` (per-frame matrices, MFCCs, chroma, BPM with confidence, per-channel).
- `breakpoint()` named-shape DSL constructor (sine, ramp, etc.) that compiles to Phase 1b's polymorphic params.

**What Phase 1b set up that Phase 2 will lean on:**
- `LatestTracker`'s `update`/`update_batch` distinction needs to land for `batch()`; the schema's `RecentGraphEntry.batch_size` field is already in place.
- `compiled_breakpoints` field on lineage gives `breakpoint()` a place to record source shape metadata.
- `pad_with_fade` (deferred Task 15) primitive will be needed for multi-input PVOC alignment in morph/cross/combine/convolve paths.

### Phase 3 needs

- Knowledge expansion to ~30 curated programs (initial scope), then ~100.
- Port afta8's `definitions.lua` to schema as a starting seed.
- Hand-curate `musical_use`, `musical_range`, `phase_sensitive`, `stereo_link_default`, `duration_model`, `flag_kind`, examples.
- **Empirical determinism verification** for every curated entry (see §5.5).
- Dual-source verification script: cross-check CDP HTML docs against CDP8 source argv shapes.
- `cluster()` with PCA + hierarchical default; UMAP opt-in.
- `why()` provenance tool.
- CDP docs FTS5 index with version-mismatch rebuild trigger.
- Extract `docs/forensics.md` and `docs/testing-principles.md` from this handoff and the design doc's appendices (see §5).

### Phase 4 needs

- `tag()`, `journal()`, `set_config()`.
- `save_graph()`, `load_graph()`, `list_graphs()`.
- `cleanup()` with predicate grammar (glob / tag / age / graph_id / and / or), atomic cache_index scrub.
- `cleanup_cache()` with predicate grammar (`tier` / `cdp_version` / `lib_version` / `age` / `size_gt` / `and` / `or`).
- `export_to_ableton()` with confidence-gated manifest.

**Phase 1b's deferred work that Phase 4 should consume:**
- **Task 14 (dependency_index.json)** — build alongside cleanup; the consumer-aligned context will make the schema cleaner than building it in Phase 1b would have.
- **Task 12 (process-output cache)** — reconsider with usage data. Phase 4's `tag()` may render it unnecessary; or if conversation-replay is dominant, build it then.

### Cross-phase: extracting institutional knowledge

Phase 3 should extract §5 of this document into `docs/forensics.md` (CDP-specific) and `docs/testing-principles.md` (test infrastructure). This handoff document then becomes a Phase 1b artifact pointing at those canonical sources rather than holding them inline.

---

## 9. Known limitations and open questions

**Determinism unverified for 5 of the 7 Phase 1a entries.** PVOC anal and PVOC synth are confirmed deterministic. `blur blur`, `modify brassage`, `extend loop`, `filter sweeping`, `morph morph` are presumed deterministic (none marked `phase_sensitive`) but not individually byte-compared. Phase 3 should sweep these as part of the curation-expansion work.

**`.ana` input durations are not readable.** `soundfile.info()` doesn't support CDP's `.ana` format. Task 8's `source_wav_duration_s` on auto-PVOC nodes solves the chained case (cross-graph `.ana` references resolve back to the originating wav). Pre-converted `.ana` files dropped into `inputs/` are a remaining gap — duration unknown, `duration_model` skips for static, errors for expression-with-indur-reference. The watchdog covers either way.

**Cache key for PVOC doesn't include `_pvoc.window` / `_pvoc.overlap`.** These engine options aren't exposed in Phase 1b (only the defaults are used). When Phase 2 adds them, the PVOC cache key needs to grow.

**Process-output cache deliberately deferred.** Conversation-replay (the strongest use case) is uncertain frequency. Phase 4 reconsiders with data.

**No cache eviction.** `~/.cdp_mcp/cache/` grows unbounded. `describe_workspace` reports total size per tier so disk pressure is visible. Phase 4's `cleanup_cache()` is the planned eviction tool.

**Acceptance test machine sensitivity.** Real PVOC duration varies 10×+ across hardware. The stress test's `[60s, 180s]` window is the recorded threshold; on much-faster hardware the test would need `_INPUT_DURATION_S` retuned (which is why Task 13 substituted `fake_subprocess` for real CDP). Acceptance test itself is structural (sequence of calls produces sequence of outputs) so doesn't have timing assertions.

**Apple Silicon arch wrapping not exercised in CI.** All Phase 1b CI runs (if any) have been on developer machines. A CI matrix running on intel macOS without `arch -x86_64` wrapping would surface any regression in the auto-detection logic. Currently the only signal is the dev machine's success.

**LLM behavior with structured `fix` text is observational, not measured.** Across Tasks 4, 5, 6, 7, the manual-verification step asked "does Claude act on the `fix` text?" and the answer was qualitative. A Phase 5 user-study or telemetry pass could measure this directly.

**The 32-second IDM piece** (the project's immediate goal) hasn't been built end-to-end yet. Phase 1b shipped the engine; the actual artistic deliverable is the next thing to attempt now that the engine is production-quality.

---

## Appendix: how this handoff was assembled

The substantive content draws from:
- The design doc (cdp-mcp-design-v7.md) for stated intent
- Commit history (a835d3c through 0138f17) for what changed
- Conversation transcripts (`2026-05-27-00-43-18-...` and `2026-05-27-07-49-00-...`) for the *why* behind each non-obvious decision
- Repository state at HEAD (`0138f17`) for what's actually true now
- Empirical verification reports from each task closeout for forensic findings

The two transcripts together are ~15k lines and contain the per-task plan-review-implement-verify cycle for all 11 shipped tasks plus the planning conversations for the 4 deferred ones. Specific empirical findings (PVOC determinism, real CDP error phrasings, the SIGTERM-vs-SIGILL macOS finding, etc.) are scattered across those transcripts; §5 of this document is the consolidated extraction.

Future contributors who want depth on any specific decision can search the transcripts by task number or by the keyword that appears in §5 of this document. The journal at `/mnt/transcripts/journal.txt` indexes the transcripts.