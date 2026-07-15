# cdp-mcp

An MCP (Model Context Protocol) server that wraps the [Composers' Desktop Project](https://www.composersdesktop.com/) (CDP) suite, exposing it as a set of tools an LLM can call for sound transformation, analysis, and visualization.

> **Status:** Phase 4 complete (Ableton export deferred). 31 tools + 3 workflow prompts; **43 curated programs** (every parameter range, duration model, and breakpoint capability empirically verified against real CDP binaries) plus 194 auto-generated uncurated stubs surfacing the long tail. DAG orchestration (`graph`, `batch`), a full observation suite (spectrograms, MIR scorecards, segmentation, comparison, progression, clustering), FTS5 search over CDP's manual, per-output provenance, and derivative caches throughout. Phase handoffs live in `docs/`.

## What this does

Wraps CDP — a 500+ program suite for offline sound transformation — as MCP tools an LLM can call in collaboration with a human composer. The knowledge layer curates the musically vital core of CDP (spectral blurring/morphing/stretching, waveset distortion, granular time-stretch, scrambling and gesture extension, filtering, texture generation) with hand-written musical guidance and machine-verified engineering metadata. Auto-inserts PVOC analysis/synthesis when input and program domains don't match, so the LLM never thinks about `.ana` vs `.wav`. Every action returns structured errors with fixes, full lineage lands on disk, and an `execute()` escape hatch covers the uncurated long tail behind a security boundary.

## Phase history

- **Phase 1a/1b** — core loop (`process` → `visualize`/`analyze`), five curated programs, derivative caches (15×–1231× speedups), pre-flight duration prediction + reactive disk watchdog, structured error taxonomy, polymorphic breakpoint parameters, `latest`/`prev_N` conversational aliases. Record: `docs/phase-1b-handoff.md`.
- **Phase 2** — DAG orchestration: `graph()` (whole-DAG validation with chained per-node duration predictions, then topological execution into one graph directory) and `batch()` (N inputs, one atomic context event, `latest_batch[i]` addressing); the observation track (`segments`, `compare`, `progression`, verbose `analyze`); the `breakpoint()` envelope DSL; multi-input processing; a hardening pass (cancellation-safe subprocesses, security-gate fixes, event-loop hygiene). Record: `docs/phase-2-handoff.md`.
- **Phase 3** — knowledge completion: 6 → 43 curated entries via an empirical pipeline against CDP built from source (`scripts/build_cdp8_linux.sh`); four-source curation hierarchy (*binaries decide, source explains, manual describes, SoundThread + afta8 prioritize*); `search_docs`/`read_doc` (FTS5 over the CDP manual), `why()` provenance, `cluster()`, `write_data_file()` + `aux_file` parameters (texture programs); long-tail stub generator. Findings — including several CDP bugs the docs don't know about — in `docs/forensics.md` and `docs/curation/`. Record: `docs/phase-3-handoff.md`.
- **Phase 4** — workflow polish: `sweep()` (one source × N param variants — a reversed design-doc non-goal, driven by usage evidence), `tag`/`journal`/`set_config`/`list_session_files`, dependency-safe `cleanup()` + `cleanup_cache()` (dry-run default), graph templates (`save_graph`/`load_graph`/`list_graphs`), a lineage→regenerate reproducibility test, and three MCP workflow prompts. `export_to_ableton` and the process-output cache are deferred with recorded rationale.

## Installation

Clone the repo and install in editable mode into a Python 3.10+ environment:

```bash
git clone https://github.com/<you>/cdp-mcp.git
cd cdp-mcp
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Or with [`uv`](https://docs.astral.sh/uv/) (recommended):

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Configuring `CDP_PATH`

The server needs to know where your CDP binaries live. Set `CDP_PATH` to the directory containing programs like `housekeep`, `blur`, `modify`, `pvoc`, etc.

```bash
export CDP_PATH=/cdpr8/_cdp/_cdprogs
```

No CDP install? On Linux, `scripts/build_cdp8_linux.sh` builds ~211 binaries from the open-source [CDP8 release](https://github.com/ComposersDesktop/CDP8) in one command.

## Use with Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cdp": {
      "command": "cdp-mcp",
      "env": { "CDP_PATH": "/path/to/cdpr8/_cdp/_cdprogs" }
    }
  }
}
```

Restart Claude Desktop. In a new conversation, the `cdp` server should appear in the MCP server list with no error icon. Ask Claude to call `list_categories()` and you should get back the categorized list of curated CDP programs.

## Quick start

In a Claude conversation with the MCP server connected:

> Set up a CDP MCP session called `my_first_session`.

Claude calls `set_session("my_first_session")`. The server creates `~/cdp_sessions/my_first_session/` with `inputs/`, `graphs/`, `tmp/`, and a few other subdirectories.

Drop a `.wav` file into `~/cdp_sessions/my_first_session/inputs/`, then:

> Blur the spectral content of frog.wav with a blurring factor of 10, then show me a spectrogram.

Claude calls `process("blur", "blur", input="frog.wav", params={"blurring": 10})` — the server auto-inserts a `pvoc anal` step because blur is spectral and the input is a wav — followed by `visualize("latest")`. The spectrogram comes back inline in the chat, and the rendered PNG is on disk under `<session>/visualizations/`.

From here the workflows compose:

- **Iterate:** chain further `process()` calls via `"latest"` / `prev_N`, with time-varying parameters built by `breakpoint()` (named shapes or custom point lists).
- **Orchestrate:** describe a whole chain declaratively with `graph(dry_run=True)` — per-node duration predictions before anything runs — then execute it.
- **Explore:** `batch()` one program across many inputs or `sweep()` one input across many parameter settings, `cluster()` the results, audition one medoid per cluster with `compare()`, and view a chain's evolution with `progression()`.
- **Understand:** `segments()` finds onsets/silences to feed edit points; `why()` reconstructs any output's full provenance; `search_docs()`/`read_doc()` consult CDP's own manual.
- **Keep:** `tag()` the winners, `journal()` the taste notes, `save_graph()` a chain you liked as a reusable template, `cleanup()` the rest (dependency-safe, dry-run by default).

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CDP_PATH` | (required) | Path to the CDP binaries directory. |
| `CDP_MCP_SESSIONS_ROOT` | `~/cdp_sessions` | Where session directories live. |
| `CDP_MCP_DOCS_ROOT` | (auto-derived) | CDP HTML manual location for `search_docs` (found by walking up from `CDP_PATH`). |
| `CDP_MCP_DISABLE_ARCH_X86_64` | (off) | Set to `1` on Apple Silicon if your CDP is a native arm64 build. |
| `CDP_MCP_DURATION_CAP_S` | `300.0` | Predicted output duration cap, seconds. `process()` pre-flight rejects calls above this. |
| `CDP_MCP_OUTPUT_SIZE_CAP_BYTES` | `1073741824` (1 GB) | Output file size cap. Reactive disk watchdog SIGKILLs the subprocess on crossing. |

Invalid values (non-numeric, non-positive) fall back to defaults with a warning on stderr.

## Tools

31 tools across six groups:

| Group | Tools |
|-------|-------|
| Introspection | `list_categories`, `list_programs`, `get_program_info`, `search_docs`, `read_doc` |
| Workspace | `set_session`, `describe_workspace` (incl. full graph `history`), `read_envelope`, `write_data_file`, `set_config`, `list_session_files` |
| Action | `process` (curated, PVOC auto-insert, lineage), `execute` (gated escape hatch), `graph` (declarative DAG w/ dry-run), `batch` (N inputs × one process), `sweep` (one input × N param variants), `breakpoint` (envelope DSL) |
| Observation | `visualize`, `analyze` (+`verbose`), `segments`, `compare`, `progression`, `cluster` |
| Curation | `tag`, `journal`, `cleanup` (dependency-safe, dry-run default), `cleanup_cache`, `save_graph`/`load_graph`/`list_graphs` |
| Provenance | `why` |

Every action returns a `ResultEnvelope` with structured errors (each carrying `fix` text) and a context block (`latest`, `recent_graphs`, `available_sources`) so the LLM stays grounded across turns.

## Development

```bash
pytest                    # hermetic: fake-CDP doubles, no CDP needed
ruff check src tests
```

With real CDP, the CDP-gated layer executes too — curation formula rows, breakpoint-capability probes, and the acceptance chains:

```bash
CDP_PATH=/path/to/cdpr8/_cdp/_cdprogs pytest        # zero gated skips
```

On Linux, `scripts/build_cdp8_linux.sh` provides the binaries for this; the curated knowledge layer was verified against exactly this build, then re-verified on macOS r8.

### Curation

Adding a program to the knowledge layer is an empirical process, not transcription — CDP's banners and manual both contain errors (see `docs/forensics.md` for the catalogue). The pipeline: `scripts/curation_harness.py` inventories banners; probes against real binaries pin ranges, duration models, breakpoint capability, and determinism; `docs/curation/` holds per-tranche transcripts and machine-readable findings; pinned tables in `tests/test_breakpoint_curation.py` and `tests/test_curation_formulas.py` fail on any drift. Priors come from SoundThread's `process_help.json` and afta8's 888 Renoise definitions (`scripts/parse_afta8_definitions.py`).

### Slow tests (MCP keepalive stress test)

Tests marked `@pytest.mark.slow` are excluded from the default cycle. `pytest -m slow tests/test_stress.py` exercises the keepalive mechanism (~80–120 s). To run everything: `pytest -m ''`.

### Apple Silicon

CDP binaries are x86-only. The server auto-wraps subprocesses with `arch -x86_64` on arm64 macOS. Disable with `CDP_MCP_DISABLE_ARCH_X86_64=1` (needed for tests where the test subprocess runs a system Python that isn't a fat binary).

### Symlinks in `$CDP_PATH`

The security boundary's binary check resolves symlinks before verifying location. A symlinked binary in `$CDP_PATH` must point at a target that is itself inside `$CDP_PATH`.

## Acknowledgements

Inspired by [DavidPiazza/CDP_MCP](https://github.com/DavidPiazza/CDP_MCP) and [j-p-higgins/SoundThread](https://github.com/j-p-higgins/SoundThread); curation priors from SoundThread's process help data and [afta8's CDP Interface](https://www.renoise.com/tools/cdp-interface) for Renoise (definitions by afta8 and Djeroek). CDP itself is open source: [ComposersDesktop/CDP8](https://github.com/ComposersDesktop/CDP8) (LGPL) — thanks to Trevor Wishart and everyone at CDP. This project adopts a few conventions from these tools (the `CDP_PATH` environment variable, array-form invocation) but derives no code from them.
