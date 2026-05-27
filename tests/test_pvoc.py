"""Tests for cdp_mcp.pvoc.maybe_insert_pvoc."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cdp_mcp.graph import GraphDir
from cdp_mcp.pvoc import PVOCFailedError, maybe_insert_pvoc, synth_for_audition
from cdp_mcp.schema import NodeLineage
from cdp_mcp.session import Session, SessionConfig

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_cdp_path(tmp_path, monkeypatch):
    """Tmp CDP_PATH containing a copy of fake_subprocess.py named `pvoc`."""
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    shutil.copy2(_FAKE_SUBPROCESS, cdp / "pvoc")
    (cdp / "pvoc").chmod(0o755)
    return cdp


@pytest.fixture
def session_and_graph(tmp_path):
    """A Session + GraphDir built directly (no SessionManager)."""
    session_root = (tmp_path / "session").resolve()
    for sub in ("inputs", "graphs", "templates", "envelopes", "tmp"):
        (session_root / sub).mkdir(parents=True, exist_ok=True)
    config = SessionConfig(
        session_name="test",
        created_at=datetime.now(timezone.utc),
        cdp_version="fake",
        python_version="3.11.6",
        cdp_mcp_version="0.0.0",
    )
    session = Session(name="test", root=session_root, config=config)
    graph = GraphDir(session, "test-op")
    return session, graph


@pytest.fixture
def cache_root(tmp_path):
    c = (tmp_path / "cache").resolve()
    c.mkdir()
    return c


# ---------------------------------------------------------------------------
# Skipped cases
# ---------------------------------------------------------------------------


async def test_ana_input_target_spectral_skipped(
    fake_cdp_path, session_and_graph, cache_root
):
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.ana"
    inp.write_bytes(b"x" * 2000)
    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="fake",
    )
    assert result.state == "skipped"
    assert result.output_path == inp
    assert result.node_id is None
    assert "n1" not in graph.node_ids()


async def test_wav_input_target_time_skipped(
    fake_cdp_path, session_and_graph, cache_root
):
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.wav"
    inp.write_bytes(b"\x00" * 2000)
    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="time",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="fake",
    )
    assert result.state == "skipped"


# ---------------------------------------------------------------------------
# Succeeded cases
# ---------------------------------------------------------------------------


async def test_wav_to_spectral_runs_pvoc_anal(
    fake_cdp_path, session_and_graph, cache_root, monkeypatch
):
    """time → spectral: fake CDP writes the .ana, node is recorded."""
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.wav"
    inp.write_bytes(b"\x00" * 2000)

    # Patch the fake pvoc binary to actually write a .ana file at argv[-1]
    # whenever invoked. We can't pass --write-ana through the real
    # validate_command path; instead we replace run_cdp_command with a
    # version that intercepts. But cleaner: replace `pvoc` with a wrapper
    # script that always writes its output file.
    #
    # Approach: write a shell wrapper at cdp_path/pvoc that calls
    # fake_subprocess.py with --write-ana set to the last argv element.
    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
# $@ is "anal 1 <input> <output>" — output is the last arg.
OUTPUT="${{@: -1}}"
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
    )
    wrapper.chmod(0o755)

    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="fake",
    )

    assert result.state == "succeeded", result.error_entry
    assert result.output_path == graph.root / "n1_pvoc-anal.ana"
    assert result.output_path.exists()
    assert result.node_id == "n1"
    assert isinstance(result.lineage, NodeLineage)
    assert "n1" in graph.node_ids()
    # node_index.json reflects the new node.
    index = json.loads(graph.node_index_path.read_text())
    assert index["n1"] == "n1_pvoc-anal.ana"


async def test_pvoc_insert_records_source_wav_duration(
    fake_cdp_path, session_and_graph, cache_root
):
    """Task 8: maybe_insert_pvoc on a real .wav input records the wav's
    duration in NodeLineage.source_wav_duration_s. Downstream breakpoint
    compilation reads this to convert relative-time tuples to absolute
    seconds across chained .ana ops."""
    session, graph = session_and_graph
    # Real wav so sf.info reads a duration. 2.5 second silent mono wav.
    inp = session.inputs_dir / "real.wav"
    sr = 44100
    sf.write(str(inp), np.zeros(int(2.5 * sr), dtype=np.float32), sr)

    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
OUTPUT="${{@: -1}}"
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
    )
    wrapper.chmod(0o755)

    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="fake",
    )
    assert result.state == "succeeded", result.error_entry
    assert result.lineage is not None
    assert result.lineage.source_wav_duration_s == pytest.approx(2.5, abs=0.01)


async def test_ana_to_time_runs_pvoc_synth(
    fake_cdp_path, session_and_graph, cache_root
):
    """spectral → time: fake CDP writes the .wav, node is recorded."""
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.ana"
    inp.write_bytes(b"\x00" * 2000)

    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
OUTPUT="${{@: -1}}"
exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT"
"""
    )
    wrapper.chmod(0o755)

    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="time",
        graph_dir=graph,
        node_id="n2",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="fake",
    )

    assert result.state == "succeeded", result.error_entry
    assert result.output_path == graph.root / "n2_pvoc-synth.wav"
    assert result.output_path.exists()
    assert result.node_id == "n2"


