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

    ``breakpoint_capable`` was empirically verified per parameter against
    the CDP r8 binary in the Phase 2 curation review (see
    ``docs/phase-2-breakpoint-review.md``); outcomes are pinned in
    ``tests/test_breakpoint_curation.py``, which fails on any drift
    between the JSONs and the verified table.

    ``type: "aux_file"`` (Phase 3) marks a parameter whose value is a
    string path to an existing auxiliary data file — e.g. ``texture``'s
    notedata slot, produced by the ``write_data_file`` tool into
    ``<session>/data/``. Usually a text file, but binary CDP data files
    are equally valid (``formants put``'s ``.for`` slot — Phase 5 wave
    2a). Any extension except ``.brk`` is accepted (``.brk`` is
    reserved for the breakpoint compiler's routing).
    ``validate_params`` checks the type only; existence + resolution
    against the session happen in ``node_validation`` (step 8.7), which
    replaces the value with a resolved :class:`~pathlib.Path` so
    ``build_cdp_argv`` renders it cwd-relative like other paths.

    ``position: "pre_output"`` (Phase 5 wave 2a) marks a positional
    ``aux_file`` parameter whose argv slot sits BETWEEN the inputs and
    the output path — CDP's ``submix mix <mixfile> <outfile>`` and
    ``formants put 1 <infile> <fmntfile> <outfile>`` layouts.
    ``build_cdp_argv`` renders ``pre_output`` params (in entry
    declaration order) before the output slot; all other params render
    after it as before. Only meaningful on positional (``flag is
    None``) ``aux_file`` params — enforced by a model validator, since
    a flagged or non-file param "before the output" has no CDP meaning
    and would silently corrupt the argv.
    """

    type: Literal["float", "int", "str", "bool", "aux_file"]
    position: Literal["pre_output"] | None = None
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    breakpoint_capable: bool = False
    # Phase 2 Task 5. Multi-input entries (input_arity > 1) need to say which
    # input's duration defines the breakpoint envelope's relative-time axis.
    # ``"input1"`` / ``"input2"`` pick a specific input; ``"max"`` / ``"min"``
    # take the longer / shorter of the inputs. Must be None on single-input
    # entries; required when ``breakpoint_capable=True`` on a multi-input
    # entry. Enforced by a ``KnowledgeEntry``-level validator.
    breakpoint_duration_source: Literal["input1", "input2", "max", "min"] | None = None
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

    @model_validator(mode="after")
    def _position_requires_positional_aux_file(self) -> ParameterSpec:
        """``position: "pre_output"`` is only meaningful for positional
        ``aux_file`` params (Phase 5 wave 2a) — the pre-output argv slot
        is where CDP programs like ``submix mix`` / ``formants put``
        expect their data file, and nothing else belongs there."""
        if self.position is None:
            return self
        if self.type != "aux_file":
            raise ValueError(
                f"position={self.position!r} requires type 'aux_file' "
                f"(got {self.type!r}) — only auxiliary data files occupy "
                "the pre-output argv slot."
            )
        if self.flag is not None:
            raise ValueError(
                f"position={self.position!r} requires a positional "
                f"parameter (flag is None), got flag={self.flag!r} — "
                "flagged params always render after the output path."
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

# Data (non-audio) output formats a curated entry may declare (Phase 5
# wave 2a, unblocking envel extract / formants get). Empirically pinned
# against the r8 binaries:
#
# - ``.evl`` — envel extract mode 1's binary envelope file. CDP dresses
#   it as a RIFF/WAVE (FLOAT subtype, sample rate 57 for a 2 s input at
#   wsize 20) and writes it verbatim under ANY name, so an entry that
#   named it ``.wav`` would mint a pseudo-wav that PASSES audio
#   verification and poisons downstream consumers.
# - ``.for`` — formants get's binary formant data file (also a RIFF
#   container; a get output named ``.ana`` misreports 107.85 s via
#   ``sfprops -d`` from a 2 s source).
# - ``.txt`` — text data outputs (envel extract mode 2's brkfile form;
#   no curated consumer yet, reserved so the namer/verifier logic
#   doesn't need reopening when one lands).
#
# Consumers: the output namer (node_validation step 9) uses the entry's
# declared data format instead of the domain-derived audio extension;
# verify_output checks exists + non-empty only (no wav RMS/silence
# decode); the duration pre-flight skips (data files have no audio
# duration); and the PVOC domain gate already refuses them as inputs
# (unknown_input_domain), so nothing feeds them to sfprops or the
# audition synth.
DATA_OUTPUT_FORMATS = frozenset({".evl", ".for", ".txt"})


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
    # ``input_arity: 0`` (Phase 5 wave 2a) marks a generator / data-driven
    # entry with NO audio inputs (synth noise/wave; submix mix, whose
    # sources live inside its mixfile). validate_node accepts an empty
    # inputs list, the duration pre-flight evaluates with no indurs
    # (duration typically ``set_by`` a dur param), and lineage records an
    # empty inputs list. graph()/batch()/sweep() exclude arity-0 entries
    # with a structured ``arity_zero_unsupported`` error — their spec
    # shapes are input-wiring by construction (see those modules).
    input_arity: int | Literal["N", "variable"]
    channel_constraint: Literal["mono", "stereo", "any", "multi"]
    input_format: str
    # ``.wav`` / ``.ana`` are the audio formats (extension actually
    # derived from ``domain`` at output-naming time, as before).
    # ``.evl`` / ``.for`` / ``.txt`` are data formats — see
    # DATA_OUTPUT_FORMATS above for the exact semantics they switch on.
    output_format: Literal[".wav", ".ana", ".evl", ".for", ".txt"]
    stability: Literal["stable", "unstable", "buggy", "deprecated"] = "stable"
    phase_sensitive: bool = False
    stereo_link_default: Literal["linked", "related", "independent"] | None = None
    duration_model: DurationModel
    # Phase 2 Task 5. How the engine should align multi-input durations when
    # no per-call override is supplied. Accepted values:
    #
    # - ``"pad_with_fade"`` — pad shorter inputs with silence + fade-in/out
    #   so they match the longest. Default for most multi-input combiners.
    # - ``"truncate_to_shortest"`` — truncate all inputs to the shortest.
    # - ``"fail"`` — refuse to run when input lengths differ; surface a
    #   structured error.
    # - ``"stagger:<float>"`` — for programs that have their own offset
    #   mechanism (e.g. ``morph morph``'s ``-s`` flag); the float is the
    #   default offset in seconds.
    # - ``None`` — no strategy (default behavior; appropriate for
    #   single-input entries).
    #
    # Enforced format by a model_validator below; engine wiring is Task 8.
    default_length_strategy: str | None = None
    curated: bool = True
    version_sensitive: bool = False
    description: str
    musical_use: str
    parameters: dict[str, ParameterSpec]
    examples: list[Example] = Field(default_factory=list)
    known_issues: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _breakpoint_duration_source_consistent(self) -> KnowledgeEntry:
        """Per Phase 2 Task 5, ``breakpoint_duration_source`` is only
        meaningful on multi-input entries, and is required whenever a
        multi-input entry has a breakpoint-capable parameter."""
        multi = isinstance(self.input_arity, int) and self.input_arity > 1
        for name, spec in self.parameters.items():
            if spec.breakpoint_duration_source is not None and not multi:
                raise ValueError(
                    f"Parameter {name!r}: breakpoint_duration_source is "
                    f"only meaningful for multi-input entries "
                    f"(input_arity > 1)."
                )
            if multi and spec.breakpoint_capable and spec.breakpoint_duration_source is None:
                raise ValueError(
                    f"Parameter {name!r}: breakpoint_capable on a "
                    f"multi-input entry requires breakpoint_duration_source."
                )
        return self

    @model_validator(mode="after")
    def _default_length_strategy_format(self) -> KnowledgeEntry:
        """Phase 2 Task 5: validate the ``default_length_strategy``
        string shape. Accepted: ``"pad_with_fade"``,
        ``"truncate_to_shortest"``, ``"fail"``, ``"stagger:<float>"``,
        or ``None``."""
        s = self.default_length_strategy
        if s is None:
            return self
        if s in {"pad_with_fade", "truncate_to_shortest", "fail"}:
            return self
        if s.startswith("stagger:"):
            try:
                float(s.removeprefix("stagger:"))
                return self
            except ValueError:
                pass
        raise ValueError(
            f"default_length_strategy {s!r} must be one of: 'pad_with_fade', "
            f"'truncate_to_shortest', 'fail', or 'stagger:<float>'."
        )


# ---------------------------------------------------------------------------
# Result-envelope models (consumed Task 4+)
# ---------------------------------------------------------------------------


class ErrorEntry(BaseModel):
    type: str
    message: str
    fix: str | None = None


class RecentGraphEntry(BaseModel):
    """One slot of the conversational ``recent_graphs`` deque.

    ``output_node`` is ``None`` for a ``batch()`` entry — batch is an
    atomic context event (one deque slot for N outputs; design-doc
    Context Block rule 6) whose elements are addressed via
    ``latest_batch[i]``, with ``batch_size`` carrying N."""

    id: str
    output_node: str | None
    alias: str
    batch_size: int | None = None


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
    - ``"ana_sfprops"`` — duration came from shelling out to CDP's
      ``sfprops -d`` on a .ana whose source wav isn't reachable in the
      current graph (pre-converted .ana in inputs/, or cross-graph
      reference). Phase 2 Task 2.
    - ``"preexisting_brk"`` — user supplied an existing .brk file by
      path. No compilation happened; ``source_duration_s`` is ``None``.
    - ``"set_by_param"`` — arity-0 (generator) entry: there is no input
      audio, so the envelope axis is the OUTPUT duration, taken from
      the entry's ``set_by`` duration-model parameter (e.g. ``synth
      wave``'s ``dur``). Phase 5 wave 2a.
    - ``"dry_run_override"`` / ``"dry_run_dummy"`` — Task 11a
      ``graph(dry_run=True)`` records only: duration came from a
      caller-supplied upstream prediction, or was unknowable and a
      placeholder axis was used for structural validation. Never
      written to ``lineage.json`` (dry-run compiles are discarded).
    """

    path: str  # absolute path to the .brk file
    sha256: str  # content hash of the .brk file
    source_duration_s: float | None  # None when path mode (not compiled)
    source_kind: Literal[
        "input_wav", "pvoc_lineage", "ana_sfprops", "preexisting_brk",
        "set_by_param", "dry_run_override", "dry_run_dummy",
    ]


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
    # Task 10: True when this node's output was served from the global
    # derivative cache instead of being freshly computed. Defaulted so
    # pre-Task-10 lineage JSON files parse unchanged.
    cache_hit: bool = False


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
