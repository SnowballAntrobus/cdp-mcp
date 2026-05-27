"""Pydantic models used across cdp-mcp.

This module defines two related families of models:

1. **Knowledge-layer models** — ``ParameterSpec``, ``Example``, ``DurationModel``
   (a discriminated union), and ``KnowledgeEntry``. These describe what
   cdp-mcp knows about a single curated CDP ``(program, mode)`` combination
   and back the introspection tools (``list_categories``, ``list_programs``,
   ``get_program_info``).

2. **Result-envelope models** — ``ErrorEntry``, ``RecentGraphEntry``,
   ``ContextBlock``, and ``ResultEnvelope``. These describe what an execution
   tool returns. Defined here in Phase 1a; first consumed in Task 4+.

All logging of validation failures happens at the loader boundary; the models
themselves only raise ``pydantic.ValidationError`` and let the loader decide
what to do.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Knowledge-layer models
# ---------------------------------------------------------------------------


class ParameterSpec(BaseModel):
    """Describes one CDP parameter.

    ``flag`` carries the CLI prefix exactly as it appears in the CDP usage
    string (e.g. ``"-l"``, ``"-w"``). ``None`` means the parameter is
    positional. The dict key in :class:`KnowledgeEntry.parameters` is the
    human-readable parameter name (e.g. ``"step"``), not the flag.

    ``flag_kind`` distinguishes CDP's two flag styles: ``"attached_value"``
    for the common ``-X<value>`` style (e.g. ``-s0.5``), ``"no_value"`` for
    value-less switches (e.g. ``-b``). Required whenever ``flag`` is
    non-None — enforced by a model validator so curator omissions fail at
    load time rather than producing malformed CDP argv.

    ``musical_range`` is advisory only — it documents the values that
    typically produce musically useful results, and is *not* enforced at
    validation time. Phase 1a leaves it unset on every entry; curated in
    Phase 3.

    ``breakpoint_capable`` is set to ``False`` everywhere in Phase 1a;
    breakpoint compilation lands in Phase 1b.
    """

    type: Literal["float", "int", "str", "bool"]
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    breakpoint_capable: bool = False
    default: float | int | str | bool | None = None
    musical_range: tuple[float, float] | None = None
    description: str | None = None
    flag: str | None = None
    flag_kind: Literal["attached_value", "no_value"] | None = None

    @model_validator(mode="after")
    def _flag_kind_matches_flag(self) -> ParameterSpec:
        if self.flag is None and self.flag_kind is not None:
            raise ValueError(
                "flag_kind is set but flag is None — flag_kind only "
                "applies to parameters with a CLI flag."
            )
        if self.flag is not None and self.flag_kind is None:
            raise ValueError(
                f"Parameter with flag={self.flag!r} must declare flag_kind "
                "(\"attached_value\" or \"no_value\")."
            )
        return self


class Example(BaseModel):
    """A worked usage example for a knowledge entry."""

    description: str
    params: dict[str, Any]
    expected_use: str | None = None


# ---------------------------------------------------------------------------
# DurationModel — discriminated union
# ---------------------------------------------------------------------------


class DurationModelStatic(BaseModel):
    """Output duration matches the input duration (in-place transformation)."""

    kind: Literal["static"]


class DurationModelSetBy(BaseModel):
    """A single parameter directly sets the output duration in seconds."""

    kind: Literal["set_by"]
    param: str


class DurationModelLinear(BaseModel):
    """Output duration is a linear function of the named parameter.

    For example, ``extend loop`` mode 3's ``cnt`` (loop repeat count) is a
    linear duration model: ``outdur ≈ cnt * loop_segment_duration``.
    """

    kind: Literal["linear"]
    param: str


class DurationModelExpression(BaseModel):
    """Free-form expression for duration models that don't fit the simpler kinds.

    **Expression vocabulary** (fixed convention so future curation doesn't drift):

    - ``indur`` — input duration in seconds (single-input case).
    - Any name appearing in the entry's ``parameters`` dict — value of that
      parameter at call time.
    - Multi-input cases use ``indur1``, ``indur2``, etc. (not needed for any
      Phase 1a entry).

    Phase 1a records the expression as an opaque string only; the evaluator
    lands in Phase 1b alongside breakpoint compilation. Example for
    ``modify brassage`` mode 2 (TIMESTRETCH)::

        DurationModelExpression(kind="expression", expr="indur / velocity")
    """

    kind: Literal["expression"]
    expr: str


DurationModel = Annotated[
    DurationModelStatic | DurationModelSetBy | DurationModelLinear | DurationModelExpression,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# KnowledgeEntry
# ---------------------------------------------------------------------------


class KnowledgeEntry(BaseModel):
    """One curated CDP ``(program, mode)`` combination.

    ``submode`` carries a curator-pinned sub-mode integer (e.g. ``2`` for
    ``modify brassage`` TIMESTRETCH). It is **not** a user-tunable parameter —
    changing it would mean using a different curated entry entirely
    (``modify brassage`` mode 2's ``velocity`` does not mean the same thing
    as mode 4's). For this reason it lives at the entry level, not inside
    ``parameters``. ``None`` is correct for programs that have no sub-mode
    dimension (e.g. ``blur blur``, ``morph morph``).
    """

    program: str
    mode: str
    submode: int | None = None
    category: str
    domain: Literal["time", "spectral"]
    input_arity: int | Literal["N", "variable"]
    channel_constraint: Literal["mono", "stereo", "any", "multi"]
    input_format: str
    output_format: str
    stability: Literal["stable", "unstable", "buggy", "deprecated"] = "stable"
    phase_sensitive: bool = False
    stereo_link_default: Literal["linked", "related", "independent"] | None = None
    duration_model: DurationModel
    curated: bool = True
    version_sensitive: bool = False
    description: str
    musical_use: str
    parameters: dict[str, ParameterSpec]
    examples: list[Example] = Field(default_factory=list)
    known_issues: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Result-envelope models (consumed Task 4+)
# ---------------------------------------------------------------------------


class ErrorEntry(BaseModel):
    type: str
    message: str
    fix: str | None = None


class RecentGraphEntry(BaseModel):
    id: str
    output_node: str
    alias: str


class ContextBlock(BaseModel):
    active_graph: str | None = None
    latest: str | None = None
    recent_graphs: list[RecentGraphEntry] = Field(default_factory=list)
    available_sources: list[str] = Field(default_factory=list)


class ResultEnvelope(BaseModel):
    status: Literal["ok", "failed", "partial_success"]
    output: str | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    errors: list[ErrorEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    cached: bool = False
    duration_ms: int | None = None
    context: ContextBlock = Field(default_factory=ContextBlock)


# ---------------------------------------------------------------------------
# Lineage and output verification (consumed Task 5+)
# ---------------------------------------------------------------------------


class InputRecord(BaseModel):
    """Provenance for one input file to a node.

    The sha256 is captured at execution time so later ``why()``-style tools
    (Phase 1b) can confirm a downstream output really did come from the
    input it claims to.

    ``source_node`` is set when this input came from an upstream node in the
    same graph — most commonly an auto-inserted PVOC node. It's ``None``
    when the input was resolved from outside the graph (session inputs,
    cross-graph references, absolute paths).
    """

    path: str  # absolute path on disk
    sha256: str  # sha256 hex of the file contents at execution time
    source_node: str | None = None  # upstream node id in the same graph, if any


class CompiledBreakpoint(BaseModel):
    """Record of a compiled breakpoint file used by one node.

    Captured in :class:`NodeLineage.compiled_breakpoints` so cache-key
    construction (Task 12) can incorporate the .brk content sha, and so
    the provenance trail shows which audio duration the relative-time
    list was compiled against.

    ``source_kind`` distinguishes:

    - ``"input_wav"`` — duration came from the main op's .wav input
      directly via ``soundfile.info()``.
    - ``"pvoc_lineage"`` — duration came from an auto-PVOC node in the
      same graph (chained .wav → .ana → main op case).
    - ``"preexisting_brk"`` — user supplied an existing .brk file by
      path. No compilation happened; ``source_duration_s`` is ``None``.
    """

    path: str  # absolute path to the .brk file
    sha256: str  # content hash of the .brk file
    source_duration_s: float | None  # None when path mode (not compiled)
    source_kind: Literal["input_wav", "pvoc_lineage", "preexisting_brk"]


class NodeLineage(BaseModel):
    """Per-node provenance record.

    Written into a graph's ``lineage.json`` under ``nodes[node_id]``. Every
    field is filled in by the engine; nothing is user-supplied at this level.
    The ``params`` field is a snapshot of the user's parameter dict, included
    for human-readable debugging and for cache-key derivation in Phase 1b.
    """

    argv: list[str]  # exact subprocess argv after arch-prefix wrapping
    inputs: list[InputRecord]
    output_path: str  # absolute path on disk
    output_sha256: str | None  # None if output verification failed pre-hashing
    params: dict[str, Any]  # snapshot of the user's parameter dict
    cdp_version: str  # captured from the active session's config
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    exit_code: int | None  # None if the subprocess timed out
    # Task 8 additions — both defaulted for backward compat with
    # pre-Phase-1b lineage JSON files.
    source_wav_duration_s: float | None = None
    compiled_breakpoints: dict[str, CompiledBreakpoint] = Field(
        default_factory=dict,
    )


class OutputVerification(BaseModel):
    """Result of :func:`cdp_mcp.graph.verify_output`.

    Never raised — failures are encoded in ``ok=False`` plus human-readable
    ``errors`` strings. ``rms_dbfs`` is intentionally ``float | None`` rather
    than allowing ``-inf``; JSON forbids non-finite floats and the engine
    returns this struct over the wire to callers.
    """

    ok: bool
    exists: bool
    size_bytes: int
    rms_dbfs: float | None  # None if non-wav, unreadable, or silent (rms=0)
    errors: list[str] = Field(default_factory=list)
