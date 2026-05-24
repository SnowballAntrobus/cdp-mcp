# cdp-mcp

An MCP (Model Context Protocol) server that wraps the [Composers' Desktop Project](https://www.composersdesktop.com/) (CDP) suite, exposing it as a set of tools an LLM can call for sound transformation, analysis, and visualization.

> **Status:** Phase 1a — rough end-to-end, not production. See the design doc for the full plan. Currently only the FastMCP scaffold and a stub `list_categories` tool are implemented.

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

Restart Claude Desktop. In a new conversation, the `cdp` server should appear in the MCP server list with no error icon. Ask Claude to call `list_categories()` and you should get back the stub list of CDP categories.

## Manual smoke test (without Claude Desktop)

```bash
# With CDP_PATH unset: server prints a warning to stderr but starts cleanly.
cdp-mcp < /dev/null

# With CDP_PATH set: server prints the detected version and binaries.
CDP_PATH=/path/to/cdp/_cdprogs cdp-mcp < /dev/null
```

In both cases, the process exits cleanly when stdin closes.

## Development

```bash
pytest
ruff check src tests
```

## Acknowledgements

Inspired by [DavidPiazza/CDP_MCP](https://github.com/DavidPiazza/CDP_MCP) and [j-p-higgins/SoundThread](https://github.com/j-p-higgins/SoundThread). This project adopts a couple of their conventions (the `CDP_PATH` environment variable, array-form command invocation) but does not derive any code from them.
