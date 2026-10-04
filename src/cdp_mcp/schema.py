"""Pydantic models used across cdp-mcp.

This module defines two related families of models:

1. **Knowledge-layer models** — ``ParameterSpec``, ``Example``, ``DurationModel``
   (a discriminated union), and ``KnowledgeEntry``. These describe what
   cdp-mcp knows about a single curated CDP ``(program, mode)`` combination
   and back the introspection tools (``list_categories``, ``list_programs``,
   ``get_program_info``).

2. **Result-envelope models** — ``ErrorEntry``, ``RecentGraphEntry``,
   ``ContextBlock``, and ``ResultEnvelope``. These describe what an execution
   tool returns.

All logging of validation failures happens at the loader boundary; the models
themselves only raise ``pydantic.ValidationError`` and let the loader decide
what to do.
"""

from __future__ import annotations

import re
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
    validation time.

    ``breakpoint_capable`` is empirically verified per parameter against
    the CDP r8 binary; outcomes are pinned in
    ``tests/test_breakpoint_curation.py``, which fails on any drift
    between the JSONs and the verified table.

    ``type: "aux_file"`` marks a parameter whose value is a string path
    to an existing auxiliary data file — e.g. ``texture``'s notedata
    slot, produced by the ``write_data_file`` tool into
    ``<session>/data/``. Usually a text file, but binary CDP data files
    are equally valid (``formants put``'s ``.for`` slot). Any extension
    except ``.brk`` is accepted (``.brk`` is reserved for the breakpoint
    compiler's routing). ``validate_params`` checks the type only;
    existence + resolution against the session happen in
    ``node_validation`` (step 8.7), which replaces the value with a
    resolved :class:`~pathlib.Path` so ``build_cdp_argv`` renders it
    cwd-relative like other paths.

    ``position: "pre_output"`` marks a positional ``aux_file`` parameter
    whose argv slot sits BETWEEN the inputs and the output path — CDP's
    ``submix mix <mixfile> <outfile>`` and ``formants put 1 <infile>
    <fmntfile> <outfile>`` layouts. ``build_cdp_argv`` renders
    ``pre_output`` params (in entry declaration order) before the output
    slot; all other params render after it. Only meaningful on
    positional (``flag is None``) ``aux_file`` params — enforced by a
    model validator, since a flagged or non-file param "before the
    output" has no CDP meaning and would silently corrupt the argv.

    ``type: "free_string"`` marks a parameter whose value is a plain
    string parsed straight from argv by CDP — NOT a file path. The
    motivating shape is the ``shuffle`` domain-image map (``"ab-abab"``,
    ``cdp2k/tklib3.c:646 read_shuffle_data``), a REQUIRED positional
    with no file fallback, which the ``str`` type cannot express (the
    engine rejects caller-supplied strings for ``str`` params — they
    exist only to pin curated side-file default names, e.g. ``repitch
    getpitch``'s ``pitchdata``). ``free_string`` values pass
    ``validate_params`` as strings, optionally gated by ``pattern`` (a
    ``re.fullmatch`` regex), and render verbatim into the argv.
    ``.brk``-suffixed values are refused at type-check time so the
    breakpoint compiler's string routing can never intercept one.

    ``pattern`` is only meaningful on ``free_string`` params and must
    compile — both enforced by a model validator so a bad curated
    regex fails at load time, not mid-``process()``.
    """

    type: Literal["float", "int", "str", "bool", "aux_file", "free_string"]
    position: Literal["pre_output"] | None = None
    pattern: str | None = None
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

    @model_validator(mode="after")
    def _position_requires_positional_aux_file(self) -> ParameterSpec:
        """``position: "pre_output"`` is only meaningful for positional
        ``aux_file`` params — the pre-output argv slot is where CDP
        programs like ``submix mix`` / ``formants put`` expect their data
        file, and nothing else belongs there."""
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

    @model_validator(mode="after")
    def _pattern_requires_free_string(self) -> ParameterSpec:
        """``pattern`` gates ``free_string`` values only. A pattern on any
        other type would silently never run; a non-compiling pattern
        would crash validate_params at call time. Both are curator
        errors caught at load."""
        if self.pattern is None:
            return self
        if self.type != "free_string":
            raise ValueError(
                f"pattern={self.pattern!r} requires type 'free_string' "
                f"(got {self.type!r}) — validation regexes only apply "
                "to free-string parameters."
            )
        try:
            re.compile(self.pattern)
        except re.error as e:
            raise ValueError(
                f"pattern {self.pattern!r} is not a valid regex: {e}"
            ) from e
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


class DurationModelExpression(BaseModel):
    """Free-form expression for duration models that don't fit the simpler kinds.

    Evaluated arithmetic-only (``simpleeval``, no function calls) by
    :mod:`cdp_mcp.duration_preflight`. **Expression vocabulary**:

    - ``indur`` — input duration in seconds (single-input case).
    - ``indur1``, ``indur2``, etc. — per-input durations.
    - ``indur_min`` / ``indur_max`` — shortest / longest input duration.
    - Any name appearing in the entry's ``parameters`` dict — value of that
      parameter at call time (its curated numeric default if not passed).

    Example for ``modify brassage`` mode 2 (TIMESTRETCH)::

        DurationModelExpression(kind="expression", expr="indur / velocity")
    """

    kind: Literal["expression"]
    expr: str


DurationModel = Annotated[
    DurationModelStatic | DurationModelSetBy | DurationModelExpression,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# KnowledgeEntry
# ---------------------------------------------------------------------------

# Data (non-audio) output formats a curated entry may declare. Empirically
# pinned against the r8 binaries:
#
# - ``.evl`` — envel extract mode 1's binary envelope file. CDP dresses
#   it as a RIFF/WAVE (FLOAT subtype, sample rate 57 for a 2 s input at
#   wsize 20) and writes it verbatim under ANY name, so an entry that
#   named it ``.wav`` would mint a pseudo-wav that PASSES audio
#   verification and poisons downstream consumers.
# - ``.for`` — formants get's binary formant data file (also a RIFF
#   container; a get output named ``.ana`` misreports 107.85 s via
#   ``sfprops -d`` from a 2 s source).
# - ``.txt`` — text data outputs (e.g. envel envtobrk's breakpoint list).
# - ``.frq`` / ``.trn`` — CDP's binary pitch-data and transposition-data
#   files (the repitch transform layer). Both are RIFF containers: fmt
#   FLOAT mono with "sample rate" = the analysis window rate (344 for
#   44.1 kHz / 1024-point / overlap-3), LIST adtl note properties ``is a
#   pitch file`` / ``is a transpos file``, one float32 per analysis
#   window (Hz values with -1/-2 markers for .frq, ratios for .trn).
#   Exactly the .evl poison shape: soundfile happily "decodes" them as
#   344 Hz pseudo-wavs, so they must never reach the audio verifier or
#   the duration probe.
#
# Consumers: the output namer (node_validation step 9) uses the entry's
# declared data format instead of the domain-derived audio extension;
# verify_output checks exists + non-empty only (no wav RMS/silence
# decode); the duration pre-flight skips (data files have no audio
# duration); and the PVOC domain gate already refuses them as inputs
# (unknown_input_domain), so nothing feeds them to sfprops or the
# audition synth. Entries CONSUMING .frq/.trn take them through
# ``aux_file`` params (pre_output slots, e.g. repitch combineb 1 /
# transposef 4), never as engine-resolved audio inputs.
DATA_OUTPUT_FORMATS = frozenset({".evl", ".for", ".txt", ".frq", ".trn"})


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
    # ``input_arity: 0`` marks a generator / data-driven entry with NO
    # audio inputs (synth noise/wave; submix mix, whose sources live
    # inside its mixfile). validate_node accepts an empty inputs list, the
    # duration pre-flight evaluates with no indurs (duration typically
    # ``set_by`` a dur param), and lineage records an empty inputs list.
    # graph()/batch()/sweep() exclude arity-0 entries with a structured
    # ``arity_zero_unsupported`` error — their spec shapes are
    # input-wiring by construction (see those modules).
    input_arity: int
    channel_constraint: Literal["mono", "stereo", "any", "multi"]
    input_format: str
    # ``.wav`` / ``.ana`` are the audio formats (extension actually
    # derived from ``domain`` at output-naming time).
    # ``.evl`` / ``.for`` / ``.txt`` / ``.frq`` / ``.trn`` are data
    # formats — see DATA_OUTPUT_FORMATS above for the exact semantics
    # they switch on.
    output_format: Literal[".wav", ".ana", ".evl", ".for", ".txt", ".frq", ".trn"]
    stability: Literal["stable", "unstable"] = "stable"
    phase_sensitive: bool = False
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
# Result-envelope models
# ---------------------------------------------------------------------------


class ErrorEntry(BaseModel):
    type: str
    message: str
    fix: str | None = None


class RecentGraphEntry(BaseModel):
    """One slot of the conversational ``recent_graphs`` deque.

    ``output_node`` is ``None`` for a ``batch()`` entry — batch is an
    atomic context event (one deque slot for N outputs) whose elements
    are addressed via ``latest_batch[i]``, with ``batch_size`` carrying N."""

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
# Lineage and output verification
# ---------------------------------------------------------------------------


class InputRecord(BaseModel):
    """Provenance for one input file to a node.

    The sha256 is captured at execution time so provenance (``why()``) can
    report exactly which input bytes a downstream output came from.

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

    Captured in :class:`NodeLineage.compiled_breakpoints` so the
    provenance trail shows the .brk content sha and which audio duration
    the relative-time list was compiled against.

    ``source_kind`` distinguishes:

    - ``"input_wav"`` — duration came from the main op's .wav input
      directly via ``soundfile.info()``.
    - ``"pvoc_lineage"`` — duration came from an auto-PVOC node in the
      same graph (chained .wav → .ana → main op case).
    - ``"ana_sfprops"`` — duration came from shelling out to CDP's
      ``sfprops -d`` on a .ana whose source wav isn't reachable in the
      current graph (pre-converted .ana in inputs/, or cross-graph
      reference).
    - ``"preexisting_brk"`` — user supplied an existing .brk file by
      path. No compilation happened; ``source_duration_s`` is ``None``.
    - ``"set_by_param"`` — arity-0 (generator) entry: there is no input
      audio, so the envelope axis is the OUTPUT duration, taken from
      the entry's ``set_by`` duration-model parameter (e.g. ``synth
      wave``'s ``dur``).
    - ``"dry_run_override"`` / ``"dry_run_dummy"`` —
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
    for human-readable debugging and surfaced by ``why()``.
    """

    argv: list[str]  # exact subprocess argv after arch-prefix wrapping
    inputs: list[InputRecord]
    output_path: str  # absolute path on disk
    output_sha256: str | None  # None if output verification failed pre-hashing
    params: dict[str, Any]  # snapshot of the user's parameter dict
    cdp_version: str  # version of the detected CDP install
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    exit_code: int | None  # None if the subprocess timed out
    # Set on auto-PVOC nodes: the source wav's duration, for downstream
    # relative-time breakpoint compilation.
    source_wav_duration_s: float | None = None
    compiled_breakpoints: dict[str, CompiledBreakpoint] = Field(
        default_factory=dict,
    )
    # True when this node's output was served from the global derivative
    # cache instead of being freshly computed (auto-PVOC nodes only).
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
