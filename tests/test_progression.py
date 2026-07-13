"""Integration tests for the progression() MCP tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

from cdp_mcp.config import CDPConfig
from cdp_mcp.graph import LatestTracker
from cdp_mcp.session import SessionManager
from cdp_mcp.tools import progression as progression_module

_FAKE_SUBPROCESS = (
    Path(__file__).parent / "fixtures" / "fake_subprocess.py"
).resolve()
_SR = 22050


def _write_sine(path: Path, seconds: float = 1.0) -> None:
    t = np.arange(int(_SR * seconds)) / _SR
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), _SR)


def _panel_h() -> int:
    return progression_module._LABEL_H + progression_module._SPEC_H


def _expected_height(n_panels: int, omitted: bool = False) -> int:
    """Composite height for N spectrogram panels (+ optional summary panel)."""
    blocks = n_panels + (1 if omitted else 0)
    height = n_panels * _panel_h()
    if omitted:
        height += progression_module._OMITTED_PANEL_H
    return height + (blocks - 1) * progression_module._GUTTER_PX


@pytest.fixture
def fake_cdp_path(tmp_path):
    """Tmp CDP_PATH with a pvoc wrapper that writes a real wav on synth."""
    cdp = (tmp_path / "cdp").resolve()
    cdp.mkdir()
    wrapper = cdp / "pvoc"
    wrapper.write_text(
        f"""#!/usr/bin/env bash
case "$1" in
    synth)
        OUTPUT="${{@: -1}}"
        exec "{_FAKE_SUBPROCESS}" --write-wav "$OUTPUT"
        ;;
    *)
        exit 1
        ;;
