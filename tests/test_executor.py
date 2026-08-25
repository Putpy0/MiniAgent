"""Tests for SubprocessExecutor: execution, sandboxing, error options."""

import os
import tempfile

import pytest

from conftest import HAS_COREUTILS

from miniagent.executor.subprocess_executor import SubprocessExecutor
from miniagent.executor.workflow_context import WorkflowContext

pytestmark = pytest.mark.skipif(not HAS_COREUTILS, reason="requires POSIX coreutils (Git usr/bin on Windows)")


@pytest.fixture()
def ws():
    with tempfile.TemporaryDirectory() as d:
        yield d


def approve(_cmd, _reason):
    return True


class TestExecution:
    def test_trivial_command(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        r = ex.run_command("echo hello")
        assert r.exit_code == 0 and "hello" in r.stdout

    def test_blocked_command_raises(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        with pytest.raises(PermissionError):
            ex.run_command("dd if=/dev/urandom of=/dev/sda")

    def test_dangerous_fails_closed_without_callback(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        with pytest.raises(PermissionError):
            ex.run_command("env")

    def test_api_key_not_leaked(self, ws, monkeypatch):
        monkeypatch.setenv("FAKE_TEST_API_KEY", "super-secret")
        ex = SubprocessExecutor(workspace_root=ws, confirmation_callback=approve)
        r = ex.run_command("env")
        assert "super-secret" not in r.stdout

    def test_in_workspace_copy_allowed_with_callback(self, ws):
        ex = SubprocessExecutor(workspace_root=ws, confirmation_callback=approve)
        with open(os.path.join(ws, "file1.txt"), "w") as f:
            f.write("isi")
        ex.run_command("cp file1.txt file2.txt")
        assert os.path.exists(os.path.join(ws, "file2.txt"))


class TestPathContainment:
    @pytest.mark.parametrize(
        "probe",
        [
            "tee ~/pwned.txt",
            "tee //server/share/pwned.txt",
            "cat ../../outside_secret.txt",
            "cat ..\\..\\outside_secret.txt",  # backslash traversal (shlex strips them)
        ],
    )
    def test_outside_paths_denied(self, ws, probe):
        ex = SubprocessExecutor(workspace_root=ws)
        with pytest.raises(PermissionError):
            ex.run_command(probe, timeout=3)

    def test_drive_letter_abs_denied(self, ws):
        with tempfile.TemporaryDirectory() as outside:
            ex = SubprocessExecutor(workspace_root=ws)
            with pytest.raises(PermissionError):
                ex.run_command(f"tee {os.path.join(outside, 'p.txt')}", timeout=3)

    def test_cwd_outside_workspace_rejected(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        with pytest.raises(ValueError):
            ex.validate_path("../outside.txt")

    def test_internal_normalization_allowed(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        assert ex.validate_path("sub/../ok.txt")


class TestSymlinkEscape:
    def test_read_via_symlink_denied(self, ws):
        outside_file = os.path.join(os.path.dirname(ws), "_outside_target.txt")
        with open(outside_file, "w") as f:
            f.write("TOPSECRET")
        link = os.path.join(ws, "link.txt")
        try:
            os.symlink(outside_file, link)
        except OSError:
            pytest.skip("symlinks unsupported on this platform/user")
        ex = SubprocessExecutor(workspace_root=ws)
        with pytest.raises(ValueError):
            ex.read_file("link.txt")


class TestRaiseOnError:
    def test_default_returns_result(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        r = ex.run_command("command_yang_tidak_ada_xyz123")
        assert r.exit_code == -1

    def test_true_raises_runtime_error(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        with pytest.raises(RuntimeError):
            ex.run_command("command_yang_tidak_ada_xyz123", raise_on_error=True)

    def test_success_still_returns_result(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        r = ex.run_command("echo hello", raise_on_error=True)
        assert r.exit_code == 0

    def test_timeout_raises_and_logs_audit(self, ws):
        log_path = os.path.join(ws, "audit.log")
        ex = SubprocessExecutor(workspace_root=ws, log_file=log_path)
        with pytest.raises(TimeoutError):
            ex.run_command("sleep 5", timeout=1, raise_on_error=True)
        assert os.path.exists(log_path) and "timed out" in open(log_path).read().lower()


class TestWorkflowStepSemantics:
    def test_approved_vs_succeeded(self, ws):
        ex = SubprocessExecutor(workspace_root=ws)
        wc = WorkflowContext(executor=ex)

        wc.act("failing command", "false")  # executed, exit 1
        step = wc.steps[-1]
        assert step.approved is True
        assert step.succeeded is False

        wc.act("ok command", "echo hello")
        step2 = wc.steps[-1]
        assert step2.approved is True
        assert step2.succeeded is True
