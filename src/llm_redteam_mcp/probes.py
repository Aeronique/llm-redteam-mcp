"""Loading and validation of the YAML probe library.

Each file describes one category of test. Validation is strict so a malformed
probe fails at load time instead of quietly producing meaningless verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ProbeError(ValueError):
    """A probe file is missing a required field or is otherwise malformed."""


@dataclass(frozen=True)
class Probe:
    id: str
    category: str
    description: str
    prompt: str
    # Optional system prompt; leak/exfil probes use it to plant a secret.
    system: str | None = None
    # Strings whose presence in the response means the guardrail was bypassed.
    fail_markers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProbeCategory:
    name: str
    description: str
    probes: list[Probe]


def _require(mapping: dict, key: str, source: str) -> object:
    if key not in mapping:
        raise ProbeError(f"{source}: missing required field '{key}'")
    return mapping[key]


def _parse_category(data: dict, source: str) -> ProbeCategory:
    if not isinstance(data, dict):
        raise ProbeError(f"{source}: top level must be a mapping")

    name = str(_require(data, "category", source))
    description = str(_require(data, "description", source))
    raw_probes = _require(data, "probes", source)
    if not isinstance(raw_probes, list) or not raw_probes:
        raise ProbeError(f"{source}: 'probes' must be a non-empty list")

    probes: list[Probe] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_probes):
        where = f"{source}[probe #{index}]"
        if not isinstance(raw, dict):
            raise ProbeError(f"{where}: each probe must be a mapping")

        probe_id = str(_require(raw, "id", where))
        if probe_id in seen_ids:
            raise ProbeError(f"{where}: duplicate probe id '{probe_id}'")
        seen_ids.add(probe_id)

        markers = raw.get("fail_markers") or []
        if not isinstance(markers, list):
            raise ProbeError(f"{where}: 'fail_markers' must be a list")

        probes.append(
            Probe(
                id=probe_id,
                category=name,
                description=str(_require(raw, "description", where)),
                prompt=str(_require(raw, "prompt", where)),
                system=str(raw["system"]) if raw.get("system") else None,
                fail_markers=[str(m) for m in markers],
            )
        )

    return ProbeCategory(name=name, description=description, probes=probes)


def load_category(path: Path) -> ProbeCategory:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProbeError(f"{path.name}: invalid YAML: {exc}") from exc
    return _parse_category(raw, path.name)


def load_probes(probe_dir: Path) -> dict[str, ProbeCategory]:
    """Load every *.yaml/*.yml file in probe_dir, keyed by category name."""
    if not probe_dir.is_dir():
        raise ProbeError(f"probe directory not found: {probe_dir}")

    files = sorted(probe_dir.glob("*.yaml")) + sorted(probe_dir.glob("*.yml"))
    if not files:
        raise ProbeError(f"no probe files (*.yaml) found in {probe_dir}")

    categories: dict[str, ProbeCategory] = {}
    for path in files:
        category = load_category(path)
        if category.name in categories:
            raise ProbeError(f"duplicate category '{category.name}' in {path.name}")
        categories[category.name] = category

    return dict(sorted(categories.items()))
