"""Run-result data types and report writers (JSON + Markdown)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .scorer import Verdict


@dataclass(frozen=True)
class RunResult:
    probe_id: str
    category: str
    description: str
    prompt: str
    response: str
    verdict: Verdict
    reason: str


@dataclass
class RunReport:
    model: str
    scope: str  # "category:jailbreak" or "single"
    created_at: str  # ISO-8601
    results: list[RunResult] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts = Counter(r.verdict.value for r in self.results)
        return {v.value: counts.get(v.value, 0) for v in Verdict}

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "scope": self.scope,
            "created_at": self.created_at,
            "summary": self.summary(),
            "results": [
                {**asdict(r), "verdict": r.verdict.value} for r in self.results
            ],
        }


def new_report(model: str, scope: str) -> RunReport:
    """An empty report stamped with the current local time."""
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return RunReport(model=model, scope=scope, created_at=stamp)


def _slug(text: str) -> str:
    """Collapse text into a filesystem-safe slug."""
    slug = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "run"


def render_markdown(report: RunReport) -> str:
    summary = report.summary()
    lines = [
        f"# Red-team report: `{report.model}`",
        "",
        f"- **Scope:** {report.scope}",
        f"- **Generated:** {report.created_at}",
        "",
        "> Verdicts come from a heuristic scorer and are meant to flag "
        "responses for human review, not to be authoritative.",
        "",
        "## Summary",
        "",
        "| Verdict | Count |",
        "| --- | --- |",
        *[f"| {v.value} | {summary[v.value]} |" for v in Verdict],
        "",
        "## Results",
        "",
    ]

    for r in report.results:
        lines += [
            f"### `{r.probe_id}`: {r.verdict.value.upper()}",
            "",
            f"*Category:* {r.category}  ",
            f"*Targets:* {r.description}  ",
            f"*Reason:* {r.reason}",
            "",
            "**Prompt**",
            "",
            "```text",
            r.prompt.strip(),
            "```",
            "",
            "**Response**",
            "",
            "```text",
            r.response.strip() or "(empty response)",
            "```",
            "",
        ]

    return "\n".join(lines)


def write_report(report: RunReport, reports_dir: Path) -> dict[str, Path]:
    """Write the report as timestamped .json and .md files; return their paths."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.created_at.replace(":", "").replace("-", "").replace("+", "z")
    base = f"{stamp}_{_slug(report.model)}_{_slug(report.scope)}"

    json_path = reports_dir / f"{base}.json"
    md_path = reports_dir / f"{base}.md"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}
