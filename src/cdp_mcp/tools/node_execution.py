"""Post-validation node execution shared by ``process()`` and ``graph()``.

Task 11b extraction, mirroring Task 3's ``validate_node`` split: the
subprocess-run → verify → lineage → error-aggregation sequence that lived
as steps 11–15 of ``process_impl`` moves here *unchanged in behavior*, so
``graph()`` (and later ``batch()``) execute nodes through exactly the code
path ``process()`` uses — same watchdog, same error taxonomy, same
precedence (size_cap > timeout > subprocess_error), same lineage shape.
The existing process-tool tests are the regression suite for this path.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from mcp.server.fastmcp import Context

from ..config import CDPConfig
from ..error_parsing import parse_cdp_errors
from ..graph import verify_output
from ..limits import OUTPUT_FILE_SIZE_CAP_BYTES
from ..schema import ErrorEntry, InputRecord, NodeLineage, OutputVerification
from ..session import Session
from ..subprocess_core import SubprocessResult, run_cdp_command
from ..utils import sha256_file
from .node_validation import ValidationResult


@dataclass
class NodeExecutionOutcome:
    """Result of one :func:`execute_validated_node` call.

    ``bookkeeping_error`` is set when the subprocess ran but the
    lineage/node-index write failed — callers decide how to surface it
    (``process()`` keeps its dedicated failure envelope; ``graph()``
    folds it into the node report).
    """

    success: bool
    subprocess_result: SubprocessResult
    verification: OutputVerification
    errors: list[ErrorEntry]
    output_sha256: str | None
    bookkeeping_error: ErrorEntry | None = None


async def execute_validated_node(
    *,
    ctx: Context,
    validation: ValidationResult,
    program: str,
    mode: str,
    params: dict,
    timeout_seconds: float,
    session: Session,
    cdp: CDPConfig,
) -> NodeExecutionOutcome:
    """Run a validated node's subprocess and record it. Steps 11–15 of
    the original ``process_impl``, verbatim in behavior.

    Preconditions: ``validation`` is a *success* result from
    :func:`~cdp_mcp.tools.node_validation.validate_node` with
    ``dry_run=False`` (``planned_argv``/``output_path``/``graph_dir``
    populated).
    """
    graph_dir = validation.graph_dir
    assert graph_dir is not None
    assert validation.planned_argv is not None
    assert validation.output_path is not None
    assert validation.main_node_id is not None
    assert validation.out_filename is not None
    assert validation.post_pvoc_paths is not None
    assert validation.pvoc_source_nodes is not None
    output_path = validation.output_path

    # 11. Run main op.
    started_at = datetime.now(timezone.utc)
    sub = await run_cdp_command(
        validation.planned_argv,
        cwd=session.root,
        timeout_seconds=timeout_seconds,
        ctx=ctx,
        output_path=output_path,
        size_cap_bytes=OUTPUT_FILE_SIZE_CAP_BYTES,
    )
    finished_at = datetime.now(timezone.utc)

    # 12. Verify output (Task 4). Off the event loop: verification
    # decodes audio for the RMS/silence check — sync work that must not
    # starve MCP heartbeats.
    verification = await asyncio.to_thread(verify_output, output_path)

    # 13. Build main node lineage (hashing off the event loop).
    def _hash_lineage_files() -> tuple[str | None, list[InputRecord]]:
        out_sha: str | None = None
        if verification.exists and verification.size_bytes > 0:
            try:
                out_sha = sha256_file(output_path)
            except OSError:
                out_sha = None
        records = [
            InputRecord(
                path=str(p),
                sha256=sha256_file(p) if p.exists() else "",
                source_node=src,
            )
            for p, src in zip(
                validation.post_pvoc_paths,
                validation.pvoc_source_nodes,
                strict=False,
            )
        ]
        return out_sha, records

    output_sha, main_inputs = await asyncio.to_thread(_hash_lineage_files)
    lineage = NodeLineage(
        argv=validation.planned_argv,
        inputs=main_inputs,
        output_path=str(output_path),
        output_sha256=output_sha,
        params=params,
        cdp_version=cdp.version,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=sub.duration_ms,
        exit_code=sub.exit_code,
        compiled_breakpoints=validation.compiled_breakpoints,
    )

    try:
        graph_dir.add_node(
            validation.main_node_id, validation.out_filename, lineage
        )
    except OSError as e:
        return NodeExecutionOutcome(
            success=False,
            subprocess_result=sub,
            verification=verification,
            errors=[],
            output_sha256=output_sha,
            bookkeeping_error=ErrorEntry(
                type="graph_bookkeeping_failed",
                message=f"Main op ran but lineage write failed: {e}",
                fix="Inspect the graph directory on disk for clues.",
            ),
        )

    # 14 + 15: status + errors aggregation.
    result_errors: list[ErrorEntry] = []
    # size_cap_exceeded takes precedence over the generic subprocess_error
    # that the SIGKILL would otherwise produce — the specific signal is
    # more actionable than "exited with code <signal>".
    if sub.size_cap_exceeded:
        result_errors.append(
            ErrorEntry(
                type="size_cap_exceeded",
                message=(
                    f"output file exceeded the {sub.triggered_at_bytes:,}-byte "
                    f"cap (limit: {OUTPUT_FILE_SIZE_CAP_BYTES:,} bytes); "
                    f"the subprocess was killed and partial output removed."
                ),
                fix=(
                    "Reduce the parameters that drive output size (counts, "
                    "multipliers, time spans), or use a shorter input. To "
                    "raise the cap for this work, set "
                    "CDP_MCP_OUTPUT_SIZE_CAP_BYTES in the environment "
                    "before starting the server."
                ),
            )
        )
    elif sub.timed_out:
        result_errors.append(
            ErrorEntry(
                type="timeout",
                message=(
                    f"{program} {mode} did not finish within "
                    f"{timeout_seconds}s."
                ),
                fix=(
                    "Raise timeout_seconds or use a smaller / shorter "
                    "input."
                ),
            )
        )
    elif sub.exit_code != 0:
        result_errors.append(
            ErrorEntry(
                type="subprocess_error",
                message=f"CDP exited with code {sub.exit_code}.",
                fix=None,
            )
        )
    if (
        not verification.ok
        and sub.exit_code == 0
        and not sub.timed_out
        and not sub.size_cap_exceeded
    ):
        # CDP succeeded but the output doesn't look healthy.
        result_errors.append(
            ErrorEntry(
                type="output_verification_failed",
                message=(
                    "Output file did not pass verification: "
                    + "; ".join(verification.errors)
                ),
                fix=(
                    "Inspect the output file directly; CDP exited 0 "
                    "but the result is empty, silent, or otherwise "
                    "unusable."
                ),
            )
        )

    # Pattern-match specific CDP failure modes into structured entries.
    # Skip on timeout — partial output isn't worth second-guessing.
    if not sub.timed_out:
        result_errors.extend(parse_cdp_errors(
            stdout=sub.stdout,
            stderr=sub.stderr,
            exit_code=sub.exit_code,
            expected_output=output_path,
            verification=verification,
        ))

    success = (
        sub.exit_code == 0 and not sub.timed_out and verification.ok
    )
    return NodeExecutionOutcome(
        success=success,
        subprocess_result=sub,
        verification=verification,
        errors=result_errors,
        output_sha256=output_sha,
    )
