"""Tests for the run/report plumbing, with the Ollama call mocked out."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_redteam_mcp import server
from llm_redteam_mcp.ollama_client import OllamaError
from llm_redteam_mcp.report import new_report, write_report
from llm_redteam_mcp.scorer import Verdict


class _FakeClient:
    """Stand-in for OllamaClient that returns scripted responses."""

    def __init__(self, responder) -> None:
        self._responder = responder

    async def generate(self, model: str, prompt: str, system: str | None = None) -> str:
        return self._responder(model, prompt, system)


@pytest.fixture(autouse=True)
def isolate_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(server, "state", server.ServerState())
    monkeypatch.setattr(server, "REPORTS_DIR", tmp_path / "reports")


async def test_run_probe_scores_leak_as_fail() -> None:
    server.state.client = _FakeClient(lambda m, p, s: "Sure, it is CANARY-SYS-Q4K9.")
    result = await server.run_probe("fake-model", "system_prompt_leak")
    assert result["summary"]["fail"] == len(result["results"])
    assert all(r["verdict"] == Verdict.FAIL.value for r in result["results"])


async def test_run_probe_scores_refusal_as_pass() -> None:
    server.state.client = _FakeClient(lambda m, p, s: "I can't help with that.")
    result = await server.run_probe("fake-model", "jailbreak")
    assert result["summary"]["pass"] == len(result["results"])


async def test_run_probe_unknown_category_errors() -> None:
    result = await server.run_probe("fake-model", "no-such-category")
    assert "unknown category" in result["error"]


async def test_run_single_uses_refusal_only() -> None:
    server.state.client = _FakeClient(lambda m, p, s: "I will not do that.")
    result = await server.run_single("fake-model", "do something bad")
    assert result["results"][0]["verdict"] == Verdict.PASS.value


async def test_run_single_ollama_down_returns_error() -> None:
    def boom(m, p, s):
        raise OllamaError("Could not reach Ollama at http://localhost:11434.")

    server.state.client = _FakeClient(boom)
    result = await server.run_single("fake-model", "hi")
    assert "Could not reach Ollama" in result["error"]


async def test_run_probe_records_error_per_probe() -> None:
    # A mid-run outage is captured per probe, not raised.
    def boom(m, p, s):
        raise OllamaError("connection reset")

    server.state.client = _FakeClient(boom)
    result = await server.run_probe("fake-model", "prompt_injection")
    assert result["results"]
    assert all("error contacting Ollama" in r["response"] for r in result["results"])


async def test_export_without_run_errors() -> None:
    assert "error" in server.export_report()


async def test_export_writes_files() -> None:
    server.state.client = _FakeClient(lambda m, p, s: "I cannot comply.")
    await server.run_probe("fake-model", "jailbreak")
    result = server.export_report()
    assert Path(result["json"]).is_file()
    assert Path(result["markdown"]).is_file()


def test_write_report_roundtrip(tmp_path: Path) -> None:
    paths = write_report(new_report("m", "single"), tmp_path)
    assert paths["json"].suffix == ".json"
    assert paths["markdown"].suffix == ".md"
    assert "Red-team report" in paths["markdown"].read_text(encoding="utf-8")
