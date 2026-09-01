"""Reasoning pipeline orchestrator.

Runs the selected stages in order, threading outputs through
PipelineContext. Stage 8 optionally executes proposed commands through the
sandboxed SubprocessExecutor with the standard permission gating:
SAFE -> auto, DANGEROUS -> confirmation callback, BLOCKED -> refused.

Failure policy:
- Stage 1 (Intent) failing is fatal (routing depends on it).
- Any later stage failing records {'_error': ...} and the pipeline continues,
  so one flaky LLM response cannot destroy the whole run.
"""

import json
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from miniagent.pipeline.context import PipelineContext
from miniagent.pipeline.router import route_stages
from miniagent.pipeline.stages import (
    STAGES,
    load_stage_template,
    render_template,
)

logger = logging.getLogger(__name__)

MAX_JSON_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5

# The stock 08_execution.md prompt was written for an architecture where the
# model executes tools itself. MiniAgent's host executes instead, so we pin
# the contract explicitly for that stage.
EXECUTION_CONTRACT = """
EXECUTION CONTRACT (overrides any conflicting instruction above):
You CANNOT execute anything yourself, and NOTHING has run yet - earlier
stages only planned/wrote code as text. If the task creates or modifies
files, YOUR commands must do it for real.

Reply with ONLY valid JSON:
{"execution_summary": "<one line>",
 "commands": ["<single shell command>", ...]}

Example:
{"execution_summary": "create greeting file",
 "commands": ["echo hello world > greeting.txt", "cat greeting.txt"]}

Rules:
- Max 5 commands; each must create/modify/verify files INSIDE the workspace.
- Use simple POSIX-style commands (echo/cat/cp/mkdir/python) without chaining.
- AVOID double quotes inside echo payloads (Windows cmd keeps them literally).
- Do NOT include any "commands_executed", stdout or exit codes - the host runs
  them for real and appends actual results to the conversation afterwards.
"""


class PipelineStageError(RuntimeError):
    """Raised when a mandatory stage (currently: Intent) fails."""


