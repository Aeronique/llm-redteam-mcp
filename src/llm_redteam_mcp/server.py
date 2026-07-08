"""The MCP server: wires the probes, the Ollama client, and the scorer together.

Runs over stdio and exposes five tools: list_models, list_probes, run_probe,
run_single, and export_report. The last run is kept in memory so export_report
can write it without re-running any prompts.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .ollama_client import OllamaClient, OllamaError
from .probes import Probe, ProbeError, load_probes
from .report import RunReport, RunResult, new_report, write_report
from .scorer import score


def _env_path(var: str, default: Path) -> Path:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else default


# Default to the current working directory; override via env when the MCP
# client launches the server from somewhere else.
PROBE_DIR = _env_path("LLM_REDTEAM_PROBE_DIR", Path.cwd() / "probes")
REPORTS_DIR = _env_path("LLM_REDTEAM_REPORTS_DIR", Path.cwd() / "reports")
OLLAMA_URL = os.environ.get("LLM_REDTEAM_OLLAMA_URL", "http://localhost:11434")


class ServerState:
    def __init__(self) -> None:
        self.client = OllamaClient(OLLAMA_URL)
        self.last_report: RunReport | None = None

    def load(self) -> dict:
        return load_probes(PROBE_DIR)


state = ServerState()
mcp = FastMCP("llm-redteam-mcp")


@mcp.tool()
async def list_models() -> dict:
    """List the models installed in the local Ollama instance."""
    try:
        models = await state.client.list_models()
    except OllamaError as exc:
        return {"error": str(exc)}
    return {
        "models": [
            {
                "name": m.name,
                "size_bytes": m.size_bytes,
                "family": m.family,
                "parameter_size": m.parameter_size,
            }
            for m in models
        ]
    }


@mcp.tool()
def list_probes() -> dict:
    """List every probe category and the probes it contains."""
    try:
        categories = state.load()
    except ProbeError as exc:
        return {"error": str(exc)}
    return {
        "categories": {
            name: {
                "description": cat.description,
                "probes": [
                    {
                        "id": p.id,
                        "description": p.description,
                        "installs_system_prompt": p.system is not None,
                        "fail_markers": p.fail_markers,
                    }
                    for p in cat.probes
                ],
            }
            for name, cat in categories.items()
        }
    }


async def _run(model: str, probes: list[Probe], scope: str) -> RunReport:
    report = new_report(model=model, scope=scope)
    for probe in probes:
        try:
            response = await state.client.generate(
                model, probe.prompt, system=probe.system
            )
            scored = score(response, probe.fail_markers)
            verdict, reason = scored.verdict, scored.reason
        except OllamaError as exc:
            # Record the failure per-probe so a mid-run outage still yields a
            # usable, exportable report.
            response = f"[error contacting Ollama: {exc}]"
            verdict = score(response, probe.fail_markers).verdict
            reason = "Ollama request failed; see response text."

        report.results.append(
            RunResult(
                probe_id=probe.id,
                category=probe.category,
                description=probe.description,
                prompt=probe.prompt,
                response=response,
                verdict=verdict,
                reason=reason,
            )
        )
    return report


@mcp.tool()
async def run_probe(model: str, category: str) -> dict:
    """Run every probe in a category against a model and score each response."""
    try:
        categories = state.load()
    except ProbeError as exc:
        return {"error": str(exc)}

    if category not in categories:
        return {
            "error": f"unknown category '{category}'. "
            f"Available: {', '.join(categories) or '(none)'}"
        }

    report = await _run(model, categories[category].probes, f"category:{category}")
    state.last_report = report
    return report.to_dict()


@mcp.tool()
async def run_single(model: str, prompt: str) -> dict:
    """Run one ad-hoc prompt against a model and score the response.

    An ad-hoc prompt has no fail markers, so the verdict is `pass` only if the
    model clearly refuses and `needs_review` otherwise.
    """
    report = new_report(model=model, scope="single")
    try:
        response = await state.client.generate(model, prompt)
    except OllamaError as exc:
        return {"error": str(exc)}

    scored = score(response)
    report.results.append(
        RunResult(
            probe_id="ad-hoc",
            category="single",
            description="Ad-hoc single prompt supplied by the caller.",
            prompt=prompt,
            response=response,
            verdict=scored.verdict,
            reason=scored.reason,
        )
    )
    state.last_report = report
    return report.to_dict()


@mcp.tool()
def export_report() -> dict:
    """Write the most recent run to timestamped JSON and Markdown in ./reports."""
    if state.last_report is None:
        return {"error": "no run to export yet; call run_probe or run_single first."}

    paths = write_report(state.last_report, REPORTS_DIR)
    return {
        "json": str(paths["json"]),
        "markdown": str(paths["markdown"]),
        "summary": state.last_report.summary(),
    }


def run() -> None:
    """Start the MCP server over stdio."""
    mcp.run()
