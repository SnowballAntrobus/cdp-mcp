"""Pure-function helpers for the ``process()`` tool.

Two responsibilities, both side-effect free:

- :func:`validate_params` — checks a user-supplied params dict against a
  :class:`KnowledgeEntry`'s ``ParameterSpec`` records and returns a pair
  ``(errors, warnings)``. All checks run to completion.
- :func:`build_cdp_argv` — assembles the CDP argv array from a validated
  entry/inputs/output/params combination, ready for the security gate.

Neither function touches the filesystem or runs subprocesses.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .schema import ErrorEntry, KnowledgeEntry, ParameterSpec

# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


def validate_params(
    entry: KnowledgeEntry,
    params: dict[str, Any],
) -> tuple[list[ErrorEntry], list[str]]:
    """Validate user params against an entry's ``ParameterSpec`` records.

    Returns ``(errors, warnings)``. All four check categories run to
    completion regardless of earlier failures so the LLM sees every issue
    at once rather than fixing them one round-trip at a time.
    """
    errors: list[ErrorEntry] = []
    warnings: list[str] = []

    known_names = list(entry.parameters.keys())

    # 1. Unknown params.
    for name in params:
        if name not in entry.parameters:
            errors.append(
                ErrorEntry(
                    type="unknown_parameter",
                    message=f"Unknown parameter {name!r} for {entry.program} {entry.mode}.",
                    fix=f"Known parameters for this entry: {known_names}.",
                )
            )

    # 2. Missing required params.
    # Flag parameters (those with `spec.flag is not None`) are CDP-optional by
    # definition — they're flags. Only positional parameters with no default
    # are "required" in the sense of validate_params.
    for name, spec in entry.parameters.items():
        if name in params:
            continue
        if spec.flag is None and spec.default is None:
            if spec.type == "free_string":
                # Phase 6 (tranche 24): the required value is a plain
                # string (e.g. a shuffle domain-image map), so "pass a
                # numeric value" would send the caller the wrong way.
                pattern_hint = (
                    f" matching pattern {spec.pattern!r}"
                    if spec.pattern is not None else ""
                )
                fix = f"Pass a string value{pattern_hint}."
            else:
                fix = f"Pass a numeric value{_range_hint(spec)}."
            errors.append(
                ErrorEntry(
                    type="missing_parameter",
                    message=f"Missing required parameter {name!r}.",
                    fix=fix,
                )
            )

    # 3 + 4: type + range for each supplied param.
    for name, value in params.items():
        spec = entry.parameters.get(name)
        if spec is None:
            # Already flagged as unknown above; don't double-report.
            continue
        type_error = _check_type(name, spec, value)
        if type_error is not None:
            errors.append(type_error)
            continue
        # Range + musical-range checks only apply to scalar constants.
        # List / .brk-path values go through the breakpoint compiler
        # (Task 8) which validates content separately.
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        range_error = _check_range(name, spec, value)
        if range_error is not None:
            errors.append(range_error)
            continue
        musical_warning = _check_musical_range(name, spec, value)
        if musical_warning is not None:
            warnings.append(musical_warning)

    return errors, warnings


def _range_hint(spec: ParameterSpec) -> str:
    """Format ``min`` / ``max`` / ``unit`` into a human-readable hint."""
    parts: list[str] = []
    if spec.min is not None and spec.max is not None:
        parts.append(f" in [{spec.min}, {spec.max}]")
    elif spec.min is not None:
        parts.append(f" >= {spec.min}")
    elif spec.max is not None:
        parts.append(f" <= {spec.max}")
    if spec.unit:
        parts.append(f" ({spec.unit})")
    return "".join(parts)


def _check_type(
    name: str,
    spec: ParameterSpec,
    value: Any,
) -> ErrorEntry | None:
    """Accepts int / float scalars, list (breakpoint pairs), `.brk`
    path strings, and — for ``aux_file`` params — non-``.brk`` path
    strings. Compiler validates list / .brk-path contents separately
    (Task 8); aux-file existence is checked in node_validation step 8.7.
    Bool accepted only for value-less switch params (Phase 3).
    ``free_string`` params (Phase 6, tranche 24) accept plain non-.brk
    strings, optionally gated by the spec's ``pattern`` regex."""
    if spec.type == "free_string":
        # Plain string parsed straight from argv by CDP (shuffle's
        # domain-image map). Not a path: nothing downstream resolves
        # or existence-checks it, so the only routing hazard is the
        # breakpoint compiler's ".brk means breakpoint file" string
        # rule — refuse that suffix here so step 8.5 never sees it.
        if isinstance(value, str) and not value.lower().endswith(".brk"):
            if spec.pattern is not None and re.fullmatch(spec.pattern, value) is None:
                return ErrorEntry(
                    type="param_pattern_mismatch",
                    message=(
                        f"Parameter {name!r} value {value!r} does not "
                        f"match the required pattern {spec.pattern!r}."
                    ),
                    fix=(
                        f"Pass a string matching {spec.pattern!r}"
                        + (f" — e.g. see the parameter description: "
                           f"{spec.description}" if spec.description else ".")
                    ),
                )
            return None
        if isinstance(value, str):
            return ErrorEntry(
                type="param_type",
                message=(
                    f"Parameter {name!r} is a free-string parameter but "
                    f"got a .brk path {value!r}."
                ),
                fix=(
                    "The .brk extension is reserved for breakpoint "
                    "files. Pass the literal string value CDP expects "
                    "here (this parameter is not a file path)."
                ),
            )
        return ErrorEntry(
            type="param_type",
            message=(
                f"Parameter {name!r} is a free-string parameter but got "
                f"{type(value).__name__} {value!r}; expected a plain "
                "string."
            ),
            fix="Pass a string value (e.g. a shuffle map like 'ab-abab').",
        )
    if spec.type == "aux_file":
        # Auxiliary text-file parameter: value must be a str path with
        # any extension EXCEPT .brk (that routing belongs to the
        # breakpoint compiler; a .brk-named notedata file would be
        # validated as time/value pairs, which it is not).
        if isinstance(value, str) and not value.lower().endswith(".brk"):
            return None
        if isinstance(value, str):
            return ErrorEntry(
                type="param_type",
                message=(
                    f"Parameter {name!r} is an aux_file parameter but got "
                    f"a .brk path {value!r}."
                ),
                fix=(
                    "The .brk extension is reserved for breakpoint files. "
                    "Write the auxiliary data with write_data_file() using "
                    "a .txt/.dat/.csv name and pass that path."
                ),
            )
        return ErrorEntry(
            type="param_type",
            message=(
                f"Parameter {name!r} is an aux_file parameter but got "
                f"{type(value).__name__} {value!r}; expected a str path "
                "to an existing text data file."
            ),
            fix=(
                "Write the data with write_data_file() and pass the "
                "returned path (or a session-relative path like "
                "'data/notes.txt')."
            ),
        )
    if isinstance(value, bool):
        # bool is a subclass of int. Accepted only for value-less switch
        # flags (Phase 3: True emits the bare flag, False omits it);
        # rejected for numeric params as before.
        if spec.flag_kind == "no_value":
            return None
        return ErrorEntry(
            type="param_type",
            message=f"Parameter {name!r} got bool {value!r}; expected a number.",
            fix=(
                "Bools are only accepted for value-less switch "
                "parameters (flag_kind 'no_value'). Pass a number here."
            ),
        )
    if isinstance(value, (int, float)):
        return None
    if isinstance(value, list):
        # Breakpoint compiler (Task 8) validates the list contents.
        return None
    if isinstance(value, str) and value.lower().endswith(".brk"):
        # Pre-existing .brk path; the compiler reads + hashes it.
        return None
    if isinstance(value, str):
        return ErrorEntry(
            type="param_type",
            message=f"Parameter {name!r} got str {value!r}.",
            fix=(
                "Strings are only accepted for breakpoint file paths "
                "(must end in .brk). Otherwise pass a number or a "
                "breakpoint tuple list."
            ),
        )
    return ErrorEntry(
        type="param_type",
        message=(
            f"Parameter {name!r} got {type(value).__name__} {value!r}; "
            "expected a number, breakpoint list, or .brk path."
        ),
        fix=(
            f"Pass an int or float, a breakpoint list, or a .brk path "
            f"string{_range_hint(spec)}."
        ),
    )