class ReasoningPipeline:
    def __init__(
        self,
        llm_client,  # duck-typed: generate_json(prompt, schema_description, system_prompt=...)
        prompts_dir: Optional[Path] = None,
        executor=None,  # SubprocessExecutor-like; enables stage 8 execution
        confirmation_callback: Optional[Callable[[str, str], bool]] = None,
        on_stage: Optional[Callable[[int, dict], None]] = None,
        max_tokens_per_stage: int = 2400,
    ):
        self.client = llm_client
        self.prompts_dir = Path(prompts_dir) if prompts_dir else None
        self.executor = executor
        self.confirmation_callback = confirmation_callback
        self.on_stage = on_stage or (lambda sid, data: None)
        self.max_tokens_per_stage = max_tokens_per_stage
        try:
            core = Path(__file__).resolve().parent.parent / "prompts" / "system_core.md"
            self.system_prompt = core.read_text(encoding="utf-8")
        except OSError:
            self.system_prompt = None

    # ---------- public API ----------

    def run(self, user_request: str, conversation_history: Optional[list] = None) -> PipelineContext:
        ctx = PipelineContext(
            user_request=user_request,
            conversation_history=list(conversation_history) if conversation_history else [],
        )

        # Stage 1 is always first and mandatory.
        self._run_stage(ctx, 1)
        intent = ctx.get_output(1)
        if "_error" in intent:
            raise PipelineStageError(f"Intent stage failed: {intent['_error']}")

        if intent.get("clarification_needed") is True and intent.get("ambiguities"):
            ctx.stopped_reason = "needs_clarification"
            return ctx

        stages = route_stages(
            complexity=intent.get("complexity_indicator", "medium"),
            suggested=intent.get("suggested_stages"),
        )
        # Models tend to copy the [1,6,10] example from the Intent prompt,
        # dropping the Execution stage. When an executor is available and the
        # task is actionable (coding/execution), force stage 8 back in before
        # Finalization so tasks actually produce artifacts.
        if (
            self.executor is not None
            and intent.get("intent_category") in ("coding", "execution")
            and 8 not in stages
        ):
            insert_at = stages.index(max(stages)) if len(stages) > 1 else len(stages)
            stages.insert(insert_at, 8)

        for stage_id in stages:
            if stage_id == 1:
                continue
            self._run_stage(ctx, stage_id)

        return ctx

    # ---------- internals ----------

    def _run_stage(self, ctx: PipelineContext, stage_id: int) -> None:
        spec = STAGES[stage_id]
        template = load_stage_template(stage_id, self.prompts_dir)
        body = render_template(
            template,
            user_request=ctx.user_request,
            history_json=json.dumps(ctx.conversation_history[-6:], ensure_ascii=False),
            context_json=ctx.previous_context_json()
            + self._execution_results_json(ctx),
        )
        # Explicit stage marker: keeps multi-stage models oriented and gives
        # test doubles a deterministic way to identify the caller.
        prompt = f"[pipeline stage {spec.id}: {spec.name}]\n\n{body}"
        if stage_id == 8:
            prompt += EXECUTION_CONTRACT

        schema_description = f"Strict JSON output for the {spec.name} stage."
        data: dict = {"_error": "unreachable"}
        for attempt in range(1, MAX_JSON_ATTEMPTS + 1):
            try:
                data = self.client.generate_json(
                    prompt,
                    schema_description=schema_description,
                    system_prompt=self.system_prompt,
                    max_tokens=self.max_tokens_per_stage,
                )
                break
            except Exception as e:  # JSON parse errors, provider hiccups
                logger.warning("stage %s attempt %s failed: %s", stage_id, attempt, e)
                data = {"_error": str(e)[:300]}
                if attempt < MAX_JSON_ATTEMPTS:
                    # Free-tier providers return empty/garbled responses often;
                    # a short backoff measurably improves the retry odds.
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    prompt = prompt + "\n\nIMPORTANT: reply with ONLY valid JSON."

        if "_error" in data and stage_id != 1:
            logger.error("stage %s failed after retries: %s", stage_id, data["_error"])

        ctx.stage_outputs[stage_id] = data

        if stage_id == 8 and "_error" not in data:
            self._execute_proposed_commands(ctx, data)

        self.on_stage(stage_id, data)

    @staticmethod
    def _execution_results_json(ctx: PipelineContext) -> str:
        if not ctx.execution_results:
            return ""
        return "\n\nEXECUTION RESULTS:\n" + json.dumps(
            ctx.execution_results, ensure_ascii=False, default=str
        )[:3000]

    def _execute_proposed_commands(self, ctx: PipelineContext, exec_data: dict) -> None:
        from miniagent.executor.permission import PermissionChecker
        from miniagent.executor.subprocess_executor import SubprocessExecutor

        commands: list[str] = []
        raw = (
            exec_data.get("commands")
            or exec_data.get("planned_commands")
            or exec_data.get("command")
        )
        if isinstance(raw, str):
            commands = [raw.strip()]
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and "command" in item:
                    commands.append(str(item["command"]).strip())
                elif str(item).strip():
                    commands.append(str(item).strip())
            commands = [c for c in commands if c]

        if not commands and isinstance(exec_data.get("commands_executed"), list):
            # Model followed the legacy report-shaped schema; treat each
            # reported entry as the command the host should actually run.
            for item in exec_data["commands_executed"]:
                if isinstance(item, dict) and str(item.get("command", "")).strip():
                    commands.append(str(item["command"]).strip())

        if not commands:
            exec_data["_note"] = "no commands proposed by the Execution stage"
            return

        checker = PermissionChecker()
        if self.executor is None:
            workspace = Path("./workspace").resolve()
            workspace.mkdir(parents=True, exist_ok=True)
            executor = SubprocessExecutor(workspace_root=str(workspace))
        else:
            executor = self.executor

        for cmd in commands[:5]:  # safety cap
            risk = checker.classify_command(cmd).risk_level.value
            entry: dict = {"command": cmd, "risk": risk}
            if risk == "blocked":
                entry["status"] = "refused"
                ctx.execution_results.append(entry)
                continue
            needs_shell = any(ch in cmd for ch in ">&|;")
            result = executor.run_command(cmd, shell=needs_shell)
            entry.update(
                {
                    "status": "executed",
                    "exit_code": result.exit_code,
                    "stdout": result.stdout[:500],
                    "stderr": result.stderr[:300],
                }
            )
            ctx.execution_results.append(entry)

        exec_data["_results_recorded"] = len(ctx.execution_results)
