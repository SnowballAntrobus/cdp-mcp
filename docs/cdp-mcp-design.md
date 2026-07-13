# CDP MCP: Design Document

> *Version 9 — final pre-Phase-2 revision. Absorbs four-reviewer feedback on v8: tool count corrected to ten throughout; `breakpoint_capable` curation review moved from Phase 3 to Phase 2 (Phase 2's `breakpoint()` tool needs targets); `_pvoc.window`/`_pvoc.overlap` cache key extension promoted from Open Questions to a Phase 2 ordering constraint (must land before the engine controls are exposed, or the LLM will hallucinate that window changes had no effect); determinism sweep for the five Phase 1a entries moved from Phase 3 to Phase 2; `batch()` semantics spelled out (atomic context event, single-graph-directory layout, alias resolution); `graph()` node ID scoping committed (bare = intra-graph, `<graph_id>:nN` = cross-graph); `graph()` intermediate cache lookups committed to content-hash addressing from lineage; multi-input wiring conventions named (which input drives breakpoint duration, `_pvoc.length_strategy` values, cross-graph multi-input cwd-relative argv); curating `combine cross` alongside multi-input wiring committed; `compare()` loudness matching given an algorithm with multi-method support; `progression()` aspect ratio and truncation behavior specified; `validate_node()` extraction from `process_impl` flagged as a precondition for `graph(dry_run=True)`; `simpleeval` configuration tightened with `names={}`; `.ana` duration via `dirsf` shell-out committed as the resolution path; "official Anthropic Ableton connector" reference dropped (no such public artifact); various smaller corrections. v9 is the implementation reference for Phase 2.*

> *v9.1 (2026-07-13) — mid-Phase-2 sync against the code audit (`docs/phase-2-audit-2026-07-13.md`). Corrections where implementation diverged from or superseded v9: `.ana` duration ships via `sfprops -d` (not `dirsf` — see Phase 2 operational fixes); `visualize` is mel-only with `t_end` (the `mode` parameter lands with the Phase 2 observation track); `describe_workspace`'s `history` field is now implemented; `combine cross` needs no length alignment (CDP natively truncates to the shorter input; its `duration_model` is `expression: "indur_min"` via evaluator-injected `indur_min`/`indur_max` names); Tasks 04 (PVOC cache-key extension) and 07 (`pad_with_fade`) were implemented then reverted pending consumers — see "Phase 2 mid-course reverts" under Architectural decisions.*

## Overview

An MCP server that wraps the Composers' Desktop Project (CDP) — a 500+ program suite of offline sound-transformation tools — for use by an LLM (specifically Claude) in collaboration with a human composer. The immediate goal is a 32-second IDM-style piece built from heavily processed frog croak samples. The broader goal is a reusable tool for LLM-augmented experimental sound design.

The MCP is one part of a larger workflow:

1. **CDP MCP** for sample mangling (this project)
2. **Ableton** for arrangement, via `ahujasid/ableton-mcp` (community-maintained)
3. Optional **Max** (separate, future) for playable instruments built from CDP outputs

## Position Relative to Existing CDP Wrappers

- **SoundThread** (j-p-higgins, 2.7k★) — Godot node GUI, ~100 curated processes, drawable breakpoints, auto channel management. The most successful CDP wrapper.
- **Renoise CDP Lua Tool** (afta8) — in-DAW wrapper with `definitions.lua` for ~50 processes.
- **CDP_MCP** (DavidPiazza, 11★) — minimal MCP passthrough; structural inspiration but not a code fork.

All three are GUI/CLI shells. Ours is an LLM-driven conversational shell — *not GUI-constrained*, so we expose more of CDP's surface at the introspection layer while concentrating curation on the ~100 most musically useful programs.

## Phase 1a + 1b: Shipped Status

**Production-ready as of commit `3dc09b9` (Phase 1b closeout).** Ten tools across the same surface as Phase 1a plus `read_envelope`, plus everything required to make that surface production-quality: caching, structured error parsing, guardrails, pre-flight checks, MCP keepalive regression-gated.

**What's in main:**

- **Ten tools**: `list_categories`, `list_programs`, `get_program_info`, `set_session`, `describe_workspace`, `read_envelope`, `execute`, `process`, `visualize`, `analyze`. (`read_envelope` was added during Phase 1b Task 8 follow-up for reading compiled `.brk` files back; see Tool Surface.)
- **Five curated knowledge entries**: `blur blur`, `extend loop`, `filter sweeping`, `modify brassage`, `morph morph` (submode 1). `extend loop`'s `duration_model` migrated from mis-specified `linear` to `{kind: expression, expr: "cnt * len / 1000"}` during Phase 1b Task 6.
- **Derivative cache layer** (Tasks 10, 11): four tiers under `~/.cdp_mcp/cache/` (pvoc, analysis, visualizations, audition). Per-tier library-version composition. Measured speedups: PVOC 15×, visualize 120×, analyze 1231×, audition 7.5× on the param-variation case.
- **Pre-flight + reactive guardrails** (Tasks 6, 7): `duration_model` evaluator via `simpleeval` (with `functions={}` and `names={}` hardening) catches runaway parameters before CDP starts. Disk watchdog SIGKILLs subprocesses that cross the size cap mid-run. Env-var-configurable caps via `CDP_MCP_OUTPUT_SIZE_CAP_BYTES` and `CDP_MCP_DURATION_CAP_S`.
- **Structured error taxonomy** (Task 5): four CDP-specific patterns (`output_exists`, `channel_mismatch`, `usage_banner_returned`, `silent_output`) plus the duration-preflight family and `size_cap_exceeded`. Each carries action-oriented `fix` text. Pattern matching runs against `stderr + stdout` because CDP r8 emits error-class messages to stdout.
- **Polymorphic parameters** (Task 8): constants, relative-time tuples, absolute-time tuples, or paths to existing `.brk` files. Defensive compilation: sort, dedupe at 1e-6, auto-append final point, content-hash into cache key.
- **Context block with `recent_graphs`** (Task 3): five-entry deque with `latest`, `prev_1`..`prev_4` aliases. Per-process; pruned by future `cleanup()` without slot renumbering.
- **CDP version detection** (Task 4): probe primary + path-component regex fallback (most stock r8 installs lack a `cdp` binary). Mismatch warning on session reload.
- **MCP timeout keepalive regression-gated** (Task 13): `@pytest.mark.slow` stress test exercises the clock-driven progress emitter across an 80s subprocess, asserts ≥5 progress calls in `[60s, 180s]`.
- **Test infrastructure**: 467 tests collected (466 default + 1 slow). Fake-CDP fault-injection (`--cdp-refuse-clobber`, `--cdp-die-on-dot-path`, `--cdp-silent-output`, `--cdp-grow-file`). Real-CDP acceptance suite under the deliberately-dotted `frog_acceptance_v1.0` session name.

**What's NOT in main (intentional non-goals or Phase 2+):**

- The tool *surface* is unchanged from Phase 1a plus `read_envelope`. `graph()`, `batch()`, `segments()`, `compare()`, `progression()`, `breakpoint()` are Phase 2.
- *Knowledge layer scope* is unchanged. Same five curated entries (one is breakpoint-capable; others need a Phase 2 review pass). Phase 3 expands to ~30, then ~100 in Phase 5.
- *Cross-session intelligence beyond the derivative cache.* Process outputs deliberately stay session-local.
- *Four Phase 1b plan items* were dropped or deferred with explicit reactivation triggers.

The Phase 1b Handoff document (`docs/phase-1b-handoff.md`) is the canonical record of what shipped, what didn't, and why, with §5 forensic findings and §6 reactivation triggers.

## Design Principles

**Introspection over enumeration.** Small discovery surface lets Claude learn at runtime. From 8beeeaaat's TouchDesigner MCP.

**Tiered abstraction.** Structured tools for common operations plus an escape hatch (`execute`). *Thick* on engineering known-knowns (PVOC lifecycle, channels, parameter ranges, error parsing); *thin* on creative space (chain choice, parameter selection, aesthetics).

**Per-call mini-graphs with cross-references.** Every `process()` creates a new graph directory containing a single executed node. Later calls reference earlier nodes via `<graph_id>:nN` or the `"latest"`/`"prev_1"`/`"prev_2"` aliases. `graph()` (Phase 2) creates one graph directory containing multiple nodes — the cross-graph reference syntax is uniform across single-node and multi-node graphs (see Graph Execution Semantics for node ID scoping rules inside `graph()`).

**Multi-input DAG semantics when needed.** Morph, convolve, cross-synthesis, mixing are inherently multi-input. Phase 2 wires the multi-input path through `process()` and `graph()` with explicit conventions for length alignment, breakpoint duration source, and channel handling (see PVOC Lifecycle Management § Multi-Input Conventions).

**Observability throughout.** Spectrograms, MIR features, structural analysis, comparative views. The MCP makes audio *visible* to Claude.

**Source-control transparency.** Sessions are filesystem directories. Graphs are JSON. Outputs are predictable filenames. Session state IS directory contents.

**Curated knowledge over raw exposure.** Layer community knowledge over official docs; surface as structured metadata, not academic prose.

**Implicit verification with state grounding.** Every action verifies its output and returns parsed errors. Returns also include a `context` block so Claude stays grounded across turns without scrolling back.

**Rough end-to-end first.** Ship the smallest version of each capability that completes a real user-visible loop, then harden. Phase 1b validated this by dropping/deferring four planned-but-consumer-less items. The discipline continues into Phase 2: ship narrowly, let real use surface what comes next.

## Architecture

```
┌───────────────────────┐
│ Claude (MCP client)   │
└──────────┬────────────┘
           │ MCP protocol (stdio/JSON-RPC, async)
┌──────────▼────────────┐
│ CDP-MCP server        │  Python 3.10+, FastMCP, asyncio
│ ├─ Tool dispatcher    │
│ ├─ Action layer       │  process / execute / visualize / analyze
│ │                        + Phase 2: graph / batch / breakpoint
│ ├─ PVOC lifecycle     │  auto-anal/synth, audition synth cache
│ │                        + Phase 2: multi-input alignment, pad_with_fade
│ ├─ Subprocess core    │  asyncio.create_subprocess_exec + clock-driven keepalive
│ ├─ run_with_progress  │  same keepalive for sync CPU work
│ ├─ Cache layer        │  Global: PVOC / analysis / viz / audition
│ │                        Session: process outputs (compositional)
│ ├─ Disk watchdog      │  per-second size + timeout monitoring
│ ├─ Duration preflight │  simpleeval against duration_model
│ ├─ Error parsing      │  Four CDP-stderr patterns + duration family + size_cap
│ ├─ Observation layer  │  librosa, pyloudnorm, matplotlib (Agg), Pillow
│ ├─ Knowledge layer    │  Pydantic schema (5 entries; Phase 3 expansion)
│ ├─ Session manager    │  Filesystem-based
│ └─ Security gate      │  Binary location + metachar + path scope
└──────────┬────────────┘
           │
┌──────────▼────────────┐  ┌────────────────────────────┐
│ CDP binaries          │  │ ~/cdp_sessions/<name>/     │  + ~/.cdp_mcp/cache/
│ (cdpr8/_cdprogs/*)    │  │ (configurable via env)     │   (global derivative artifacts)
└───────────────────────┘  └────────────────────────────┘
```

### Sessions and Cache Locations

Sessions root defaults to `~/cdp_sessions/` (configurable via `$CDP_MCP_SESSIONS_ROOT`). Each session:

```
<sessions_root>/<name>/
├── config.json              ← session metadata, CDP version, defaults
├── inputs/                  ← source audio
├── graphs/                  ← one directory per process(), graph(), or batch() call
│   └── <timestamp>-<name>/
│       ├── graph.json            ← user intent, opt-in
│       ├── node_index.json       ← atomic via .tmp + os.replace
│       ├── lineage.json          ← per-graph; atomic-write
│       ├── n1_<op>.{wav,ana}     ← process outputs (session-local)
│       └── ...
├── envelopes/               ← compiled .brk files (content-hashed names)
├── tmp/                     ← transient intermediates
└── visualizations/          ← PNG outputs (separate from global viz cache)
```

Global artifact cache at `~/.cdp_mcp/cache/`:

```
~/.cdp_mcp/cache/
├── pvoc/                ← .ana files: sha256(audio_bytes + argv_discriminator + window + overlap + cdp_version)
├── analysis/            ← MIR feature JSON: sha256(audio_bytes + feature_set + lib_versions)
├── visualizations/      ← spectrogram PNGs: sha256(audio_bytes + mode + render_params + lib_versions)
└── audition/            ← .ana → temp .wav: sha256(ana_bytes + cdp_version)
```

**The PVOC cache key includes `window` and `overlap`** (Phase 2 extension). v8 left this in Open Questions; v9 commits to fixing it as a Phase 2 ordering constraint: the engine controls `_pvoc.window` and `_pvoc.overlap` cannot be exposed to the LLM before the cache key grows to include them. If they were exposed first, the cache would serve stale `.ana` files for window-changed requests, and the LLM would observe that changing the window had no audible effect — a silent correctness bug that would be hard to debug.

### Cache Strategy: Derivative (Global) vs. Compositional (Session-Local)

**Derivative artifacts go global.** PVOC `.ana` files, MIR features, spectrograms, audition synth wavs are *pure functions* of `(input_bytes, parameters, software_versions)`. Identical regardless of which session triggered them. Cross-session deduplication; lifetime independent of any session.

**Per-tier library version composition.** PVOC keys depend on `cdp_version` only — PVOC analysis is a pure CDP computation. Analysis cache keys mix in `librosa`, `numpy`, `scipy`, `pyloudnorm`. Visualization keys mix in `librosa`, `numpy`, `matplotlib`. A library bump invalidates only the tiers that depend on it.

**Cache writes are non-fatal.** Every `cache_populate` wraps the disk write in try/except. On failure (full disk, permissions), a stderr warning fires and the operation proceeds with the live result.

**Materialization helper.** Cache hits that need a graph-dir file go through `cache.materialize_cached_artifact(src, dst)`: try `os.link()` (POSIX hardlink, zero disk cost) first, fall back to `shutil.copy2` (preserves mtime — relevant when Phase 4's `cleanup_cache()` adds age-based eviction).

**Compositional artifacts stay session-local.** Process outputs (`n1_<op>.wav`) are *intentional creative products* tied to the graph and session that produced them. Deleting a session should delete its outputs. **In Phase 1b, process outputs are NOT cached** (Task 12 was deferred). Phase 4 reconsiders with usage data.

**Cache key construction is content-addressed, not path-addressed.** For `graph()` (Phase 2), this is load-bearing: when Node B's auto-PVOC consumes Node A's output, the PVOC cache key uses `sha256(Node A's actual output bytes + window + overlap + cdp_version)`. Node A's output sha256 is recorded in its `lineage.json` entry, so the engine reads the hash from lineage rather than re-hashing on every lookup. The cache remains blind to whether it's operating inside a multi-node DAG or a single `process()` call — same content, same key, same hit.

**Global cache eviction: explicit, user-invoked.** `cleanup_cache(predicate?)` (Phase 4) is the user's lever. No surprise auto-evictions. `describe_workspace()` reports per-tier cache sizes so disk pressure is visible. Predicate grammar — `tier` / `cdp_version` / `lib_version` / `age` / `size_gt` / boolean composition — is committed; the `cdp_version` predicate is the key one for retiring artifacts after a CDP upgrade.

### PVOC Lifecycle Management

CDP's phase-vocoder pipeline is the most error-prone aspect of CDP use.

**Auto-conversion (Phase 1a, shipped).** Spectral op on WAV input → engine inserts `pvoc anal` upstream as an addressable node. Time-domain op on `.ana` input → engine inserts `pvoc synth` upstream. Auto-inserted PVOC nodes are first-class addressable via the audition cache's `.ana → .wav` synth.

**PVOC + audition caching (Phase 1b, shipped).** Two caching layers stack:
- **PVOC cache** at `~/.cdp_mcp/cache/pvoc/<sha>.ana` — hardlinked into any future graph dir that needs the same analysis under the same CDP version and PVOC parameters (window, overlap).
- **Audition cache** at `~/.cdp_mcp/cache/audition/<sha>.wav` — the `.ana → .wav` synth needed by `visualize` / `analyze` is cached globally, keyed by `sha256(ana_bytes + cdp_version)`.

**Pre-delete contract (Phase 1a, shipped).** CDP r8's `pvoc synth` refuses to overwrite existing output files and exits 255 — emitting the error message to stdout, not stderr. The engine unconditionally `unlink(missing_ok=True)`s any output path before invoking CDP in a re-invocation path.

**PVOC byte-determinism is verified** for `pvoc anal` and `pvoc synth` only. The other Phase 1a curated programs (`blur blur`, `modify brassage`, `extend loop`, `filter sweeping`, `morph morph`) are *assumed* deterministic but not byte-compared. **Phase 2 includes the determinism sweep** for these five entries (~2-3 hours per entry, mechanical: process same input twice, compare output sha256s). v8 placed this in Phase 3; v9 moves it to Phase 2 because Phase 4's process-output cache reactivation depends on knowing which entries are safe to cache.

### Multi-Input Conventions (Phase 2)

Multi-input wiring lands in Phase 2 alongside the consuming `combine cross` curated entry. The conventions below need to be named explicitly because they're not derivable from CDP's docs or from single-input behavior.

**Which input drives breakpoint duration.** For a multi-input op with a `breakpoint_capable: true` parameter, relative-time breakpoints `(0.0, ...)` to `(1.0, ...)` are compiled against **input 1's duration by default**. This matches CDP convention: most multi-input ops (morph, combine cross, etc.) treat the first input's timeline as the controlling timeline. The knowledge schema gains an optional `breakpoint_duration_source` field per parameter:

```json
"interp": {
  "type": "float", "flag": null, "breakpoint_capable": true,
  "breakpoint_duration_source": "input1",   // default; "input2", "max", or "min"
  ...
}
```

`compiled_breakpoints` in lineage records which input duration was used.

**`_pvoc.length_strategy` named values.** For multi-input spectral ops whose inputs differ in duration:
- `"pad_with_fade"` (default) — shorter input gets 5 ms cosine fade-out at its tail, then zero-pads to match the longer input. The `pad_with_fade` primitive (deferred Phase 1b Task 15) ships with this wiring.
- `"truncate_to_shortest"` — longer input is cut at the shorter input's duration with a 5 ms fade-out at the cut point.
- `"stagger:<seconds>"` — explicit stagger offset; relevant for `morph morph` which has a built-in `-sstagger` flag. The engine sets the flag rather than padding.
- `"fail"` — return a structured `multi_input_length_mismatch` error if durations differ.

The default per curated entry is set via `entry.default_length_strategy`; the user can override via `_pvoc.length_strategy` in params.

**Multi-input cwd-relative argv.** Cross-graph multi-input refs like `input=["frog.wav", "<other_graph>:n3"]` resolve both paths through `_argv_path` against `cwd=session.root`. Both are inside the session tree → both render cwd-relative. The Phase 2 acceptance test exercises this under a dotted session name (the brassage path-mangling regression generalized to multi-input). Currently `compiled_breakpoints` records one `source_duration_s`; the field becomes a per-input map when multi-input breakpoint-capable ops land.

### Sync Work in Async Tools (load-bearing)

MCP tools are `async def`, but matplotlib rendering, librosa feature extraction, and sha256-on-big-files are synchronous CPU work. Running them directly inside `async def` blocks the event loop, starves MCP heartbeats, and looks like a crash to Claude Desktop.

**The fix: `run_with_progress(ctx, label, fn, *args)`.** Push the blocking call into `asyncio.to_thread`, fire periodic `ctx.report_progress` notifications from the main coroutine, cancel the heartbeat task when the work returns. Default `interval_seconds=5.0`. Used in `visualize`, `analyze`, and required for any future Phase 2 observation tool.

### Matplotlib Backend (module-level, not env-var)

`matplotlib.use("Agg")` lives at the top of `visualization.py`, before any pyplot import. Co-located with the only consumer; can't be removed by someone cleaning up `server.py` imports; works whether or not `server.py` ran first (which matters for tests that import `visualization` directly).

`MPLBACKEND=Agg` as an environment variable is unreliable: launch wrappers (`uvx`, `npx`, IDE-spawned servers) drop or override env vars. If pyplot is imported before the env var is read, matplotlib defaults to a GUI backend which hangs the headless MCP server.

### MCP Timeout Handling

**Implementation (Phase 1a, shipped).** FastMCP `async def` tools. CDP subprocess via `asyncio.create_subprocess_exec()` with three concurrent tasks: stdout consumer, stderr line-by-line consumer (updating shared `latest_stderr_line`), and **clock-driven** progress emitter calling `ctx.report_progress` every 5 seconds via `asyncio.sleep`. Clock-driven, not CDP-driven — the keepalive fires on schedule regardless of whether CDP itself is emitting stderr.

**Stress test (Phase 1b Task 13, shipped).** `tests/test_stress.py` (`@pytest.mark.slow`) runs an 80s subprocess sleep, asserts ≥5 progress calls and `60_000 < duration_ms < 180_000`. Substrate is `fake_subprocess` (real PVOC scales nonlinearly with input duration; the test verifies a mechanism property).

**Async-escalation surface decision.** If progress reporting ever fails to keep some operation class's connection alive, the fallback is server-internal polling. The LLM-visible tool surface stays synchronous.

Per-process hard timeout defaults to 120 seconds, configurable via `_timeout`. Combined with the disk watchdog, this prevents runaways independent of MCP-layer behavior.

### Cwd-Relative Argv Paths (load-bearing)

`modify brassage` (and likely others) crash with SIGILL on absolute paths whose ancestry contains a `.` in any directory name — root cause is brassage's `_cdptemp1` sibling-derivation logic. Fix: render argv paths cwd-relative when inside the session tree; outside (e.g. CDP cache for shared `.ana` files) they stay absolute. The security gate's path-scope check resolves both forms against `session.root` before checking.

The acceptance test uses session name `frog_acceptance_v1.0` to lock in the regression. Phase 2 adds a multi-input cross-graph variant of this test (see Multi-Input Conventions).

### Resource Limits, Guardrails, and Duration Pre-Flight

**Hard limits (Phase 1a defaults; env-var-overridable in Phase 1b):**

- **Output duration cap:** 5 minutes per node (override: `CDP_MCP_DURATION_CAP_S`)
- **Output file size cap:** 1 GB per node (override: `CDP_MCP_OUTPUT_SIZE_CAP_BYTES`)
- **Session disk budget:** 5 GB soft warning, 20 GB hard fail (Phase 4 set_config)
- **Process timeout:** 120 seconds per CDP invocation; overridable via `_timeout`

**Disk watchdog (Phase 1b Task 7, shipped).** asyncio task polls `os.path.getsize(output_path)` every second; if the file crosses the size cap mid-run, the watchdog sends SIGKILL, removes the partial output, and returns a structured `size_cap_exceeded` error.

**Duration pre-flight via `duration_model` (Phase 1b Task 6, shipped).** Four kinds in the discriminated union: `static`, `set_by`, `linear`, `expression`. Three structured failure modes: `predicted_duration_evaluation_failed`, `predicted_duration_negative`, `predicted_duration_exceeds_cap`.

**Expression evaluation safety.** `simpleeval` is configured with **both `functions={}` and `names={}`** — no `math.sqrt`, no `int()`, no `abs()`, no attribute access. Allowed: arithmetic operators (`+`, `-`, `*`, `/`, `**`), parentheses, and the names injected for evaluation (`indur`, `indur1`, `indur2`, and the entry's parameter names). v8 specified only `functions={}`, which left `simpleeval`'s default builtins (`int`, `float`, `abs`, `min`, `max`) accessible. v9 tightens this — the threat surface is curator-authored JSON (defense-in-depth), and there's no curator use case that benefits from `int()`. For future curated entries that need non-linear duration models (logarithmic, square-root scaling), the pattern is to pre-compute the scalar Python-side and inject it as a constant name, keeping the expression arithmetic-only.

### Error & Verification Contract

Every action tool returns a `ResultEnvelope`:

```json
{
  "status": "ok" | "failed" | "partial_success",
  "output": "<path or null>",
  "stdout": "...", "stderr": "...", "exit_code": 0,
  "errors": [{"type": "channel_mismatch", "message": "...", "fix": "..."}],
  "warnings": [...], "cached": false, "duration_ms": 1240,
  "context": { /* ContextBlock */ }
}
```

**Structured error types** added in Phase 1b: `predicted_duration_evaluation_failed`, `predicted_duration_negative`, `predicted_duration_exceeds_cap`, `size_cap_exceeded`, `output_exists`, `channel_mismatch`, `usage_banner_returned` (exit-code-agnostic), `silent_output`, `param_breakpoint_*` family.

Phase 2 adds: `multi_input_length_mismatch` (when `_pvoc.length_strategy = "fail"` and inputs differ), `graph_topology_error` (cycles, unresolved references), `graph_channel_propagation_error`.

**Additive composition.** Specific entries coexist with the existing generic ones (`subprocess_error`, `output_verification_failed`). The specific entry's `fix` field is what the LLM acts on; the generic remains as residual confirmation.

**Error precedence**: `size_cap_exceeded` > `timed_out` > `subprocess_error`. The SIGKILL-induced negative exit code doesn't double-report.

**`active_graph` vs `latest` after failure.** `active_graph` reports the just-acted-on graph regardless of outcome. `latest` only resolves to the last *successfully produced* node — prevents failure cascade.

### Context Block Semantics

The context block carries `active_graph`, `latest`, `recent_graphs`, and `available_sources` on every action envelope.

**`recent_graphs` (Phase 1b Task 3, shipped).** Five-entry deque. Per-process state, not persisted. Aliases `latest`, `prev_1`..`prev_4`.

1. Reset on server restart.
2. Not backfilled from disk on `set_session()`.
3. Pruned by `cleanup()` (Phase 4) without renumbering: if `prev_2`'s pointed-at graph is removed, `prev_2` becomes absent; `prev_3` stays as `prev_3`.
4. `prev_N` aliases are stable for the lifetime of their pointed-at graph.
5. `latest` after a failed `process()` resolves to the last successfully produced node.
6. **`batch()` is an atomic context event** (Phase 2). A `batch()` call with N inputs produces N output nodes but pushes a **single** synthetic entry onto `recent_graphs` (with `output_node: null` and `batch_size: N`). The deque is not updated during the internal loop. Without this, a 10-item batch would evict its own early results and previous conversational context before returning. `latest` continues to point to the last single-output action; individual batch outputs are addressed via `latest_batch[i]` (see `batch()` in Tool Surface).

**`available_sources` (Phase 1b: simple form).** Deduplicated session inputs + recently produced graph outputs. v7's planned auto-pinning heuristic was rejected in Phase 1b implementation (it didn't filter anything in branching exploration). Phase 4's explicit `tag()` is the durable answer.

**Three related lists, three distinct purposes:**
- **`recent_graphs`** — live conversational subset (5 entries, with `latest`/`prev_N` aliases). Per-process.
- **`available_sources`** — working set in every action envelope.
- **`history`** in `describe_workspace()` — complete session record, built from the filesystem at call time.

### Channel Handling (Phase 2)

Channels are first-class graph types. Each node tracks input and output channel count.

Mono-only ops on stereo input get explicit `<node>_L` / `<node>_R` sub-nodes that process each channel independently and rejoin downstream via Python (`numpy.column_stack` + `soundfile.write`), not CDP `housekeep interleave`.

**Stereo seed-linking — three modes (Phase 2).** Stochastic CDP processes marked `phase_sensitive: true` need careful seed handling on stereo splits. `_stereo_link` accepts:
- `"linked"` — identical seeds across L and R; channels bit-identical.
- `"related"` (**default**) — `seed_R = int(hashlib.sha256(f"{seed_L}_RIGHT".encode()).hexdigest()[:8], 16) % MAX_INT`. **Hash-salt, not additive offset** (legacy C PRNGs exhibit severe sequence correlation under additive offsets).
- `"independent"` — fully independent seeds; maximum width, mono-incompatible.

**Channel handling implementation likely waits for Phase 3.** Phase 1a's five curated entries are all mono-or-any; none are `phase_sensitive: true`. Without a curated stochastic stereo entry to exercise, building the L/R split + stereo seed-linking machinery is speculative. The schema and engine namespace are committed; the wiring lands when Phase 3 curates the first `phase_sensitive: true` program (likely candidates from CDP8: `blur scatter`, `distmore`, programs in `texture/` or `grain/`).

### Reproducibility & Version Handling

- `config.json` records CDP version at session init plus Python and library versions
- `lineage.json` carries full provenance: argv, input hashes, output_path with sha256, params, cdp_version, library versions, timestamps, `source_wav_duration_s` on auto-PVOC nodes, `compiled_breakpoints` (per-input source duration when multi-input breakpoint-capable ops land), seeds
- All session-level JSON state uses `.tmp` + `os.replace` atomic writes

**CDP version detection.** `_detect_version()` first tries `cdp --version`, falls back to walking `cdp_path.parts` in reverse for a `cdp[_-]?r?\d+(\.[\w.]+)?` pattern. Stock CDP r8 has no `cdp` binary; the fallback catches the common case.

**Version mismatch on session reload.** Warning lists both versions; proceed by default. `version_sensitive` flag in the knowledge schema reserved for refuse-and-prompt.

### Security Boundary (Phase 1a, shipped)

Three independent checks; all violations collected into one envelope:

1. **Binary location** — `argv[0]` must be a bare CDP program name or absolute path inside `$CDP_PATH`. Symlinks resolved before checking.
2. **Shell metacharacters** — `command[1:]` containing any of `;|&$\`><()\n\r\0` is rejected. Denylist by design; subprocess invocation is `shell=False`; denylist is defense-in-depth.
3. **Path scope** — `command[1:]` extensions in the path-like catalog must resolve inside the session tree or the CDP cache.

## Tool Surface

Target: ~22 tools across six groups. Phase 1a+1b shipped 10; the rest land in subsequent phases.

### Introspection (Phase 1a complete)
- `list_categories()` [1a]
- `list_programs(category?, curated_only=True)` [1a]
- `get_program_info(program, mode?)` [1a]
- `search_docs(query, limit?)` [3]
- `read_doc(uri)` [3]

### Workspace
- `set_session(name)` [1a]
- `describe_workspace()` [1a/1b] — file counts, recent graph IDs with summaries, **per-tier cache sizes (Phase 1b Task 10)**, available templates, and `history` field (compressed mapping of all session graph IDs to their primary outputs, for explicit recall)
- `read_envelope(path)` [1b — Task 8 follow-up] — reads compiled `.brk` files (and other small text envelopes) back from `session.envelopes_dir`. Path-scoped; extension allowlist; size cap. Lets the LLM verify what was compiled from its tuple list.
- `set_config(key, value)` [4]
- `list_session_files(pattern?)` [4]
- `tag(target, tags[])` [4]
- `cleanup(predicate)` [4] — predicate grammar (`glob` / `tag` / `age` / `graph_id` / `and` / `or`); refuses to delete files in the dependency index; atomically scrubs cache index entries
- `cleanup_cache(predicate?)` [4]
- `journal(note)` [4]
- `write_data_file(path, content)` [3 or 4] — workspace tool for CDP programs taking auxiliary text/data inputs (`tesselate`, `newmorph2`). Path-scope security; extension allowlist (`.txt`, `.dat`, `.csv`, `.brk`); 4 MB content cap.

### Action
- `process(program, mode, input, params, output_name?, timeout_seconds=120)` [1a/1b] — primary action. One new graph directory per call. Auto-PVOC, validation, duration pre-flight, output verification, lineage write. `input` accepts a path or a `<graph_id>:nN` reference. Multi-input curated entries (Phase 2: `morph morph`, `combine cross`) accept `input=[a, b]`.
- `execute(command, timeout_seconds?)` [1a] — escape hatch under the three-check security gate.
- `graph(inputs, nodes, output, dry_run=False)` [2] — declarative full-DAG (see Graph Execution Semantics).
- `batch(program, mode, inputs[], params, **engine_opts)` [2] — N parallel `process()`-equivalent calls under a single graph directory.

  **On-disk layout (Phase 2 specification).** `batch()` creates **one** graph directory containing N output nodes:
  ```
  graphs/<timestamp>-batch-<program-mode>/
  ├── n1_batch_0_<op>.wav      ← first batch element's output
  ├── n1_batch_1_<op>.wav      ← second
  ├── ...
  ├── node_index.json          ← {"n1_batch_0": "n1_batch_0_<op>.wav", "n1_batch_1": ...}
  └── lineage.json             ← nodes: {"n1_batch_0": {...per-element provenance...}, ...}
  ```
  Auto-PVOC nodes (if any) become `n0_batch_i_pvoc-anal.ana`. Each batch element is independently cached via the derivative caches (PVOC, auto-PVOC).

  **Alias resolution.** `latest_batch` is bound to the list of node IDs in this graph (`["n1_batch_0", "n1_batch_1", ...]`). `latest_batch[i]` resolves to `<graph_id>:n1_batch_i`. The conventional `target` parser recognizes the array-indexing syntax.

  **`recent_graphs` interaction.** See Context Block § rule 6: batch is atomic. One synthetic deque entry, `output_node: null`, `batch_size: N`. `prev_1` after a batch refers to the batch entry; individual results via `latest_batch[i]`.

- `breakpoint(shape, **kwargs)` [2] — named-shape DSL constructor. Compiles to Phase 1b's polymorphic-param tuples (so `breakpoint("linear", start=10, end=50, duration_relative=1.0)` returns a tuple list the param compiler accepts). The value over raw tuples: **named shapes** (`"linear"`, `"exponential"`, `"sigmoid"`, `"pulse_train"`, `"step"`, `"random"`) that would be tedious to spell as tuples; **seed control** for reproducible `"random"`; **validation** against the target parameter's `breakpoint_capable` flag at construction time rather than process time. Raw tuples remain the "I know the exact points" path; `breakpoint()` is the "I know the shape" path.

- `save_graph(name)` / `load_graph(name, overrides?)` / `list_graphs(tag?, include_implicit=False)` [4]

### Observation

- `visualize(target, t_start?, t_end?)` [1a/1b — mel-only as shipped]. PNG output. `.ana` targets auto-synth via audition cache. **Phase 1b adds**: cache layer (~120× speedup on hits). The `mode="mel"|"lin"|"cqt"|"multi"` parameter lands with the Phase 2 observation track (the cache key already carries a mode discriminator).

- `analyze(target, t_start?, t_duration?, verbose=False)` [1a/1b concise; verbose Phase 2]. **Phase 1b adds**: cache layer (~1231× speedup on hits).

- `segments(target, method="onset"|"novelty"|"silence")` [2]. Returns:
  ```json
  {
    "segments": [{"start": 0.0, "end": 1.234, "label": "onset_0"}, ...],
    "visualization": "<png_path>",
    "method": "onset",
    "count": 42
  }
  ```
  The visualization is a spectrogram with vertical segment markers, cached in the global visualization cache (pure function of audio + method + render params).

- `compare(target_a, target_b, loudness_method="lufs_i")` [2]. Paired spectrograms + feature deltas in one composite PNG.

  **Loudness matching.** Default `loudness_method="lufs_i"` (integrated LUFS via `pyloudnorm`); both files gain-adjusted to the *quieter file's* LUFS-I so dynamic range is preserved and noise isn't amplified. Two alternative methods for IDM/transient material:
  - `loudness_method="lufs_m"` — momentary LUFS (400 ms window), better for short transients where integrated loudness misleads.
  - `loudness_method="peak"` — peak normalization to -1 dBFS, ignores LUFS entirely.

  When crest factor delta between targets exceeds 12 dB and `loudness_method="lufs_i"`, the result envelope emits a warning suggesting `loudness_method="peak"`. (A transient and a noise wash can share LUFS-I but feel wildly different in volume; the warning steers the user toward an appropriate method.)

- `progression(targets[] or graph_id)` [2]. Stacked spectrograms in topological order via PIL composite (not matplotlib-tiled — `bbox_inches="tight"` would garble grid alignment).

  **Panel layout.** Each panel is a fixed width (default 1024 px); height scales proportionally to preserve the time-axis aspect ratio (so a 1 s frog croak and a 30 s spectral blur don't get squished into the same panel size). Vertical stack with 20 px gutters and a left-aligned time-axis ruler.

  **Truncation.** Panel cap at **8 nodes**. For >8 nodes: first 8 panels rendered + a 9th text-only panel reading `"N more nodes omitted. Use cluster() or specify a subset."`. The envelope's `warnings` array also records the truncation.

- `cluster([targets...], method="hierarchical", k?, seed?)` [3].

### Provenance
- `why(target)` [3] — full lineage for any output.

### Export
- `export_to_ableton(targets[] or tag, destination_dir, normalize=False)` [4] — confidence-gated manifest columns for BPM/key estimates.

**Target argument:** filepath, `<graph_id>:nN`, or alias (`latest`, `prev_1`-`prev_4`, `latest_batch[i]`).

### Engine-Control Namespace

`_*` prefix on `params` keys and as direct kwargs:
- `_seed` [Phase 2]
- `_stereo_link ∈ {"linked", "related", "independent"}` [Phase 2]
- `_timeout` — per-call timeout override
- `_pvoc.window`, `_pvoc.overlap`, `_pvoc.length_strategy` [Phase 2 — see Multi-Input Conventions; **cache key must be extended before exposing these to the LLM**]
- `_keep` [Phase 4]
- `_output_name` [1a as `output_name` kwarg]

### Polymorphic Parameters (Phase 1b shipped)

A parameter is a constant, a list of `(time, value)` tuples (relative time 0.0-1.0 or absolute via `"abs:"` prefix), or a path to an existing `.brk` file.

Defensive compilation: sort, dedupe near-identical timestamps (1e-6 threshold), auto-append final point, validate `breakpoint_capable`, compile to absolute-time `.brk` in `session.envelopes_dir`, content-hash into cache key. For multi-input ops, the relative-time base duration is taken from `entry.parameters[name].breakpoint_duration_source` (default "input1"; see Multi-Input Conventions).

**`breakpoint_capable` curation status (Phase 1b end).** Only `blur_blur.blurring` is flagged `True`. The ~20 plausibly-capable parameters across the other four entries are still `False`. **Phase 2 includes the curation review pass** (moved from Phase 3): a same-commit schema review identical to the Phase 1b `flag_kind` migration, flipping flags where CDP empirically supports breakpoint envelopes (e.g., `filter sweeping`'s frequency parameters, `extend loop`'s loop times, `modify brassage`'s velocity, `morph morph`'s time parameters and stagger). Without this pass, the new `breakpoint()` DSL constructor has only one parameter to target.

## Knowledge Layer Schema

```json
{
  "program": "morph", "mode": "morph", "submode": 1,
  "category": "morph", "domain": "spectral", "input_arity": 2,
  "channel_constraint": "mono", "input_format": ".ana", "output_format": ".ana",
  "stability": "stable", "phase_sensitive": false, "stereo_link_default": null,
  "duration_model": {"kind": "static"},
  "default_length_strategy": "stagger:0",
  "curated": true, "version_sensitive": false,
  "description": "...", "musical_use": "...",
  "parameters": {
    "stagger": {"type": "float", "min": 0.0, "flag": "-s", "flag_kind": "attached_value", "default": 0.0, ...}
  },
  "examples": [...], "known_issues": [], "references": ["cdp://docs/morph/morph"]
}
```

### Schema Enums

- `domain ∈ {"time", "spectral"}`
- `channel_constraint ∈ {"mono", "stereo", "any", "multi"}`
- `stability ∈ {"stable", "unstable", "buggy", "deprecated"}`
- `input_arity ∈ {1, 2, "N", "variable"}`
- `phase_sensitive ∈ {true, false}`
- `stereo_link_default ∈ {"linked", "related", "independent", null}`
- `curated ∈ {true, false}`
- `version_sensitive ∈ {true, false}`
- `default_length_strategy ∈ {"pad_with_fade", "truncate_to_shortest", "stagger:<seconds>", "fail", null}` [Phase 2; null means single-input or N/A]

### Submode at the Entry Level

Curator-pinned; different submodes mean different curated entries. Future-proofs the process-output cache key (when Phase 4 reconsiders Task 12).

### `duration_model` — Discriminated Union

```python
DurationModelStatic(kind="static")
DurationModelSetBy(kind="set_by", param="dur")
DurationModelLinear(kind="linear", param="cnt")        # currently same as set_by (no multiplier in schema yet)
DurationModelExpression(kind="expression", expr="cnt * len / 1000")
```

Evaluator shipped Phase 1b Task 6. `simpleeval` with `functions={}` and `names={}` (v9 tightening). The `linear` discriminator currently behaves identically to `set_by`; comment in source documents this. Phase 3 may grow a `factor_expr` field if a curated entry needs `outdur = factor × param` semantics.

### `flag_kind` — Required (Phase 1b)

`flag_kind: Literal["attached_value", "no_value"] | None`. Enforced by Pydantic model validator: required iff `flag is non-None`.

### `breakpoint_capable` and `breakpoint_duration_source` — Phase 2 wiring

`breakpoint_capable: true` means the parameter accepts breakpoint envelopes. For multi-input ops, an optional `breakpoint_duration_source ∈ {"input1", "input2", "max", "min"}` (default `"input1"`) specifies which input's duration drives relative-time compilation. Single-input ops omit the field.

### `default: null` Semantics

Positional param (`flag is None`), `default: null` → required.
Flag param (`flag is non-None`), `default: null` → omit unless supplied.

### Advisory vs. Enforced Ranges

`min` / `max` enforced (CDP rejects anyway). `musical_range` advisory.

### Strict Knowledge Gating (shipped)

`process()` hard-rejects `curated: false` entries.

## Graph Execution Semantics (Phase 2)

`graph()` creates one graph directory containing multiple nodes. Execution proceeds in five phases:

1. **Validation.** Reference resolution, topological sort, channel-count propagation, sample-rate/domain consistency, parameter range checks, `breakpoint_capable` checks, `duration_model` evaluation against guardrails. Returns structured errors without executing. `dry_run=True` exposes this phase standalone and **returns per-node duration predictions** so the LLM can see which specific node would exceed the cap, not just "somewhere in the graph violates a guardrail."

2. **Time-domain pre-analysis.** For multi-input spectral ops with length mismatches, apply 5 ms cosine micro-fade then pad/truncate per `entry.default_length_strategy` (overridable via `_pvoc.length_strategy`). Uses the `pad_with_fade` primitive (deferred Phase 1b Task 15, ships in Phase 2 with the consuming wiring).

3. **PVOC insertion.** Spectral ops on WAV input get `pvoc anal` upstream; time-domain ops on `.ana` input get `pvoc synth` upstream. Auto-inserted nodes are first-class addressable. Hits the PVOC cache.

4. **Channel resolution.** Mono-only ops on stereo input get `<node>_L`/`<node>_R` sub-graphs. `phase_sensitive` stochastic ops apply the chosen `_stereo_link` mode (hash-salted "related" default). Implementation likely waits for Phase 3 (no `phase_sensitive: true` entries curated yet).

5. **Execution.** Topological order. Each node: cache check (using upstream node's content sha from lineage, not the file path) → input resolution → asyncio subprocess under watchdog → verification → `lineage.json` / `node_index.json` update → status record.

Graph IDs are always new (`<timestamp>-<name>`); re-running creates new directories. Append-only.

**Node ID scoping (Phase 2 commitment).** Within a `graph()` definition, **bare node IDs refer to nodes in the same graph**; **cross-graph references use the full `<graph_id>:nN` form**. Example:

```python
graph(
  inputs={"src": "frog.wav"},
  nodes=[
    {"id": "n1", "op": "blur blur", "in": "src",                "params": {...}},
    {"id": "n2", "op": "modify brassage", "in": "n1",          "params": {...}},   # intra-graph
    {"id": "n3", "op": "morph morph",
                 "in": ["n2", "earlier_graph:n4"],              "params": {...}},   # mixed
  ],
  output="n3"
)
```

Bare `"n1"` inside this graph cannot collide with `"n1"` in another graph because the bare form is always scoped to the current graph. Cross-graph references are always explicit.

**Pre-extraction refactor (Phase 2 precondition).** Before `graph()` itself is written, `process_impl`'s validation + planning steps (everything before subprocess spawn — parameter validation, type checks, range checks, breakpoint compilation, auto-PVOC insertion, duration pre-flight, argv build) get factored into a `validate_node(entry, inputs, params, *, dry_run=False) → (errors, warnings, planned_argv, predicted_duration_s)` helper. Then:

- `process()` calls `validate_node()` then runs the subprocess.
- `graph(dry_run=True)` calls `validate_node()` per-node topologically without running.
- `graph()` (full execution) calls `validate_node()` per-node, runs the subprocess on success.
- `batch()` calls `validate_node()` per-element and short-circuits the whole batch on any validation failure.

Without this extraction, dry-run validation will inevitably diverge from real-run validation as Phase 2 ships and Phase 3 expands curation. The refactor pays itself off four times over.

## Resources

- `cdp://docs/index` / `cdp://docs/<program>` / `cdp://docs/<program>/<mode>` / `cdp://docs/tutorials/<topic>` [Phase 3]
- `cdp://knowledge/<program>/<mode>` [Phase 3 URI; data shape shipped in 1a]
- `cdp://examples/<category>` [Phase 3]

**FTS5 index rebuild trigger (Phase 3).** Index records the CDP version it was built from. On `set_session`, mismatch triggers rebuild before any `search_docs` or `read_doc` call.

## Workflow Patterns

**Targeted design (imperative — Phase 1a/1b's primary loop).** `process` → `visualize`/`analyze` via `"latest"` → next `process` → iterate. Branch using `"prev_1"`, `"prev_2"`, etc.

**Targeted design (declarative — Phase 2).** `graph(dry_run=True)` → `graph()` → inspect.

**Exploratory generation.** Source → `batch` (Phase 2) → `cluster` (Phase 3) → audition representatives via `compare` (Phase 2) → `tag` keepers (Phase 4).

**Library curation at scale.** `cluster()` first, audition medoids with `compare()`, `progression()` the chain of the best medoid, `tag()` winners.

**Performance preparation.** Tag keepers → `export_to_ableton()` → manifest.csv consumed by Ableton MCP.

## Knowledge Sources

1. **CDP official HTML docs** — canonical
2. **CDP8 source on GitHub** — raw usage strings; cross-check against (1) during curation
3. **afta8 `definitions.lua`** — community-curated for ~50 processes
4. **SoundThread's curated process list** — vetted ~100 programs
5. **Session journals** — taste-specific

Treat 1 and 2 as canonical (cross-check), 3-4 as defaults, 5 as preferences. Hand-curation plus listening tests plus empirical measurement is still required for `musical_use`, `musical_range`, `phase_sensitive`, `stereo_link_default`, `duration_model`, `flag_kind`, `breakpoint_capable`, `default_length_strategy`, and examples.

**Dual-source verification.** Phase 3 curation institutionalizes cross-checking CDP HTML against CDP8 source via an import-time script comparing knowledge-entry argv shapes against the source's usage strings.

## Implementation Plan

### Phase 1a (delivered) and Phase 1b (delivered, with deferrals)

`docs/phase-1b-handoff.md` is the canonical record. Summary:

**Phase 1b shipped 11 tasks** (flag_kind required, test-double upgrades, recent_graphs + prev_N, CDP version detection, stderr pattern parsing, duration_model evaluation, disk watchdog + env-var caps, polymorphic params + breakpoint compiler + read_envelope, derivative caches, audition cache, MCP timeout stress test).

**Four tasks dropped/deferred** with reactivation triggers documented in handoff §6:
- Task 9 (auto-pinning): dropped; heuristic failed its purpose; Phase 4 `tag()` is the answer.
- Task 12 (process-output cache): deferred to Phase 4 pending usage data.
- Task 14 (dependency_index.json): deferred to Phase 4 alongside its `cleanup()` consumer.
- Task 15 (pad_with_fade primitive): deferred to Phase 2 alongside multi-input wiring.

### Phase 2: DAG + Observation + Multi-Input

Phase 2 has two structurally independent tracks (DAG/orchestration and Observation) plus a multi-input track that produces a new curated entry. The dependencies between items matter; the doc captures them as prose rather than as a numbered task list (Phase 1b taught us numbered task lists in design docs go stale).

**Precondition — pre-cache-exposure cache key extension.** Before any `_pvoc.window`/`_pvoc.overlap` engine control is exposed to the LLM, the PVOC cache key grows to include them: `sha256(audio_bytes + argv_discriminator + window + overlap + cdp_version)`. Reverse order would mean window changes serve stale `.ana` and the LLM would observe "changing the window had no audible effect" — a silent correctness bug.

**Precondition — `validate_node()` extraction from `process_impl`.** Refactor before `graph()` is written. Reused by `process()`, `graph(dry_run)`, `graph()` (full), and `batch()`. Without it, validation paths diverge.

**Precondition — `breakpoint_capable` curation review.** Same-commit schema review across the five Phase 1a entries, flipping flags where CDP supports envelopes. Without it, the new `breakpoint()` DSL has only `blur_blur.blurring` to target. Approach is identical to Phase 1b's `flag_kind` migration (~10-12 hours of empirical work to verify and flip).

**Precondition — determinism sweep.** Process each of the five Phase 1a entries twice with the same input and params; byte-compare outputs. ~2-3 hours per entry, mechanical. Gates Phase 4's Task 12 reactivation decision (compositional cache is safe only on verified-deterministic entries).

**DAG / orchestration track:**
- `breakpoint()` DSL constructor (pure-additive over the polymorphic param compiler)
- `batch()` over `validate_node()`; single-graph-directory layout; atomic `recent_graphs` event
- `graph(dry_run=True)` per-node validation + per-node duration predictions
- `graph()` full execution (topological order, channel propagation, lineage atomic writes)

**Observation track (can ship independently):**
- `segments()` with onset/novelty/silence methods
- `compare()` with three loudness methods + crest-factor warning
- `progression()` with PIL composite, fixed panel width, 8-panel cap + summary panel
- Verbose `analyze()` mode (per-frame matrices, MFCCs, chroma, BPM with confidence, per-channel)

**Multi-input track:**
- `pad_with_fade` primitive (Task 15 reactivation)
- Multi-input PVOC alignment wiring per `_pvoc.length_strategy`
- New curated entry: `combine cross` (clean 2-input spectral op — single mode, breakpoint-capable `interp` parameter with `breakpoint_duration_source: "input1"`, mono-only, static duration). Curating it as part of Phase 2 — not deferring to Phase 3 — is how we know the wiring actually works.
- Cross-graph multi-input cwd-relative argv test under a dotted session name

**Stereo seed-linking (likely defers to Phase 3).** Three-mode `_stereo_link` is committed in the schema and engine namespace, but the actual L/R-split + hash-salted seeding can't be exercised without a `phase_sensitive: true` curated entry — and none of the Phase 1a or planned-for-Phase-2 entries are. When Phase 3 curates a stochastic stereo program (likely candidates: `blur scatter`, `distmore`, programs in CDP8's `texture/` or `grain/`), the channel handling wires up.

**Operational fixes during Phase 2:**
- Linux test portability: `_install_real_pvoc_wrapper` shebang from `#!/bin/sh` to `#!/usr/bin/env bash`. Production code is fine; this is a test-fixture-only fix that unblocks cross-platform CI.
- `.ana` duration for pre-converted files: **shipped via `sfprops -d`** (cached in `session/tmp/`, never raises; graceful skip + reactive watchdog on failure). Investigation outcome: v9 named `dirsf`, but verification against r8 found `dirsf` is a directory-listing utility and `pvoc info` doesn't exist (modes are anal/synth/extract); `sfprops -d <path>` writes exactly one float to stdout and is the right tool. This beat writing a custom binary parser for CDP's `.ana` header format.

### Phase 3: Knowledge Completion

Scoped to **~30 programs initially** (frog/IDM workflow + most common CDP operations), expanding to ~100 in Phase 5.

- Port afta8 `definitions.lua` to schema (~8 hours)
- Hand-curate ~30 programs with full metadata (`musical_use`, `musical_range`, `phase_sensitive`, `stereo_link_default`, `duration_model`, `flag_kind`, `breakpoint_capable`, `default_length_strategy`, examples) — ~40-50 hours
- Dual-source verification script (CDP HTML cross-checked against CDP8 source argv shapes) — ~10 hours
- Mono-sum listening tests for `phase_sensitive: true` programs to validate `stereo_link_default` — ~5 hours
- Empirical duration measurements for `duration_model` (especially `expression` cases requiring actual measurement) — ~20 hours
- Auto-generated minimal entries for uncurated long tail (`curated: false`)
- CDP docs FTS5 index build pipeline + version-mismatch rebuild trigger
- `cluster()` with default PCA + hierarchical; optional UMAP path
- `why()` provenance tool
- `write_data_file(path, content)` workspace tool if curating programs that need it (`tesselate`, etc.)
- **Channel handling and stereo seed-linking wiring** — exercises against the first `phase_sensitive: true` curated entry
- **Appendix extraction.** Move CDP forensic findings and test infrastructure principles from `docs/phase-1b-handoff.md` §5 + §4 into permanent `docs/forensics.md` and `docs/testing-principles.md`.

### Phase 4: Curation Polish

- `tag()`, `journal()`, `set_config()`
- `save_graph()` / `load_graph()` / `list_graphs()`
- `cleanup()` with predicate grammar — **build alongside the deferred dependency_index.json (Task 14)**
- `cleanup_cache()` with predicate grammar
- **Reconsider process-output cache (Task 12 reactivation)** with usage data from Phase 1b–3 and the determinism sweep results from Phase 2
- Reproducibility verification: regenerate-from-lineage round-trip test
- Bundled prompt templates
- `export_to_ableton()` with confidence-gated manifest

### Phase 5: Generalization + Documentation

- Examples library with curated chains
- Curation expansion from ~30 to ~100 programs
- Generalization testing: clarinet multisample, field recording, synth one-shot, vocal phrase
- Documentation

## Open Questions

Substantially reduced after Phase 1b and the Phase 2 preconditions above. Remaining:

- **MCP image-per-turn limits.** Empirical; surfaces when `compare` and `progression` introduce composite PNGs.
- **Ableton MCP manifest consumption.** Confirm with the `ahujasid/ableton-mcp` maintainer; the manifest format we're producing may need negotiation.
- **Apple Silicon arch wrapping unexercised in CI.** All Phase 1b runs have been on developer machines. A CI matrix on intel macOS would surface any auto-detection regression.
- **Determinism of Phase 1a entries beyond PVOC.** PVOC anal/synth verified. `blur blur`, `modify brassage`, `extend loop`, `filter sweeping`, `morph morph` are presumed deterministic but not byte-compared. Phase 2 sweeps these.
- **Cross-session library beyond cache.** `~/.cdp_mcp/library/` reserved.

### Architectural decisions revised by Phase 1b and Phase 2 prep

- **Matplotlib backend forcing** lives at the top of `visualization.py` (module-level, before any pyplot import), not at the top of `server.py`. Strictly safer than v7's prescription.
- **Auto-pinning for `available_sources`** was rejected. The 5-slot deque + Phase 4's explicit `tag()` is the answer.
- **Process-output cache** (v7's Phase 1b P0) was deferred to Phase 4 pending usage data.
- **Dependency index** (v7's Phase 1b P1) was deferred to Phase 4 to build alongside its `cleanup()` consumer.
- **`pad_with_fade` primitive** (v7's Phase 1b P1) was deferred to Phase 2 alongside its multi-input alignment consumer.
- **`simpleeval` configuration** tightened from `functions={}` to `functions={} + names={}` so default builtins (`int`, `float`, `abs`, `min`, `max`) are not silently accessible.
- **Channel handling wiring** likely defers to Phase 3 because Phase 1a/2 entries are all mono-or-any; building the L/R-split machinery without a `phase_sensitive: true` entry to exercise is speculative.
- **PVOC cache key** grows to include `window` and `overlap` in Phase 2 — before `_pvoc.*` engine controls are exposed to the LLM.

### Phase 2 mid-course reverts (2026-05-28; rationale recorded 2026-07-13)

Two implemented Phase 2 tasks were deliberately reverted the same afternoon `combine cross` landed. The commits carry no rationale; recording it here so neither gets re-litigated from scratch.

- **Task 04 — PVOC cache-key extension (window/overlap)** — implemented in `3a7000e`, reverted in `c804a03`. The `_pvoc.window`/`_pvoc.overlap` engine controls did not ship in this pass, so the extended key had no consumer while invalidating every existing PVOC cache entry. The v9 ordering constraint is *unbroken* (neither key nor controls shipped) and still applies: re-land the key extension (revert the revert) **before** exposing `_pvoc.*`.
- **Task 07 — `pad_with_fade` primitive (`audio_align.py`)** — implemented in `896d868`, reverted in `fb8fda6`. `combine cross` (Task 09) turned out to need no length alignment — CDP natively truncates to the shorter input, order-independent — leaving the primitive consumer-less, exactly the pattern "rough end-to-end first" exists to catch. Re-land alongside the first curated entry that actually exercises `_pvoc.length_strategy` (`morph morph` sidesteps it via its own `-s` stagger flag; its former `default_length_strategy: "stagger:0"` declaration was removed as dead data, see the entry's `known_issues`).

### Decided (still decided)

The Phase 1b implementation confirmed the v7 architectural commitments that weren't on the revised-above list:

- Derivative cache global, compositional cache session-local
- Hash-salted stereo seed-linking (additive offsets phase-cancel under LCG-style PRNGs)
- Submode in process-output cache key (when Phase 4 reconsiders Task 12)
- `flag_kind` required, not defaulted
- Stress test acceptance: `60_000ms < duration_ms < 180_000ms` regression threshold
- `usage_banner_returned` exit-code-agnostic trigger
- `recent_graphs` durability: per-process, no persistence, no backfill, prune-on-cleanup without renumbering
- `prev_N` stability: stable for the lifetime of the pointed-at graph
- Cache-hit materialization: hardlink on POSIX, copy on Windows
- Session-level JSON state files use `.tmp` + `os.replace` atomic-write contract
- Cwd-relative argv paths inside session root; absolute outside
- Pre-delete-then-write contract for CDP outputs in re-invocation paths
- Apple Silicon: auto-wrap `arch -x86_64` on arm64 Darwin
- `run_with_progress` for sync CPU work in async tools
- Async-escalation fallback: server-internal polling, LLM-visible tool surface stays sync
- All forensic findings in handoff §5 (stock CDP r8 has no `cdp` binary; CDP r8 emits errors to stdout; PVOC byte-deterministic; PVOC scales nonlinearly; macOS ReportCrash forces SIGTERM in test fakes; etc.)

## Non-Goals

- A GUI. Claude is the user-facing surface.
- A general DAW. Ableton handles arrangement via its own MCP.
- Real-time processing.
- A replacement for SoundThread / Soundloom / direct CDP.
- A music theory or compositional engine.
- Audio similarity search (`find_similar`).
- Parameter sweep automation as a dedicated tool (`batch` + `process` covers it).
- Aggregated `inspect()` observation tool — `visualize` / `analyze` / `segments` / `compare` stay distinct.
- Cross-session intelligence beyond the derivative cache.
- `LatestTracker` persistence across server restarts (alias state is conversational, not historical).
- `MPLBACKEND` env var as the matplotlib backend mechanism (must be programmatic, in `visualization.py`).
- Auto-pinning heuristic for `available_sources` (rejected in Phase 1b; tagging is the durable answer).
- Detailed numbered Phase 2 task lists with acceptance criteria embedded in this doc — those are a phase-planning artifact, not a design-doc artifact. Phase 1b's experience confirmed numbered task lists go stale; the Phase 2 plan above captures *dependencies* in prose.

## Stack Summary

- **Language:** Python 3.10+
- **MCP framework:** FastMCP (official MCP Python SDK ≥ 1.2)
- **Schema validation:** pydantic ≥ 2.0 (with model validators for required-conditional fields)
- **Subprocess:** `asyncio.create_subprocess_exec`
- **Audio I/O:** soundfile ≥ 0.12, numpy ≥ 1.24
- **MIR:** librosa ≥ 0.10 (prefer soundfile backend; `LIBROSA_AUDIO_BACKEND=soundfile` for explicit selection), pyloudnorm ≥ 0.1
- **Expression evaluation:** `simpleeval` ≥ 0.9 (configured with `functions={}` and `names={}`)
- **Clustering (Phase 3):** scikit-learn (default PCA + hierarchical); `umap-learn` optional
- **Visualization:** matplotlib ≥ 3.7 (Agg backend, programmatically forced at top of `visualization.py`), Pillow ≥ 10.0 (PIL-stitched composites)
- **Search (Phase 3):** SQLite FTS5
- **Dev:** pytest ≥ 7.0 (with `pytest-asyncio`, `pytest-timeout`); ruff ≥ 0.5
- **External:** CDP binaries via `$CDP_PATH`; sessions root via `$CDP_MCP_SESSIONS_ROOT`; resource caps via `CDP_MCP_OUTPUT_SIZE_CAP_BYTES` and `CDP_MCP_DURATION_CAP_S`

## References

### Foundation
- **DavidPiazza/CDP_MCP** — structural inspiration; not a code fork. https://github.com/DavidPiazza/CDP_MCP

### Design Inspiration (other MCPs)
- **8beeeaaat/touchdesigner-mcp** — https://github.com/8beeeaaat/touchdesigner-mcp
- **ahujasid/ableton-mcp** — community-maintained downstream integration point. https://github.com/ahujasid/ableton-mcp
- **ersatzben/maxmsp-mcp** — https://github.com/ersatzben/maxmsp-mcp
- **tiianhk/MaxMSP-MCP-Server** — https://github.com/tiianhk/MaxMSP-MCP-Server

### Related CDP Tooling
- **j-p-higgins/SoundThread** — https://github.com/j-p-higgins/SoundThread
- **afta8 CDP Renoise Lua Tool** — https://forum.renoise.com/t/new-tool-3-0-cdp-lua-tool/41466

### CDP Itself
- **Composers' Desktop Project** — https://www.composersdesktop.com/
- **ComposersDesktop/CDP8** — open-source CDP (LGPL). https://github.com/ComposersDesktop/CDP8

### Protocol & Framework
- **Model Context Protocol** — https://modelcontextprotocol.io/
- **MCP Python SDK** — https://github.com/modelcontextprotocol/python-sdk

### Audio Analysis Libraries
- **librosa** — https://librosa.org/
- **pyloudnorm** — https://github.com/csteinmetz1/pyloudnorm
- **scikit-learn** — https://scikit-learn.org/
- **simpleeval** — https://pypi.org/project/simpleeval/

### Project Documents
- **Phase 1b Handoff** — `docs/phase-1b-handoff.md`. Canonical Phase 1b record: shipped, deferred, forensic findings, test infrastructure principles, development/operations guide.

## License

Inherits MIT from the project's structural foundation. CDP itself is LGPL. Knowledge ported from afta8 is MIT; knowledge ported from SoundThread is MIT.
