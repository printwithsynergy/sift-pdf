"""Tests for the sift-pdf CLI commands."""

from __future__ import annotations

import json

from click.testing import CliRunner

from sift_pdf.cli import main
from sift_pdf.version import SOLVER_SCHEMA_VERSIONS, VERSION


def test_version_command_prints_version() -> None:
    result = CliRunner().invoke(main, ["version"])
    assert result.exit_code == 0
    assert VERSION in result.output


def test_health_command_exits_clean() -> None:
    result = CliRunner().invoke(main, ["health"])
    assert result.exit_code == 0


def test_health_command_prints_json() -> None:
    result = CliRunner().invoke(main, ["health"])
    data = json.loads(result.output)
    assert "sift_version" in data
    assert data["sift_version"] == VERSION
    assert "codex" in data


def test_health_command_includes_codex_version() -> None:
    result = CliRunner().invoke(main, ["health"])
    data = json.loads(result.output)
    assert "version" in data["codex"]


def test_contract_command_exits_clean() -> None:
    result = CliRunner().invoke(main, ["contract"])
    assert result.exit_code == 0


def test_contract_command_prints_json() -> None:
    result = CliRunner().invoke(main, ["contract"])
    data = json.loads(result.output)
    assert data["contract_name"] == "sift-pdf"
    assert data["package_version"] == VERSION


def test_contract_command_includes_solver_schema_versions() -> None:
    result = CliRunner().invoke(main, ["contract"])
    data = json.loads(result.output)
    assert data["solver_schema_versions"] == SOLVER_SCHEMA_VERSIONS


def test_contract_command_includes_codex_section_versions() -> None:
    result = CliRunner().invoke(main, ["contract"])
    data = json.loads(result.output)
    assert "codex_section_versions" in data
    assert "geom" in data["codex_section_versions"]


def test_main_group_help_exits_clean() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "version" in result.output
    assert "health" in result.output
    assert "contract" in result.output
