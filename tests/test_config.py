"""Tests for configuration loading and env-var resolution."""

import logging
import os

import pytest

from miniagent.config import MiniAgentConfig


def test_empty_yaml_returns_default(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    cfg = MiniAgentConfig.load_from_yaml(str(p))
    assert isinstance(cfg, MiniAgentConfig)


def test_comment_only_yaml_returns_default(tmp_path):
    p = tmp_path / "comments.yaml"
    p.write_text("# hanya komentar\n")
    cfg = MiniAgentConfig.load_from_yaml(str(p))
    assert isinstance(cfg, MiniAgentConfig)


def test_missing_file_returns_default():
    assert isinstance(MiniAgentConfig.load_from_yaml("does_not_exist_xyz.yaml"), MiniAgentConfig)


def test_yaml_env_resolution_and_unset_warning(tmp_path, caplog):
    os.environ["MA_TEST_SET"] = "resolved-value"
    try:
        p = tmp_path / "c.yaml"
        p.write_text(
            "llm:\n"
            "  primary: ${MA_TEST_SET}\n"
            "  api_keys:\n"
            "    groq: ${MA_TEST_UNSET}\n"
        )
        with caplog.at_level(logging.WARNING, logger="miniagent.config"):
            cfg = MiniAgentConfig.load_from_yaml(str(p))
        assert cfg.llm.primary == "resolved-value"
        assert cfg.llm.api_keys["groq"] == ""
        assert any("MA_TEST_UNSET" in r.message for r in caplog.records)
    finally:
        del os.environ["MA_TEST_SET"]


def test_programmatic_construction_resolves_env_too(monkeypatch):
    """Regression: previously only the YAML path resolved placeholders."""
    monkeypatch.setenv("MA_TEST_SET2", "prog-value")
    cfg = MiniAgentConfig(llm={"primary": "${MA_TEST_SET2}"}, skills_dir="${MA_TEST_SET2}")
    assert cfg.llm.primary == "prog-value"
    assert cfg.skills_dir == "prog-value"


def test_example_config_loads_without_stale_keys(repo_root):
    example = repo_root / "miniagent" / "config.example.yaml"
    cfg = MiniAgentConfig.load_from_yaml(str(example))
    fields = cfg.executor.model_dump().keys()
    assert "allow_dangerous" not in fields
