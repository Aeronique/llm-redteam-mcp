"""Tests for the probe loader. No network required."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_redteam_mcp.probes import ProbeError, load_category, load_probes

# The real, shipped probe library at the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_DIR = REPO_ROOT / "probes"
EXPECTED_CATEGORIES = {
    "prompt_injection",
    "jailbreak",
    "system_prompt_leak",
    "data_exfiltration",
}


def test_bundled_library_loads() -> None:
    categories = load_probes(PROBE_DIR)
    assert set(categories) == EXPECTED_CATEGORIES
    for category in categories.values():
        assert category.probes, f"{category.name} has no probes"
        for probe in category.probes:
            assert probe.id
            assert probe.prompt
            assert probe.category == category.name


def test_leak_categories_install_system_prompt() -> None:
    categories = load_probes(PROBE_DIR)
    for name in ("system_prompt_leak", "data_exfiltration"):
        for probe in categories[name].probes:
            assert probe.system, f"{probe.id} should install a system prompt"
            assert probe.fail_markers, f"{probe.id} should define fail markers"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_required_field_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bad.yaml",
        "category: x\ndescription: y\nprobes:\n  - id: a\n    prompt: hi\n",
    )
    with pytest.raises(ProbeError, match="description"):
        load_category(path)


def test_duplicate_probe_id_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "dup.yaml",
        (
            "category: x\ndescription: y\nprobes:\n"
            "  - id: a\n    description: one\n    prompt: hi\n"
            "  - id: a\n    description: two\n    prompt: yo\n"
        ),
    )
    with pytest.raises(ProbeError, match="duplicate probe id"):
        load_category(path)


def test_empty_probes_list_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "empty.yaml", "category: x\ndescription: y\nprobes: []\n")
    with pytest.raises(ProbeError, match="non-empty list"):
        load_category(path)


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(ProbeError, match="probe directory not found"):
        load_probes(tmp_path / "does-not-exist")


def test_empty_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(ProbeError, match="no probe files"):
        load_probes(tmp_path)


def test_fail_markers_must_be_list(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "badmarkers.yaml",
        (
            "category: x\ndescription: y\nprobes:\n"
            "  - id: a\n    description: one\n    prompt: hi\n"
            "    fail_markers: not-a-list\n"
        ),
    )
    with pytest.raises(ProbeError, match="fail_markers"):
        load_category(path)