esac
"""
    )
    wrapper.chmod(0o755)
    return cdp


@pytest.fixture
def mcp_with_progression(fake_cdp_path, tmp_path):
    mcp = FastMCP("test-cdp-progression")
    sessions_root = (tmp_path / "sessions").resolve()
    cache_root = (tmp_path / "cache").resolve()
    cache_root.mkdir()
    cdp_cfg = CDPConfig(cdp_path=fake_cdp_path, version="fake", detected_binaries=["pvoc"])
    sessions = SessionManager(sessions_root, lambda: cdp_cfg)
    tracker = LatestTracker()
    progression_module.register(
        mcp, sessions=sessions, cdp_config_provider=lambda: cdp_cfg,
        latest_tracker=tracker, cache_root=cache_root,
    )
    return mcp, sessions, tracker


async def _call(mcp: FastMCP, args: dict[str, Any]) -> Any:
    return await mcp._tool_manager.call_tool(
        "progression", args, context=None, convert_result=False
    )


# ---------------------------------------------------------------------------
# Pre-flight failure paths
# ---------------------------------------------------------------------------


async def test_no_active_session(mcp_with_progression):
    mcp, _sessions, _tracker = mcp_with_progression
    result = await _call(mcp, {"targets": ["x.wav"]})
    assert isinstance(result, list) and len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert any(e["type"] == "no_active_session" for e in envelope["errors"])


async def test_empty_targets_list(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    sessions.set_active("s1")
    result = await _call(mcp, {"targets": []})
    assert len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert any(e["type"] == "progression_empty" for e in envelope["errors"])


async def test_graph_with_no_nodes(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    session, _ = sessions.set_active("s1")
    graph_root = session.graphs_dir / "g-empty"
    graph_root.mkdir(parents=True)
    (graph_root / "node_index.json").write_text("{}\n")
    result = await _call(mcp, {"targets": "g-empty"})
    assert len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert any(e["type"] == "progression_empty" for e in envelope["errors"])


async def test_unresolvable_target_names_the_ref(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "frog.wav", seconds=0.3)
    result = await _call(mcp, {"targets": ["frog.wav", "ghost.wav"]})
    assert len(result) == 1
    envelope = result[0]
    assert envelope["status"] == "failed"
    assert envelope["output"] is None
    resolution_errors = [
        e for e in envelope["errors"] if e["type"] == "reference_resolution"
    ]
    assert resolution_errors
    assert any("ghost.wav" in e["message"] for e in resolution_errors)


async def test_missing_graph_id_is_reference_resolution(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    sessions.set_active("s1")
    result = await _call(mcp, {"targets": "no-such-graph"})
    assert len(result) == 1
    errors = result[0]["errors"]
    assert any(e["type"] == "reference_resolution" for e in errors)
    assert any("no-such-graph" in e["message"] for e in errors)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_list_of_wav_targets_happy_path(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    session, _ = sessions.set_active("s1")
    _write_sine(session.inputs_dir / "a.wav", seconds=0.5)
    _write_sine(session.inputs_dir / "b.wav", seconds=1.0)
    _write_sine(session.inputs_dir / "c.wav", seconds=2.0)
    result = await _call(mcp, {"targets": ["a.wav", "b.wav", "c.wav"]})
    assert isinstance(result, list) and len(result) == 2
    assert isinstance(result[0], Image)
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["output"] is not None
    assert envelope["output"].endswith(".png")
    png_path = Path(envelope["output"])
    assert png_path.exists()
    assert png_path.parent == session.root / "visualizations"
    # Valid PNG whose height indicates 3 panels + gutters.
    with PILImage.open(png_path) as im:
        width, height = im.size
    assert width == progression_module._PANEL_MAX_W
    assert height == _expected_height(3)
    assert envelope["panel_count"] == 3
    assert envelope["truncated"] is False
    assert envelope["targets_rendered"] == ["a.wav", "b.wav", "c.wav"]
    assert envelope["warnings"] == []
    assert envelope["cached"] is False


async def test_graph_id_renders_nodes_in_numeric_order(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    session, _ = sessions.set_active("s1")
    graph_root = session.graphs_dir / "g1"
    graph_root.mkdir(parents=True)
    # Written out of order on purpose; n10 must sort after n9.
    index: dict[str, str] = {}
    for node_id in ["n10", "n1", "n9", "n2"]:
        filename = f"{node_id}_out.wav"
        _write_sine(graph_root / filename, seconds=0.3)
        index[node_id] = filename
    (graph_root / "node_index.json").write_text(json.dumps(index))
    result = await _call(mcp, {"targets": "g1"})
    assert len(result) == 2
    assert isinstance(result[0], Image)
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["targets_rendered"] == ["g1:n1", "g1:n2", "g1:n9", "g1:n10"]
    assert envelope["panel_count"] == 4
    assert envelope["truncated"] is False
    with PILImage.open(envelope["output"]) as im:
        assert im.size == (progression_module._PANEL_MAX_W, _expected_height(4))


async def test_ana_target_auto_synths(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    session, _ = sessions.set_active("s1")
    (session.inputs_dir / "frog.ana").write_bytes(b"\x00" * 2000)
    result = await _call(mcp, {"targets": ["frog.ana"]})
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["panel_count"] == 1
    assert envelope["targets_rendered"] == ["frog.ana"]


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


async def test_truncation_over_panel_cap(mcp_with_progression):
    mcp, sessions, _tracker = mcp_with_progression
    session, _ = sessions.set_active("s1")
    names = [f"t{i:02d}.wav" for i in range(10)]
    for name in names:
        _write_sine(session.inputs_dir / name, seconds=0.2)
    result = await _call(mcp, {"targets": names})
    assert len(result) == 2
    envelope = result[1]
    assert envelope["status"] == "ok"
    assert envelope["truncated"] is True
    assert envelope["panel_count"] == progression_module._PANEL_CAP
    assert envelope["targets_rendered"] == names[: progression_module._PANEL_CAP]
    assert any("2 more nodes omitted" in w for w in envelope["warnings"])
    # First 8 panels + the text-only summary panel worth of height.
    with PILImage.open(envelope["output"]) as im:
        assert im.size == (
            progression_module._PANEL_MAX_W,
            _expected_height(progression_module._PANEL_CAP, omitted=True),
        )
