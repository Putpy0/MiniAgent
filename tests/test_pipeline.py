"""Offline tests for the 10-stage reasoning pipeline (FakeLLM, no network)."""

import json

import pytest

from miniagent.pipeline import (
    ALL_STAGE_IDS,
    PipelineContext,
    PipelineStageError,
    ReasoningPipeline,
    route_stages,
)
from miniagent.pipeline.stages import (
    load_stage_template,
    parse_frontmatter,
    render_template,
)


class FakeLLM:
    """Returns scripted JSON per stage; records prompts for assertions."""

    def __init__(self, scripted: dict[int, dict]):
        self.scripted = scripted
        self.prompts: dict[int, str] = {}

    def generate_json(self, prompt, schema_description=None, system_prompt=None, **kw):
        # The orchestrator prefixes every prompt with "[pipeline stage N: name]"
        for sid in range(1, 11):
            if f"[pipeline stage {sid}" in prompt:
                self.prompts[sid] = prompt
                out = self.scripted.get(sid, {"ok": True})
                if isinstance(out, Exception):
                    raise out
                return json.loads(json.dumps(out))
        raise AssertionError("prompt tidak memuat penanda stage")


def _intent(**overrides):
    base = {
        "intent": "uji",
        "complexity_indicator": "simple",
        "suggested_stages": [],
        "clarification_needed": False,
        "ambiguities": [],
    }
    base.update(overrides)
    return base


class TestRouter:
    def test_simple(self):
        assert route_stages("simple") == [1, 6, 10]

    def test_medium(self):
        assert route_stages("medium") == [1, 2, 4, 6, 7, 9, 10]

    def test_complex_runs_all(self):
        assert route_stages("complex") == ALL_STAGE_IDS

    def test_suggested_overrides_and_validates(self):
        assert route_stages("simple", suggested=[3, 99, 6]) == [3, 6]

    def test_unknown_complexity_falls_back_to_medium(self):
        assert route_stages("ngawur") == route_stages("medium")


class TestTemplates:
    def test_all_ten_prompts_load_with_placeholders(self):
        for sid in ALL_STAGE_IDS:
            tpl = load_stage_template(sid)
            assert "{{user_request}}" in tpl, sid
        fm = parse_frontmatter(8)
        assert fm.get("requires_executor") is True

    def test_render_fills_context(self):
        out = render_template("R={{user_request}} C={{context}} H={{history_marker}}", "tugas", "[]", '{"a":1}')
        assert "R=tugas" in out and '"a": 1' in out.replace(" ", "") or '"a":1' in out.replace(" ", "")
        assert "{{" not in out


class TestOrchestratorSimpleRoute:
    def test_simple_task_runs_only_1_6_10(self):
        llm = FakeLLM(
            {
                1: _intent(),
                6: {"code": "print('hi')"},
                10: {"summary": "selesai"},
            }
        )

        seen = []
        pipe = ReasoningPipeline(llm, on_stage=lambda sid, data: seen.append(sid))
        ctx = pipe.run("buat hello world")

        assert seen == [1, 6, 10]
        assert ctx.stage_outputs[6]["code"] == "print('hi')"
        # user_request threaded into the stage prompt
        assert "buat hello world" in llm.prompts[6]
        # stage outputs threaded into later prompts via {{context}}
        assert '"code"' in llm.prompts[10]

    def test_stage1_failure_is_fatal(self):
        class BoomLLM(FakeLLM):
            def generate_json(self, prompt, **kw):
                raise ValueError("bad json")

        with pytest.raises(PipelineStageError):
            ReasoningPipeline(BoomLLM({})).run("apa pun")

    def test_clarification_stops_pipeline(self):
        llm = FakeLLM(
            {
                1: _intent(clarification_needed=True, ambiguities=["db apa?"]),
                2: {"should": "not run"},
            }
        )
        ctx = ReasoningPipeline(llm).run("bangun api")
        assert ctx.stopped_reason == "needs_clarification"
        assert 2 not in ctx.stage_outputs


class TestExecutionStageGating:
    def _run_with_commands(self, commands, executor_cls):
        exec_out = {"commands": commands}
        llm = FakeLLM(
            {1: _intent(complexity_indicator="complex"), 8: exec_out}
        )
        executed = []

        class RecordingExecutor(executor_cls):
            pass

        pipe = ReasoningPipeline(llm, executor=RecordingExecutor())
        ctx = pipe.run("tugas kompleks")
        return ctx, executed

    def test_blocked_command_refused_without_execution(self, tmp_path):
        from miniagent.executor.subprocess_executor import SubprocessExecutor

        ran = []
        real_run = SubprocessExecutor.run_command

        def spy(self, cmd, **kw):
            ran.append(cmd)
            return real_run(self, cmd, **kw)

        import miniagent.executor.subprocess_executor as se

        se.SubprocessExecutor.run_command = spy
        try:
            llm = FakeLLM(
                {
                    1: _intent(complexity_indicator="complex"),
                    8: {"commands": ["dd if=/dev/urandom of=/dev/sda"]},
                }
            )
            pipe = ReasoningPipeline(llm)  # default executor, cwd ./workspace
            ctx = pipe.run("tugas")
        finally:
            se.SubprocessExecutor.run_command = real_run

        assert ctx.execution_results[0]["status"] == "refused"
        assert ran == []  # never reached the OS

    def test_safe_command_executed_and_results_threaded_to_stage9(self, tmp_path):
        from miniagent.executor.subprocess_executor import SubprocessExecutor

        ex = SubprocessExecutor(workspace_root=str(tmp_path), confirmation_callback=lambda c, r: True)
        llm = FakeLLM(
            {
                1: _intent(complexity_indicator="complex"),
                8: {"commands": ["echo pipedata"]},
                9: {"verdict": "ok"},
            }
        )
        ctx = ReasoningPipeline(llm, executor=ex).run("tugas")
        assert ctx.execution_results[0]["status"] == "executed"
        assert ctx.execution_results[0]["exit_code"] == 0
        assert "pipedata" in ctx.execution_results[0]["stdout"]
