"""Fail when a CI sentinel appears anywhere in saved container image data."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

DEFAULT_MARKER_ENVIRONMENT = "IMAGE_SECRET_SENTINEL"
DEFAULT_CHUNK_SIZE = 1024 * 1024


def stream_contains_marker(
    stream: BinaryIO,
    marker: bytes,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> bool:
    """Search a binary stream while retaining matches split across chunk boundaries."""
    if not marker:
        raise ValueError("The image secret sentinel cannot be empty.")
    if chunk_size < 1:
        raise ValueError("The scan chunk size must be positive.")

    overlap = b""
    while chunk := stream.read(chunk_size):
        candidate = overlap + chunk
        if marker in candidate:
            return True
        overlap_length = min(len(marker) - 1, len(candidate))
        overlap = candidate[-overlap_length:] if overlap_length else b""
    return False


def verify_image_archives(images: Sequence[str], marker: bytes) -> None:
    """Save images together and reject the archive if any layer or metadata leaks the marker."""
    if not images:
        raise ValueError("At least one container image is required.")

    descriptor, archive_name = tempfile.mkstemp(prefix="agentdesk-images-", suffix=".tar")
    os.close(descriptor)
    archive_path = Path(archive_name)
    try:
        result = subprocess.run(
            ["docker", "image", "save", "--output", str(archive_path), *images],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker image save failed: {result.stderr.strip()}")
        with archive_path.open("rb") as archive:
            if stream_contains_marker(archive, marker):
                raise RuntimeError("A local-secret sentinel was found in container image data.")
    finally:
        archive_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", help="Local container image references to inspect.")
    parser.add_argument(
        "--marker-environment",
        default=DEFAULT_MARKER_ENVIRONMENT,
        help="Environment variable containing the CI sentinel.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    marker_value = os.getenv(args.marker_environment, "")
    if len(marker_value) < 16:
        raise ValueError("The image secret sentinel must contain at least 16 characters.")
    verify_image_archives(args.images, marker_value.encode("utf-8"))
    print(f"Verified {len(args.images)} image archive(s) contain no local-secret sentinel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
