"""Contract tests for CI container builds and inspectable security reports."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_builds_and_scans_all_runtime_images() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "container-images:" in workflow
    assert 'docker build --tag "$PYTHON_IMAGE" .' in workflow
    assert 'docker build --file services/scoper/Dockerfile --tag "$SCOPER_IMAGE" .' in workflow
    assert 'docker build --file apps/web/Dockerfile --tag "$WEB_IMAGE" .' in workflow
    assert workflow.count("uses: aquasecurity/trivy-action@v0.36.0") == 3
    assert workflow.count("version: v0.72.0") == 3
    assert "reports/python-vulnerabilities.json" in workflow
    assert "reports/scoper-vulnerabilities.json" in workflow
    assert "reports/web-vulnerabilities.json" in workflow
    assert "name: container-vulnerability-reports-${{ github.run_id }}" in workflow
    assert "retention-days: 14" in workflow


def test_ci_proves_ignored_local_secrets_do_not_enter_image_layers() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ignored_paths = ROOT.joinpath(".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored_paths
    assert ".env.*" in ignored_paths
    assert "Seed ignored local-secret sentinel" in workflow
    assert "python scripts/verify_image_secrets.py" in workflow
    assert ROOT.joinpath("scripts", "verify_image_secrets.py").is_file()
