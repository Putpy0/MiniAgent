"""Offline tests for the chat CLI helpers (no network)."""

import os

from miniagent.cli_chat import (
    FREE_MODEL_CANDIDATES,
    MAX_TOOL_CALLS_PER_TURN,
    SYSTEM_PROMPT_TEMPLATE,
    load_api_key,
    parse_run_blocks,
)


class TestParseRunBlocks:
    def test_extracts_run_block(self):
        text = 'Saya buat filenya.\n```run\necho halo > a.txt\n```'
        assert parse_run_blocks(text) == ["echo halo > a.txt"]

    def test_accepts_shell_aliases(self):
        for tag in ("shell", "bash", "sh"):
            text = "```" + tag + "\nls -la\n```"
            assert parse_run_blocks(text) == ["ls -la"]

    def test_ignores_plain_code_fence(self):
        text = "Contoh:\n```python\nprint('hi')\n```\nSelesai."
        assert parse_run_blocks(text) == []

    def test_multiline_block_yields_each_line(self):
        text = "```run\necho satu\necho dua\n```\n```run\necho tiga\n```"
        assert parse_run_blocks(text) == ["echo satu", "echo dua", "echo tiga"]

    def test_skips_comments_and_blank_lines(self):
        text = "```run\n# komentar\necho x\n\n```"
        assert parse_run_blocks(text) == ["echo x"]

    def test_caps_tool_calls_per_turn(self):
        lines = "\n".join(f"echo n{i}" for i in range(10))
        text = "```run\n" + lines + "\n```"
        assert len(parse_run_blocks(text)) == MAX_TOOL_CALLS_PER_TURN

    def test_empty_text(self):
        assert parse_run_blocks("") == []
        assert parse_run_blocks(None) == []


class TestLoadApiKey:
    def test_env_var_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-from-env")
        key, source = load_api_key(tmp_path)
        assert key == "sk-from-env"
        assert source == "environment"

    def test_sibling_key_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        (tmp_path / ".openrouter_key").write_text("sk-or-file-key\n")
        key, source = load_api_key(cfg)
        assert key == "sk-or-file-key"
        assert source.endswith(".openrouter_key")

    def test_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        key, _ = load_api_key(tmp_path / "missing.yaml")
        assert key is None


def test_system_prompt_contains_protocol():
    rendered = SYSTEM_PROMPT_TEMPLATE.format(workspace="C:/ws")
    assert "C:/ws" in rendered
    assert "```run" in rendered
    assert "NEVER invent" in rendered


def test_free_candidates_are_free_tier_ids():
    assert all(c.startswith("openrouter/") for c in FREE_MODEL_CANDIDATES)
    assert all(":free" in c or c.endswith("/free") is False for c in FREE_MODEL_CANDIDATES)