def _check_range(
    name: str,
    spec: ParameterSpec,
    value: int | float,
) -> ErrorEntry | None:
    if spec.min is not None and value < spec.min:
        return ErrorEntry(
            type="param_out_of_range",
            message=(
                f"Parameter {name!r} = {value} is below the minimum {spec.min}."
            ),
            fix=f"Pass a value{_range_hint(spec)}.",
        )
    if spec.max is not None and value > spec.max:
        return ErrorEntry(
            type="param_out_of_range",
            message=(
                f"Parameter {name!r} = {value} is above the maximum {spec.max}."
            ),
            fix=f"Pass a value{_range_hint(spec)}.",
        )
    return None


def _check_musical_range(
    name: str,
    spec: ParameterSpec,
    value: int | float,
) -> str | None:
    """Musical range is advisory only — never blocks, just warns."""
    if spec.musical_range is None:
        return None
    lo, hi = spec.musical_range
    if value < lo or value > hi:
        return (
            f"{name}={value} is outside musical_range [{lo}, {hi}]; "
            "CDP will accept this but the result may be extreme."
        )
    return None


# ---------------------------------------------------------------------------
# Argv assembly
# ---------------------------------------------------------------------------


def build_cdp_argv(
    entry: KnowledgeEntry,
    input_paths: list[Path],
    output_path: Path,
    params: dict[str, Any],
    cwd: Path,
) -> list[str]:
    """Assemble a CDP argv array.

    Preconditions:
    - input arity matches ``entry.input_arity``
    - ``params`` has already passed :func:`validate_params`
    - ``cwd`` is the directory the subprocess will run from (typically
      ``session.root``); paths inside ``cwd`` are emitted as cwd-relative.

    Layout (per the Phase 1a spec, extended Phase 5 wave 2a):
        [program, mode, *([submode] if submode else []),
         *input_paths,
         *pre_output_params_in_entry_declaration_order,
         output_path,
         *params_in_entry_declaration_order]

    ``pre_output`` params (``spec.position == "pre_output"`` —
    positional aux_file slots like ``submix mix``'s mixfile and
    ``formants put``'s fmntfile) render BETWEEN the inputs and the
    output path, where those CDP programs expect their data file;
    every other param renders after the output as before.

    Each param emits one of three forms:

    - ``"<value>"`` — positional (``spec.flag is None``)
    - ``"<flag><value>"`` — attached-value flag, no space (CDP convention)
    - ``"<flag>"`` — value-less switch flag, no value at all

    A flag param with no user value and no default is omitted entirely;
    emitting a bare ``-l`` for an attached-value flag would be invalid CDP
    syntax, and the curator clearly didn't want the switch on.

    A ``no_value`` switch emits its bare flag only when the resolved value
    is truthy; a falsy value (``False``, ``0``, or ``None``-after-default)
    omits the switch. (Phase 3 fix: previously any non-``None`` value —
    including a curated ``default: false`` — emitted the switch
    unconditionally, so e.g. ``strange glis``'s ``-i`` was always on.)

    Paths are rendered cwd-relative when they live under ``cwd`` (i.e. inside
    the session tree). Paths outside ``cwd`` stay absolute. This dodges a
    nasty CDP quirk where some programs — modify brassage in particular —
    do path-mangling that breaks on absolute paths containing a ``.`` in
    any parent directory name. Empirically: session names like ``frog_v0.1``
    trigger this. Relative paths sidestep the entire path-mangling code
    path. Security is unchanged — ``validate_command`` resolves both
    absolute and relative arg paths against session_root before checking.
    """
    argv: list[str] = [entry.program, entry.mode]
    if entry.submode is not None:
        argv.append(str(entry.submode))
    for p in input_paths:
        argv.append(_argv_path(p, cwd))
    # Phase 5 wave 2a: pre_output params occupy the argv slot(s) between
    # the inputs and the output path (submix mix's mixfile, formants
    # put's fmntfile); everything else renders after the output.
    for name, spec in entry.parameters.items():
        if spec.position == "pre_output":
            _emit_param(argv, spec, params.get(name, spec.default), cwd)
    argv.append(_argv_path(output_path, cwd))
    for name, spec in entry.parameters.items():
        if spec.position != "pre_output":
            _emit_param(argv, spec, params.get(name, spec.default), cwd)
    return argv


