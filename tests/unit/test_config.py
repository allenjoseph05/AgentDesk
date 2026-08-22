"""Repository-local environment loading tests."""

import os
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import packages.config as project_config

ROOT = Path(__file__).resolve().parents[2]


def test_project_environment_loads_dotenv_without_overriding_process_values(
    monkeypatch,
) -> None:
    test_root = Path(__file__).resolve().parents[2] / ".test-environments" / uuid4().hex
    test_root.mkdir(parents=True)
    try:
        (test_root / ".env").write_text(
            "RESEARCH_AGENT_URL=http://127.0.0.1:9005\nANALYST_AGENT_URL=http://127.0.0.1:9006\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(project_config, "PROJECT_ROOT", test_root)
        monkeypatch.delenv("RESEARCH_AGENT_URL", raising=False)
        monkeypatch.setenv("ANALYST_AGENT_URL", "http://explicit.example:8006")

        project_config.load_project_environment()

        assert project_config.PROJECT_ROOT == test_root
        assert os.environ["RESEARCH_AGENT_URL"] == "http://127.0.0.1:9005"
        assert os.environ["ANALYST_AGENT_URL"] == "http://explicit.example:8006"
    finally:
        (test_root / ".env").unlink(missing_ok=True)
        test_root.rmdir()
        with suppress(OSError):
            test_root.parent.rmdir()


def test_example_environment_uses_runtime_registry_names() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "RESEARCH_AGENT_URL=http://127.0.0.1:8005" in example
    assert "ANALYST_AGENT_URL=http://127.0.0.1:8006" in example
    assert "VERIFIER_AGENT_URL=http://127.0.0.1:8007" in example
    assert "AGENTDESK_AUTH_MODE=local" in example
    assert "AGENTDESK_BROWSER_TOKEN=" in example
    assert "AGENTDESK_SERVICE_TOKEN=" in example
    assert "RESEARCHER_URL=" not in example
    assert "ANALYST_URL=" not in example
