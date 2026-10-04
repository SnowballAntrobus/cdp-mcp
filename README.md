# cdp-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an LLM use the [Composers' Desktop Project](https://www.composersdesktop.com/) (CDP), a suite of more than 500 command-line programs for offline sound transformation.

Can a model that cannot hear do real sound design? The models driving this server are text-only, so everything they learn about a sound comes through its observation tools: spectrograms, feature scorecards, segmentation, comparisons and provenance. This server was the harness for that question. The project is complete and archived.

The loop is **find a program → process the audio → observe the result → refine**. There are 348 curated program modes, each with musical guidance on when to use it. Their parameter ranges, output-duration rules and breakpoint support were measured against real CDP binaries. The server converts between audio and spectral files automatically and records how every output was made. When a call goes wrong, it returns structured errors with suggested fixes. [How the server works](docs/how-it-works.md) has the details.

## Contents

- `src/cdp_mcp/`: the server. `server.py` registers the 33 tools and 4 prompts, and `tools/` holds the tool modules. The other modules check, run and record CDP commands, cache derived files and analyze audio.
- `src/cdp_mcp/knowledge/`: the curated entries, stubs for uncurated programs, and six verified example chains.
- `tests/`: a suite that fakes CDP, plus tests that run when real CDP binaries are available.
- `scripts/build_cdp8_linux.sh`: builds the CDP binaries from source on Linux.
- `docs/`: [how the server works](docs/how-it-works.md) and the [CDP quirks](docs/cdp-quirks.md) found during curation.

## Setup

Clone the repository and install the locked dependencies with [uv](https://docs.astral.sh/uv/):

```sh
uv sync --extra dev
```

The server needs CDP binaries. On Linux, build them from the CDP8 source the entries were verified against. Elsewhere, point `CDP_PATH` at a CDP release.

```sh
scripts/build_cdp8_linux.sh ~/CDP8
export CDP_PATH=~/CDP8/NewRelease
```

To use the server from Claude Desktop, add it to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cdp": {
      "command": "/path/to/cdp-mcp/.venv/bin/cdp-mcp",
      "env": { "CDP_PATH": "/path/to/CDP8/NewRelease" }
    }
  }
}
```

In a conversation, ask Claude to start a session called `first`. That creates `~/cdp_sessions/first/`. Copy a `.wav` file into its `inputs/` directory and ask for something like "blur the spectrum of frog.wav, then show me a spectrogram." The remaining settings are listed under [configuration](docs/how-it-works.md#configuration).

## Tests

```sh
uv run --extra dev pytest                               # fakes CDP; no binaries needed
CDP_PATH=~/CDP8/NewRelease uv run --extra dev pytest    # adds the tests that need real CDP
uv run --extra dev pytest -m slow                       # 80-second MCP keepalive test
uv run --extra dev ruff check src tests
```

The development notes are gone from the working tree but kept in the git history at commit `7d967b9`. They include the phase plans, session handoffs, the original design document and the per-program curation transcripts.

## Acknowledgements

Inspired by [DavidPiazza/CDP_MCP](https://github.com/DavidPiazza/CDP_MCP) and [SoundThread](https://github.com/j-p-higgins/SoundThread). Curation started from SoundThread's process help data and [afta8's CDP Interface](https://www.renoise.com/tools/cdp-interface) for Renoise, with definitions by afta8 and Djeroek. No code is taken from these projects. CDP itself is open source as [CDP8](https://github.com/ComposersDesktop/CDP8); thanks to Trevor Wishart and everyone at CDP.
