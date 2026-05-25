"""Unit tests for cdp_mcp.utils."""

from __future__ import annotations

import hashlib
import os
import secrets

from cdp_mcp.utils import atomic_write_text, sha256_file


def test_atomic_write_text_writes_content(tmp_path):
    target = tmp_path / "hello.txt"
    atomic_write_text(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"
    # No stray .tmp file left over.
    assert not (tmp_path / "hello.txt.tmp").exists()


def test_atomic_write_text_overwrites(tmp_path):
    target = tmp_path / "thing.json"
    atomic_write_text(target, '{"v": 1}')
    atomic_write_text(target, '{"v": 2}')
    assert target.read_text(encoding="utf-8") == '{"v": 2}'
    assert not (tmp_path / "thing.json.tmp").exists()


def test_atomic_write_text_handles_no_extension(tmp_path):
    # path.with_suffix(path.suffix + ".tmp") still works when suffix is "".
    target = tmp_path / "noext"
    atomic_write_text(target, "x")
    assert target.read_text(encoding="utf-8") == "x"


def test_sha256_file_matches_hashlib(tmp_path):
    content = b"the quick brown fox jumps over the lazy dog"
    target = tmp_path / "fox.bin"
    target.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert sha256_file(target) == expected


def test_sha256_file_handles_large_file(tmp_path):
    # 1 MB of random bytes — verifies chunked reading doesn't OOM and
    # produces a 64-char hex digest.
    target = tmp_path / "big.bin"
    target.write_bytes(secrets.token_bytes(1024 * 1024))
    digest = sha256_file(target)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_sha256_file_uses_custom_chunk_size(tmp_path):
    # Just exercise the chunk_size knob — output identical to default.
    content = os.urandom(200)
    target = tmp_path / "chunked.bin"
    target.write_bytes(content)
    assert sha256_file(target, chunk_size=32) == sha256_file(target)
