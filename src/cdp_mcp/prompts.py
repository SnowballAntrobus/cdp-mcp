"""MCP prompt templates — workflow recipes for common CDP sessions.

Three ``@mcp.prompt()`` templates (FastMCP renders a returned string as
a single user message). Each is a short, ordered recipe over REAL tool
names — the design doc's canonical workflows ("Exploratory generation",
"Library curation at scale") turned into prompts the client can invoke
with arguments. They tell the model *which tools in which order*, not
what to think; observations (analyze / compare / cluster) stay the
ground truth at every step.

Registered via :func:`register`, mirroring the tools modules' pattern
(closure-free — prompts have no server-state dependencies).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register the prompt templates against ``mcp``."""

    @mcp.prompt(title="Explore new material")
    def explore_material(input_file: str, session: str = "exploration") -> str:
        """Guided first contact with a sound: analyze, segment, sweep one
        parameter, cluster the results, and audition the medoids."""
        return f"""\
Explore the sound material {input_file!r} with the CDP tools, step by step:

1. set_session({session!r}), then describe_workspace() to confirm
   {input_file!r} is in the session inputs (tell me if it isn't).
2. analyze({input_file!r}) for the feature scorecard, and
   segments({input_file!r}, method="onset") to see its event structure.
   Summarize what kind of material this is in one or two sentences.
3. Pick ONE curated transformation suited to that character
   (list_programs() / get_program_info() to choose), then sweep a single
   parameter across 4-6 values with batch() — same input, varied params.
4. cluster() the batch outputs (latest_batch refs) and compare() the
   cluster medoids pairwise to hear how the parameter reshapes the sound.
5. Report: which settings are worth keeping, referenced as
   <graph_id>:<node_id>, with one line of evidence from the
   analyze/compare deltas for each."""

    @mcp.prompt(title="Build a texture")
    def build_texture(
        source: str, character: str = "a soft, sustained spectral wash"
    ) -> str:
        """Design a multi-node blur/texture chain, validate it with
        graph(dry_run=True), execute, and verify against the brief."""
        return f"""\
Build {character} from {source!r} using a multi-node CDP chain:

1. Check the source: analyze({source!r}) — note duration, brightness,
   and dynamics, since they constrain the chain design.
2. Choose 2-4 curated ops for the chain (blur blur is the classic
   starting point for washes; see get_program_info() for its parameter
   ranges, and search_docs() if you want alternatives like stretch or
   texture-family ops).
3. Declare the chain as ONE graph() call — inputs={{"src": {source!r}}},
   nodes wired by bare-name references — and run it with dry_run=True
   first. Fix any per-node errors or duration-cap warnings it reports.
4. Execute the same graph() without dry_run, then visualize() and
   analyze() the output node. compare({source!r}, "latest") to confirm
   the transformation actually moved toward the brief.
5. If it's a keeper, save_graph("<short_name>") so the chain can be
   replayed on other material with load_graph(); report the graph_id,
   the output reference, and what you'd adjust for a second pass."""

    @mcp.prompt(title="Review provenance")
    def review_provenance(target: str = "latest") -> str:
        """Reconstruct how an output was made: lineage chain, visual
        progression, and a reproducibility check."""
        return f"""\
Review the provenance of {target!r}:

1. why({target!r}) for the full lineage chain — every hop from this
   output back to its source audio, with argv, params, and hashes.
2. progression() over the chain's graph (pass the graph_id from step 1)
   to see the transformation as stacked spectrograms.
3. Walk me through it hop by hop: program + mode, the params that
   mattered, cache hits, and cumulative duration changes. Flag anything
   suspicious (missing lineage, sources outside the session).
4. Finish with: (a) whether the chain is worth templating via
   save_graph() and (b) which single parameter you'd vary — with
   breakpoint() automation if it's breakpoint-capable — to develop the
   result further."""
