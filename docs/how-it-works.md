# How the server works

The server exposes CDP as 34 MCP tools and 4 prompts. Most of the work happens in one place: running a curated CDP program safely, with every input, parameter and output recorded.

## A `process()` call

`process(program, mode, input, params)` runs one curated program through these steps:

1. **Look up the entry** for `(program, mode, submode)`. Programs without a curated entry are refused; `execute()` runs those instead.
2. **Resolve inputs.** A plain filename refers to the session's `inputs/` directory. `latest` and `prev_1`–`prev_4` name recent outputs, `latest_batch[i]` names one output of the last `batch()`, and `<graph_id>:<node_id>` names any earlier node. Every input must stay inside the session.
3. **Check parameters** against the entry's types and ranges, then predict the output duration from the entry's duration rule. A call predicted to exceed the duration cap is refused before CDP starts.
4. **Convert domains.** CDP's spectral programs read `.ana` analysis files and its time-domain programs read `.wav`. When an input is in the wrong domain, the server inserts `pvoc anal` or `pvoc synth` as its own node.
5. **Compile breakpoints.** A time-varying parameter given as `[[time, value], ...]` becomes a `.brk` file in `envelopes/`. Times are fractions of the input's duration, or seconds when written `"abs:1.5"`. `breakpoint()` builds these lists from named shapes.
6. **Check and run the command.** The binary must be inside `CDP_PATH`, no argument may contain shell metacharacters, and every path must be inside the session or the cache. While CDP runs, progress notifications keep the MCP client from timing out, and a watchdog kills the process if its output grows past the size cap.
7. **Verify and record.** The output must exist, and audio must not be silent. The argv, input and output hashes, and timings of every node go into `lineage.json` in a new graph directory, and `latest` moves to the new output.

The action and observation tools return a result envelope: a status, the output path, any `errors` as `{type, message, fix}`, and a `context` block naming the current `latest` and recent graphs. CDP prints many of its errors to stdout rather than stderr, so the server searches both for known CDP messages and turns them into specific error types with a suggested fix.

The other action tools reuse the same steps. `graph()` runs a whole DAG of nodes, and with `dry_run=True` it validates everything and predicts each node's duration without running anything. `batch()` runs one program over many inputs, `sweep()` runs one input through many parameter settings, and `timeline()` places several sources at set times and mixes them with `submix mix`. CDP's mixer wraps around on overload instead of clipping, so by default `timeline()` first measures the mix with `submix getlevel` and attenuates it when needed. `execute()` runs any CDP command after the same command checks, without lineage or output verification.

## Sessions and files

`set_session(name)` creates `~/cdp_sessions/<name>/` with `inputs/`, `graphs/`, `templates/`, `envelopes/` and `tmp/`, plus `config.json`, `tags.json` and `journal.md`. Each run of an action tool writes a new directory under `graphs/` holding its outputs, `node_index.json` and `lineage.json`. Spectrograms go to `visualizations/`, and files written by `write_data_file()` (texture note data, mixfiles) go to `data/`.

`latest` and `prev_N` are conversational state. They live in memory and reset when the server restarts or a session is activated. Everything else is on disk, and `why(output)` rebuilds an output's history from the lineage files.

PVOC conversions, analysis scorecards and spectrograms depend only on their inputs and software versions, so they are cached in `~/.cdp_mcp/cache/` and shared between sessions. `cleanup()` deletes graph directories while protecting anything tagged or still referenced, and `cleanup_cache()` evicts cache files. Both are dry runs by default.

## Observation

The model never hears the audio, so these tools are how it judges a result. Spectral files are resynthesized automatically before any of them run.

- `visualize` renders a mel spectrogram and returns it as an image.
- `analyze` returns a 13-field scorecard (duration, peak, RMS, LUFS, crest factor, spectral centroid, flatness, rolloff, flux, zero-crossing rate, onset count, channels, sample rate). `verbose=True` adds MFCC and chroma statistics, tempo, per-channel levels, a 16-point trajectory, inharmonicity, roughness, attack sharpness, stereo width and pitch estimates.
- `segments` finds onsets and silences and reports rhythm statistics such as inter-onset intervals, density and accelerando.
- `compare` stacks the spectrograms of two sounds after matching their loudness, and `progression` stacks the spectrograms of a chain's steps.
- `cluster` groups many variants by timbre, so only one per group needs reviewing.

## Knowledge entries

Each file in `src/cdp_mcp/knowledge/data/` describes one program mode. It gives the parameters (CLI flag, type, range, default, and whether a breakpoint file is accepted), the input and output formats, the channel constraint and the output-duration rule. It also has a description, musical guidance, examples and known issues. `get_program_info` returns the whole entry, and `search_programs` searches the entries by musical intent.

The engineering fields were measured against CDP8 binaries built by `scripts/build_cdp8_linux.sh`, not copied from CDP's manual or usage banners, which often disagree with the binaries ([CDP quirks](cdp-quirks.md)). `tests/test_curation_formulas.py` and `tests/test_breakpoint_curation.py` pin the measured ranges, duration rules and breakpoint support, so any drift fails when the tests run against real CDP.

`data_uncurated/` holds 99 stubs generated from usage banners for programs left uncurated: mostly multichannel and spatial tools, file utilities, and programs dropped because of defects. They make those programs discoverable through `list_programs(curated_only=False)` and point the model to `execute()`. `examples/` holds six chain recipes, served as `cdp://examples/*`, each of which was run against real CDP.

## Tools

| Group | Tools |
|---|---|
| Find | `list_categories`, `list_programs`, `get_program_info`, `search_programs`, `search_docs`, `read_doc`, `list_examples` |
| Run | `process`, `graph`, `batch`, `sweep`, `timeline`, `breakpoint`, `write_data_file`, `execute` |
| Observe | `visualize`, `analyze`, `segments`, `compare`, `progression`, `cluster`, `why` |
| Session | `set_session`, `describe_workspace`, `read_envelope`, `set_config`, `list_session_files`, `tag`, `journal`, `cleanup`, `cleanup_cache`, `save_graph`, `load_graph`, `list_graphs` |

The prompts `explore_material`, `build_texture`, `review_provenance` and `recommend_transforms` walk the model through common workflows.

`search_docs` searches CDP's HTML manual and `read_doc` reads its pages as well as the example recipes. The manual ships with CDP releases rather than the CDP8 source, and the server looks for it by walking up from `CDP_PATH`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CDP_PATH` | required | Directory containing the CDP binaries. |
| `CDP_MCP_SESSIONS_ROOT` | `~/cdp_sessions` | Where session directories live. |
| `CDP_MCP_DOCS_ROOT` | found from `CDP_PATH` | Location of CDP's HTML manual. |
| `CDP_MCP_DURATION_CAP_S` | `300` | Longest predicted output, in seconds, that `process()` will run. |
| `CDP_MCP_OUTPUT_SIZE_CAP_BYTES` | `1073741824` | Output size at which the watchdog kills a run. |
| `CDP_MCP_DISABLE_ARCH_X86_64` | off | On Apple Silicon the server runs CDP under `arch -x86_64`; set to `1` for native arm64 binaries. |

A symlinked binary in `CDP_PATH` must point to a file that is also inside `CDP_PATH`.
