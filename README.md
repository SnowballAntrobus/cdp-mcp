# cdp-mcp

An MCP (Model Context Protocol) server that wraps the [Composers' Desktop Project](https://www.composersdesktop.com/) (CDP) suite, exposing it as a set of tools an LLM can call for sound transformation, analysis, and visualization.

> **Status:** Phase 1a complete. Nine tools, curated subset of five CDP programs, real CDP integration verified end-to-end via an automated acceptance test.

## What this does

Wraps CDP — a 500+ program suite for offline sound transformation — as MCP tools an LLM can call. Phase 1a curates five programs (`blur blur`, `modify brassage`, `morph morph`, `extend loop`, `filter sweeping`) plus the `pvoc` analysis/synthesis pair they depend on, along with observation tools that render mel spectrograms and extract MIR scorecards. Auto-inserts the PVOC conversion step when input and program domains don't match, so the LLM never has to think about `.ana` vs `.wav` files explicitly. An `execute()` escape hatch covers anything uncurated, behind a security boundary that rejects shell metacharacters and out-of-session file paths.

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

### Apple Silicon

CDP binaries are x86-only. The server auto-wraps subprocesses with `arch -x86_64` on arm64 macOS. Disable with `CDP_MCP_DISABLE_ARCH_X86_64=1` (needed for tests where the test subprocess runs a system Python that isn't a fat binary).

### Symlinks in `$CDP_PATH`

The security boundary's binary check resolves symlinks before verifying location. A symlinked binary in `$CDP_PATH` must point at a target that is itself inside `$CDP_PATH`. Well-behaved CDP installs follow this convention.

## Acknowledgements

Inspired by [DavidPiazza/CDP_MCP](https://github.com/DavidPiazza/CDP_MCP) and [j-p-higgins/SoundThread](https://github.com/j-p-higgins/SoundThread). This project adopts a couple of their conventions (the `CDP_PATH` environment variable, array-form command invocation) but does not derive any code from them.
