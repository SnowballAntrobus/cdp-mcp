# cdp-mcp

An MCP (Model Context Protocol) server that wraps the [Composers' Desktop Project](https://www.composersdesktop.com/) (CDP) suite, exposing it as a set of tools an LLM can call for sound transformation, analysis, and visualization.

> **Status:** Phase 1b complete. Production-quality on the Phase 1a tool surface — same nine tools, same five curated programs, now with derivative caches (PVOC / analysis / visualizations / audition), pre-flight duration prediction, reactive disk watchdog, structured stderr error parsing, polymorphic-parameter breakpoint compilation, `recent_graphs` deque with `prev_N` aliases, and an MCP keepalive regression gate.

## What this does

Wraps CDP — a 500+ program suite for offline sound transformation — as MCP tools an LLM can call. Phase 1a curates five programs (`blur blur`, `modify brassage`, `morph morph`, `extend loop`, `filter sweeping`) plus the `pvoc` analysis/synthesis pair they depend on, along with observation tools that render mel spectrograms and extract MIR scorecards. Auto-inserts the PVOC conversion step when input and program domains don't match, so the LLM never has to think about `.ana` vs `.wav` files explicitly. An `execute()` escape hatch covers anything uncurated, behind a security boundary that rejects shell metacharacters and out-of-session file paths.

## What's new in Phase 1b

Phase 1b made the Phase 1a tool surface production-quality without adding new tools. Key changes:

- **Derivative caches** under `~/.cdp_mcp/cache/` give 15× to 1231× speedups on repeat operations across PVOC, MIR analysis, and spectrogram rendering. Audition synth cache makes parameter variation against the same spectral target ~7.5× faster.
- **Pre-flight duration prediction** rejects calls whose `duration_model` predicts output exceeding the 300-second cap before CDP spawns. Complemented by a reactive disk watchdog that SIGKILLs the subprocess on output-size overruns (configurable via env vars).
- **Structured error taxonomy** with action-oriented `fix` text on every entry. Four stderr patterns (`output_exists`, `channel_mismatch`, `usage_banner_returned`, `silent_output`) coexist with the existing generic errors.
- **`recent_graphs` deque** (length 5) with `prev_1`..`prev_4` aliases for branching conversational workflows. Per-process, not persisted.
- **Polymorphic parameters**: scalars, relative-time tuple lists, absolute-time tuple lists (`"abs:"` prefix), or pre-existing `.brk` file paths. Defensive compilation with sort + dedupe + auto-append. Content-addressable breakpoint files.
- **CDP version detection** via path-component regex (stock CDP r8 has no `cdp` binary). Mismatch warning on session reload.
- **Test infrastructure**: fault-injection in `fake_subprocess.py` (`--cdp-refuse-clobber`, `--cdp-die-on-dot-path`, `--cdp-silent-output`, `--cdp-grow-file`). Apple Silicon arch-wrapping autouse fixture. MCP keepalive stress test (slow-marked).

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

From here you can chain further: `modify brassage` for time-stretching, `extend loop` for looping, etc. The `"latest"` reference always points at the most recent successful output, so you can iterate naturally without naming each intermediate.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CDP_PATH` | (required) | Path to the CDP binaries directory. |
| `CDP_MCP_SESSIONS_ROOT` | `~/cdp_sessions` | Where session directories live. |
| `CDP_MCP_DISABLE_ARCH_X86_64` | (off) | Set to `1` on Apple Silicon if your CDP is a native arm64 build. |
| `CDP_MCP_DURATION_CAP_S` | `300.0` | Predicted output duration cap, seconds. `process()` pre-flight rejects calls above this. |
| `CDP_MCP_OUTPUT_SIZE_CAP_BYTES` | `1073741824` (1 GB) | Output file size cap. Reactive disk watchdog SIGKILLs the subprocess on crossing. |

Invalid values (non-numeric, non-positive) fall back to defaults with a warning on stderr.

## Manual smoke test (without Claude Desktop)

```bash
# With CDP_PATH unset: server prints a warning to stderr but starts cleanly.
cdp-mcp < /dev/null

# With CDP_PATH set: server prints the detected version and binaries.
CDP_PATH=/path/to/cdp/_cdprogs cdp-mcp < /dev/null
```

In both cases, the process exits cleanly when stdin closes.

## Tools

Nine tools ship in Phase 1a:

| Tool | Purpose |
|------|---------|
| `list_categories`, `list_programs`, `get_program_info` | Introspection over the curated CDP knowledge layer |
| `set_session`, `describe_workspace` | Session and workspace management |
| `execute` | Raw CDP escape hatch with security boundary (binary location, shell metacharacters, file path scope) |
| `process` | Curated CDP invocation with PVOC auto-insertion, parameter validation, and graph lineage |
| `visualize` | Mel-spectrogram PNG returned inline plus on disk |
| `analyze` | Concise MIR scorecard (duration, peak, RMS, LUFS, spectral centroid, spectral flux, ZCR, onset count, channels, sample rate) |

## Development

```bash
pytest
ruff check src tests
```

### Acceptance test

`tests/test_acceptance.py` runs the full frog chain (`process("blur","blur") → visualize → analyze → process("modify","brassage") → process("extend","loop") → visualize → analyze → cross-graph visualize`) end-to-end against real CDP under a dotted session name (`frog_acceptance_v1.0`). It's skipped when `$CDP_PATH` isn't set or doesn't contain `blur`, `pvoc`, `modify`, `extend`. To run it:

```bash
CDP_PATH=/path/to/cdpr8/_cdp/_cdprogs pytest tests/test_acceptance.py -v
```

The per-tool tests in `test_execute.py`, `test_process.py`, `test_visualize.py`, `test_analyze.py` use a fake-CDP wrapper (`tests/fixtures/fake_subprocess.py`) and cover orchestration concerns exhaustively without needing CDP installed.

### Slow tests (MCP keepalive stress test)

Tests marked `@pytest.mark.slow` are excluded from the default `pytest` cycle (configured in `pyproject.toml`). They take 80–120 seconds. To run:

```bash
pytest -m slow tests/test_stress.py
```

`tests/test_stress.py` exercises the MCP keepalive mechanism: a subprocess sleeps for 80 s while emitting periodic stderr, and the test asserts that `ctx.report_progress` fired multiple times during the run. Without those notifications Claude Desktop would close the connection at ~60 s. The test uses `tests/fixtures/fake_subprocess.py` rather than real CDP for deterministic duration across machines — see the test's module docstring for the rationale.

To run every test including slow ones: `pytest -m ''`.

### Apple Silicon

CDP binaries are x86-only. The server auto-wraps subprocesses with `arch -x86_64` on arm64 macOS. Disable with `CDP_MCP_DISABLE_ARCH_X86_64=1` (needed for tests where the test subprocess runs a system Python that isn't a fat binary).

### Symlinks in `$CDP_PATH`

The security boundary's binary check resolves symlinks before verifying location. A symlinked binary in `$CDP_PATH` must point at a target that is itself inside `$CDP_PATH`. Well-behaved CDP installs follow this convention.

## Acknowledgements

Inspired by [DavidPiazza/CDP_MCP](https://github.com/DavidPiazza/CDP_MCP) and [j-p-higgins/SoundThread](https://github.com/j-p-higgins/SoundThread). This project adopts a couple of their conventions (the `CDP_PATH` environment variable, array-form command invocation) but does not derive any code from them.
