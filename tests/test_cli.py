"""Tests for the miniagent CLI (no network, no shell execution)."""

import os

from typer.testing import CliRunner

from miniagent.cli import app

runner = CliRunner()


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "miniagent" in result.output


def test_doctor_with_default_config():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "loaded OK" in result.output


def test_doctor_reports_missing_api_keys(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "llm:\n"
        "  primary: openrouter/test/model\n"
        "  api_keys:\n"
        "    openrouter: ${MA_CLI_TEST_UNSET_KEY}\n"
    )
    env = dict(os.environ)
    env.pop("MA_CLI_TEST_UNSET_KEY", None)
    result = runner.invoke(app, ["doctor", "--config", str(cfg)], env=env)
    assert result.exit_code == 0
    assert "missing/empty" in result.output


def test_skills_lists_discovered_skills(tmp_path):
    skill_dir = tmp_path / "skills"
    (skill_dir / "demo").mkdir(parents=True)
    (skill_dir / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: A demo skill\ntriggers: [demo]\n---\nbody"
    )
    result = runner.invoke(app, ["skills", str(skill_dir)])
    assert result.exit_code == 0
    assert "demo" in result.output