def _emit_param(
    argv: list[str],
    spec: ParameterSpec,
    value: Any,
    cwd: Path,
) -> None:
    """Append one parameter's argv rendering (possibly nothing) to ``argv``.

    Factored out of :func:`build_cdp_argv` when pre_output positioning
    split the single param loop in two (Phase 5 wave 2a); the emission
    rules themselves are unchanged from Phase 3.
    """
    # Optional flag parameter with no value supplied and no default:
    # omit from argv. (CDP flags are optional by definition; emitting
    # `-l` with no value would be invalid, and emitting a default for
    # something the curator left unset would change CDP's behavior.)
    if spec.flag is not None and value is None:
        return
    if spec.flag_kind == "no_value":
        # Value-less switch: truthy → bare flag, falsy (False / 0 /
        # None-after-default) → omitted. There is no value to format.
        if value:
            argv.append(spec.flag)
        return
    if isinstance(value, Path):
        # Compiled breakpoint or resolved aux file (Tasks 8 / 8.7).
        # Render cwd-relative inside the session tree (CDP-quirk
        # workaround applies the same as for inputs/outputs).
        formatted = _argv_path(value, cwd)
    else:
        formatted = _format_value(value, spec.type)
    if spec.flag is None:
        argv.append(formatted)
    else:  # attached_value
        argv.append(f"{spec.flag}{formatted}")


