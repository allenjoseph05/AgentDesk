"""Unit tests for cross-chunk container image sentinel inspection."""

from __future__ import annotations

from io import BytesIO

import pytest

from scripts.verify_image_secrets import stream_contains_marker


def test_stream_scan_finds_a_marker_split_across_chunks() -> None:
    marker = b"agentdesk-secret-sentinel"
    stream = BytesIO(b"safe-prefix-" + marker + b"-safe-suffix")

    assert stream_contains_marker(stream, marker, chunk_size=16)


def test_stream_scan_accepts_an_archive_without_the_marker() -> None:
    assert not stream_contains_marker(BytesIO(b"ordinary image archive data"), b"not-present")


def test_stream_scan_rejects_empty_markers_and_invalid_chunk_sizes() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        stream_contains_marker(BytesIO(b"archive"), b"")
    with pytest.raises(ValueError, match="must be positive"):
        stream_contains_marker(BytesIO(b"archive"), b"marker", chunk_size=0)
