"""Offline tests for LLMClient.chat_stream (no network)."""

import pytest

import miniagent.llm.client as llm_module
from miniagent.llm.client import LLMClient


class _FakeDelta:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, delta):
        self.delta = delta


class _FakeChunk:
    def __init__(self, content):
        self.choices = [_FakeChoice(_FakeDelta(content))]


def _client():
    from miniagent.config import LLMConfig

    return LLMClient(config=LLMConfig(primary="openrouter/test/model", api_keys={"openrouter": "k"}))


def test_stream_concatenates_deltas_and_skips_empty(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        yield _FakeChunk("ha")
        yield _FakeChunk("lo")
        yield _FakeChunk(None)
        yield _FakeChunk("!")

    monkeypatch.setattr(llm_module, "litellm_completion", fake_completion)
    got = list(_client().chat_stream("hi"))
    assert "".join(got) == "halo!"
    assert captured["stream"] is True
    assert captured["model"] == "openrouter/test/model"
    assert captured["api_key"] == "k"


def test_stream_builds_messages_with_system_prompt_and_history_copy(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        yield _FakeChunk("ok")

    monkeypatch.setattr(llm_module, "litellm_completion", fake_completion)
    history = [{"role": "user", "content": "lama"}]
    list(_client().chat_stream("baru", conversation_history=history, system_prompt="SYS"))
    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user", "user"]
    assert captured["messages"][0]["content"] == "SYS"
    assert history == [{"role": "user", "content": "lama"}]  # tidak termutasi


def test_stream_error_before_first_delta_propagates(monkeypatch):
    def fake_completion(**kwargs):
        raise RuntimeError("boom before stream")
        yield  # pragma: no cover

    monkeypatch.setattr(llm_module, "litellm_completion", fake_completion)
    with pytest.raises(RuntimeError):
        list(_client().chat_stream("hi"))