def _argv_path(p: Path, cwd: Path) -> str:
    """Render a filesystem path for inclusion in a CDP argv.

    Returns the cwd-relative form when ``p`` is inside ``cwd`` (e.g. session
    tree paths under ``session.root``), otherwise the absolute form.

    Why bother: see :func:`build_cdp_argv` docstring — some CDP programs
    (modify brassage) crash on absolute paths whose ancestry contains a
    ``.``. Relative paths dodge the entire problematic code path.
    """
    try:
        return str(p.relative_to(cwd))
    except ValueError:
        return str(p)


def _format_value(value: Any, declared_type: str) -> str:
    """Render a parameter value into a CDP-friendly string.

    Float values use ``format(v, ".10g")``: general format up to 10
    significant digits with trailing zeros trimmed. This handles
    ``0.1 + 0.2`` → ``"0.3"`` cleanly while preserving precision when
    actually needed (``1.234567`` → ``"1.234567"``, ``1e-12`` → ``"1e-12"``).
    Integer values use plain ``str(int(value))`` to avoid spurious decimals.
    """
    if declared_type in ("free_string", "str"):
        # Phase 6 (tranche 24): plain strings render verbatim —
        # ``free_string`` for caller-supplied values (shuffle maps),
        # ``str`` for curated fixed defaults (getpitch side names).
        # Ordered before the numeric branches so a numeric-looking
        # string is never reformatted.
        return str(value)
    if declared_type == "int" or (
        isinstance(value, int) and not isinstance(value, bool)
    ):
        return str(int(value))
    if declared_type == "float" or isinstance(value, float):
        return format(float(value), ".10g")
    # Defensive fallback — validate_params should have rejected anything else.
    return str(value)
