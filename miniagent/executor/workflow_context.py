"""Thin workflow layer over Executor: plan -> act -> observe -> checkpoint."""

from dataclasses import dataclass, field
from typing import Optional

from miniagent.executor.base import Executor, ExecutionResult


@dataclass
class WorkflowStep:
    """One recorded step in a workflow: intent, action, and result."""

    intent: str
    command: str
    result: Optional[ExecutionResult] = None
    # True means the command was allowed AND executed - NOT that it succeeded
    approved: bool = False

    @property
    def succeeded(self) -> bool:
        """True if the command was executed AND its outcome was successful."""
        return self.result.success if self.result else False


class WorkflowContext:
    """
    Wraps an Executor to record intent-annotated steps. Does not replace
    Executor's safety checks (BLOCKED/DANGEROUS/confirmation_callback still
    apply unchanged) — only adds a lightweight audit trail of intent +
    outcome per step, capped in memory to avoid unbounded growth.
    """

    def __init__(self, executor: Executor, max_history: int = 100):
        self.executor = executor
        self.max_history = max_history
        self.steps: list[WorkflowStep] = []

    def act(self, intent: str, command: str, **run_command_kwargs) -> ExecutionResult:
        step = WorkflowStep(intent=intent, command=command)
        try:
            result = self.executor.run_command(command, **run_command_kwargs)
            step.result = result
            step.approved = True
            return result
        finally:
            self._record(step)

    def _record(self, step: WorkflowStep) -> None:
        self.steps.append(step)
        if len(self.steps) > self.max_history:
            self.steps.pop(0)

    def recent_steps(self, n: int = 10) -> list[WorkflowStep]:
        return self.steps[-n:]

    def summary(self) -> str:
        lines = []
        for i, step in enumerate(self.steps, 1):
            status = "✓" if (step.result and step.result.success) else "✗"
            lines.append(f"{i}. [{status}] {step.intent} -> `{step.command}`")
        return "\n".join(lines) if lines else "(no steps recorded yet)"