# ---------------------------------------------------------------------------
# Failed cases
# ---------------------------------------------------------------------------


async def test_unknown_extension_fails(
    fake_cdp_path, session_and_graph, cache_root
):
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.foo"
    inp.write_bytes(b"x" * 100)
    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="fake",
    )
    assert result.state == "failed"
    assert result.error_entry is not None
    assert result.error_entry.type == "unknown_input_domain"


async def test_pvoc_nonzero_exit_fails(
    fake_cdp_path, session_and_graph, cache_root
):
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.wav"
    inp.write_bytes(b"\x00" * 2000)

    # Replace the pvoc binary with one that exits 1 without writing output.
    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
exec "{_FAKE_SUBPROCESS}" --exit 1
"""
    )
    wrapper.chmod(0o755)

    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="fake",
    )
    assert result.state == "failed"
    assert result.error_entry is not None
    assert result.error_entry.type == "pvoc_failed"
    assert result.subprocess_result is not None
    assert result.subprocess_result.exit_code == 1


# ---------------------------------------------------------------------------
# synth_for_audition (Task 7 — rendering aid, no graph node)
# ---------------------------------------------------------------------------


async def test_synth_for_audition_happy_path(
    fake_cdp_path, session_and_graph, cache_root
):
    """time → wav rendering aid: pvoc synth runs, output lands in tmp_dir."""
    session, _graph = session_and_graph
    ana = session.inputs_dir / "frog.ana"
    ana.write_bytes(b"\x00" * 2000)

    # Replace pvoc binary with a wrapper that writes a valid wav at argv[-1].
    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
OUTPUT="${{@: -1}}"
exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT"
"""
    )
    wrapper.chmod(0o755)

    out_path, sub = await synth_for_audition(
        ana,
        session=session,
        cdp_path=fake_cdp_path,
        cache_root=cache_root,
        cdp_version="fake",
    )
    assert out_path == session.tmp_dir / "frog.wav"
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert sub.exit_code == 0
    # No node added to any graph.
    # (session_and_graph creates one graph; assert it stayed empty of new files.)


async def test_synth_for_audition_predeletes_existing_output(
    fake_cdp_path, session_and_graph, cache_root
):
    """CDP r8's pvoc synth refuses to overwrite — we must pre-delete.

    Models real CDP behavior with a wrapper that exits 1 if the output
    path already exists. Pre-create a wav at the target path; the
    pre-delete must clear it before CDP looks, otherwise the wrapper
    fails and we'd raise.
    """
    session, _graph = session_and_graph
    ana = session.inputs_dir / "frog.ana"
    ana.write_bytes(b"\x00" * 2000)

    # Pre-create a file at the target path. Without our pre-delete, the
    # refuse-to-overwrite wrapper below would exit 1.
    existing = session.tmp_dir / "frog.wav"
    existing.write_bytes(b"PREVIOUS")

    # Wrapper that mimics CDP r8: refuses to clobber existing output.
    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
OUTPUT="${{@: -1}}"
if [ -e "$OUTPUT" ]; then
    echo "pvoc synth: output file exists, refusing to overwrite" >&2
    exit 1
fi
exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT"
"""
    )
    wrapper.chmod(0o755)

    out_path, sub = await synth_for_audition(
        ana,
        session=session,
        cdp_path=fake_cdp_path,
        cache_root=cache_root,
        cdp_version="fake",
    )
    # Pre-delete worked: CDP didn't see the stale file, wrote a fresh one.
    assert out_path.read_bytes() != b"PREVIOUS"
    assert sub.exit_code == 0


async def test_synth_for_audition_nonzero_exit_raises(
    fake_cdp_path, session_and_graph, cache_root
):
    session, _graph = session_and_graph
    ana = session.inputs_dir / "frog.ana"
    ana.write_bytes(b"\x00" * 2000)

    # Wrapper that exits 1 without writing output.
    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
exec "{_FAKE_SUBPROCESS}" --exit 1
"""
    )
    wrapper.chmod(0o755)

    with pytest.raises(PVOCFailedError, match="exited with code 1"):
        await synth_for_audition(
            ana,
            session=session,
            cdp_path=fake_cdp_path,
            cache_root=cache_root,
            cdp_version="fake",
        )


