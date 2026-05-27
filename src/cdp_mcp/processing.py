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
            range_hint = _range_hint(spec)
            errors.append(
                ErrorEntry(
                    type="missing_parameter",
                    message=f"Missing required parameter {name!r}.",
                    fix=f"Pass a numeric value{range_hint}.",
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
    """Accepts int / float scalars, list (breakpoint pairs), and `.brk`
    path strings. Compiler validates list / path contents separately
    (Task 8). Bool still rejected (no curated bool params yet)."""
    if isinstance(value, bool):
        # bool is a subclass of int; treat it as a type error in Phase 1a
        # since no curated entries expose bool-typed params yet.
        return ErrorEntry(
            type="param_type",
            message=f"Parameter {name!r} got bool {value!r}; expected a number.",
            fix=(
                "Bool-typed parameters and value-less flags are not "
                "currently exposed in any curated entry. For the switch "
                "you want, reach for execute()."
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

    Layout (per the Phase 1a spec):
        [program, mode, *([submode] if submode else []),
         *input_paths, output_path,
         *params_in_entry_declaration_order]

    Each param emits one of three forms:

    - ``"<value>"`` — positional (``spec.flag is None``)
    - ``"<flag><value>"`` — attached-value flag, no space (CDP convention)
    - ``"<flag>"`` — value-less switch flag, no value at all

    A flag param with no user value and no default is omitted entirely;
    emitting a bare ``-l`` for an attached-value flag would be invalid CDP
    syntax, and the curator clearly didn't want the switch on.

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
    argv.append(_argv_path(output_path, cwd))
    for name, spec in entry.parameters.items():
        value = params.get(name, spec.default)
        # Optional flag parameter with no value supplied and no default:
        # omit from argv. (CDP flags are optional by definition; emitting
        # `-l` with no value would be invalid, and emitting a default for
        # something the curator left unset would change CDP's behavior.)
        if spec.flag is not None and value is None:
            continue
        if isinstance(value, Path):
            # Compiled breakpoint file (Task 8). Render cwd-relative
            # inside the session tree (CDP-quirk workaround applies
            # the same as for inputs/outputs).
            formatted = _argv_path(value, cwd)
        else:
            formatted = _format_value(value, spec.type)
        if spec.flag is None:
            argv.append(formatted)
        elif spec.flag_kind == "no_value":
            argv.append(spec.flag)
        else:  # attached_value
            argv.append(f"{spec.flag}{formatted}")
    return argv


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
    if declared_type == "int" or (
        isinstance(value, int) and not isinstance(value, bool)
    ):
        return str(int(value))
    if declared_type == "float" or isinstance(value, float):
        return format(float(value), ".10g")
    # Defensive fallback — validate_params should have rejected anything else.
    return str(value)