async def test_synth_for_audition_missing_output_raises(
    fake_cdp_path, session_and_graph, cache_root
):
    """CDP exits 0 but doesn't write the output file."""
    session, _graph = session_and_graph
    ana = session.inputs_dir / "frog.ana"
    ana.write_bytes(b"\x00" * 2000)

    # Wrapper that returns success but writes nothing.
    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
exec "{_FAKE_SUBPROCESS}" --exit 0
"""
    )
    wrapper.chmod(0o755)

    with pytest.raises(PVOCFailedError, match="produced no output"):
        await synth_for_audition(
            ana,
            session=session,
            cdp_path=fake_cdp_path,
            cache_root=cache_root,
            cdp_version="fake",
        )


# ---------------------------------------------------------------------------
# Task 10 — PVOC cache: miss populates, hit skips subprocess, version invalidates
# ---------------------------------------------------------------------------


def _install_real_pvoc_wrapper(fake_cdp_path: Path) -> None:
    """Replace the ``pvoc`` binary with a wrapper that writes a .ana file
    at argv[-1] each call. The fake_subprocess marker bytes embed the
    timestamp, so each call produces *different* output bytes — handy
    for proving the cache hit served the same file that the first call
    populated, not a fresh subprocess run."""
    wrapper = fake_cdp_path / "pvoc"
    wrapper.unlink()
    wrapper.write_text(
        f"""#!/bin/sh
OUTPUT="${{@: -1}}"
exec "{_FAKE_SUBPROCESS}" --write-ana "$OUTPUT"
"""
    )
    wrapper.chmod(0o755)


async def test_pvoc_cache_miss_populates_cache(
    fake_cdp_path, session_and_graph, cache_root
):
    """First call: CDP runs, output written to graph, cache populated."""
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.wav"
    sr = 44100
    sf.write(str(inp), np.zeros(int(0.5 * sr), dtype=np.float32), sr)
    _install_real_pvoc_wrapper(fake_cdp_path)

    result = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="r8-fake",
    )
    assert result.state == "succeeded", result.error_entry
    assert result.lineage is not None
    assert result.lineage.cache_hit is False  # first call was a real run
    # Cache populated under the pvoc tier — exactly one .ana file.
    cached_files = list((cache_root / "pvoc").glob("*.ana"))
    assert len(cached_files) == 1
    assert cached_files[0].stat().st_size > 0


async def test_pvoc_cache_hit_skips_subprocess(
    fake_cdp_path, session_and_graph, cache_root, monkeypatch
):
    """Second call with identical (input, argv, cdp_version) → cache hit.
    The subprocess MUST NOT run. Lineage reflects cache_hit=True."""
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.wav"
    sr = 44100
    sf.write(str(inp), np.zeros(int(0.5 * sr), dtype=np.float32), sr)
    _install_real_pvoc_wrapper(fake_cdp_path)

    # First call: populates cache.
    first = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="r8-fake",
    )
    assert first.state == "succeeded"
    first_bytes = first.output_path.read_bytes()

    # Second call: subprocess must not be invoked. Use a fresh graph dir
    # to avoid node-id reuse; the cache is shared across graphs.
    graph2 = GraphDir(session, "second-graph")
    from unittest.mock import AsyncMock
    boom = AsyncMock(side_effect=AssertionError("subprocess must not run on cache hit"))
    monkeypatch.setattr("cdp_mcp.pvoc.run_cdp_command", boom)

    second = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph2,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="r8-fake",
    )
    assert second.state == "succeeded", second.error_entry
    assert second.lineage is not None
    assert second.lineage.cache_hit is True
    boom.assert_not_called()
    # Materialized content matches the first call's output.
    assert second.output_path.read_bytes() == first_bytes


async def test_pvoc_cache_invalidates_on_cdp_version_change(
    fake_cdp_path, session_and_graph, cache_root
):
    """Same audio + same argv but a different cdp_version → cache miss,
    new entry created. The first cache entry is not served to the
    second call."""
    session, graph = session_and_graph
    inp = session.inputs_dir / "x.wav"
    sr = 44100
    sf.write(str(inp), np.zeros(int(0.5 * sr), dtype=np.float32), sr)
    _install_real_pvoc_wrapper(fake_cdp_path)

    await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="r7",
    )
    # Second call: bumped cdp_version → different cache key.
    graph2 = GraphDir(session, "second-graph")
    second = await maybe_insert_pvoc(
        input_path=inp,
        target_domain="spectral",
        graph_dir=graph2,
        node_id="n1",
        cdp_path=fake_cdp_path,
        session_root=session.root,
        cache_root=cache_root,
        cdp_version="r8",
    )
    assert second.state == "succeeded"
    assert second.lineage is not None
    assert second.lineage.cache_hit is False
    # Two distinct cache entries now exist.
    cached_files = list((cache_root / "pvoc").glob("*.ana"))
    assert len(cached_files) == 2
