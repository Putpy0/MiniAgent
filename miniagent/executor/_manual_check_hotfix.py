"""Manual smoke test for the hotfix/main-import-broken branch.

Run directly:
    python miniagent/executor/_manual_check_hotfix.py

All 6 tests must print OK before the hotfix is considered done.

Platform notes (Windows):
- Commands such as cp/env/tee come from Git for Windows coreutils. Add
  C:\\Program Files\\Git\\usr\\bin to PATH before running this script,
  otherwise those executables are not found by subprocess.
- Test 5 (cp) and Test 6 (env) use commands that are DANGEROUS by design
  (they are members of PermissionChecker.DANGEROUS_BASE_COMMANDS). They are
  constructed with a confirmation_callback that approves execution - the
  official approval path. Without any callback these commands correctly
  fail closed with PermissionError, which is expected behavior.
"""

import os
import sys
import tempfile

sys.path.insert(0, ".")

from miniagent.executor.permission import PermissionChecker
from miniagent.executor.subprocess_executor import SubprocessExecutor


def approve(_command: str, _reason: str) -> bool:
    """Simulated user approval for DANGEROUS commands under test."""
    return True


def test_1_import() -> None:
    print("=== Test 1: import berhasil ===")
    print("OK")


def test_2_trivial_command() -> None:
    print("=== Test 2: command sepele harus jalan ===")
    with tempfile.TemporaryDirectory() as ws:
        ex = SubprocessExecutor(workspace_root=ws)
        r = ex.run_command("echo hello")
        assert r.exit_code == 0, f"GAGAL: exit_code={r.exit_code}, stderr={r.stderr}"
        assert "hello" in r.stdout, f"GAGAL: stdout={r.stdout!r}"
        print("OK")


def test_3_blocked_command_rejected() -> None:
    print("=== Test 3: BLOCKED command tetap ditolak ===")
    with tempfile.TemporaryDirectory() as ws:
        ex = SubprocessExecutor(workspace_root=ws)
        try:
            ex.run_command("dd if=/dev/urandom of=/dev/sda")
            print("GAGAL: seharusnya ditolak")
        except PermissionError:
            print("OK")


def test_4_path_traversal_rejected() -> None:
    print("=== Test 4: path traversal via argumen command HARUS ditolak ===")
    with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as outside:
        target = os.path.join(outside, "pwned.txt")
        ex = SubprocessExecutor(workspace_root=ws)
        try:
            ex.run_command(f"tee {target}", timeout=3)
            print(f"GAGAL: file dibuat? {os.path.exists(target)}")
        except PermissionError as e:
            print("OK -", e)


def test_5_command_inside_workspace_allowed() -> None:
    print("=== Test 5: command dalam workspace tetap boleh jalan ===")
    with tempfile.TemporaryDirectory() as ws:
        ex = SubprocessExecutor(workspace_root=ws, confirmation_callback=approve)
        with open(os.path.join(ws, "file1.txt"), "w") as f:
            f.write("isi")
        r = ex.run_command("cp file1.txt file2.txt")
        exists = os.path.exists(os.path.join(ws, "file2.txt"))
        print("OK" if exists else f"GAGAL: {r.stderr}")


def test_6_api_key_not_leaked() -> None:
    print("=== Test 6: API key tidak bocor ke subprocess env ===")
    os.environ["FAKE_TEST_API_KEY"] = "super-rahasia-jangan-bocor"
    try:
        with tempfile.TemporaryDirectory() as ws:
            ex = SubprocessExecutor(workspace_root=ws, confirmation_callback=approve)
            r = ex.run_command("env")
            if "super-rahasia-jangan-bocor" in r.stdout:
                print("GAGAL: API key bocor")
            else:
                print("OK")
    finally:
        del os.environ["FAKE_TEST_API_KEY"]


def test_7_dd_regex_no_false_positive() -> None:
    print("=== Test 7: dd regex - device target BLOCKED, target aman tidak ===")
    pc = PermissionChecker()
    # Device sebagai OUTPUT target (urutan argumen apapun) harus tetap blocked
    assert (
        pc.classify_command("dd if=/dev/urandom of=/dev/sda").risk_level.value == "blocked"
    ), "GAGAL: dd of=/dev/sda seharusnya blocked"
    assert (
        pc.classify_command("dd of=/dev/sda if=/dev/urandom").risk_level.value == "blocked"
    ), "GAGAL: urutan dibalik seharusnya tetap blocked"
    assert (
        pc.classify_command("dd if=myimage.iso of=/dev/sdb").risk_level.value
        in ("blocked", "dangerous")
    ), "GAGAL: dd of=/dev/sdb seharusnya blocked/dangerous"
    # Target aman TIDAK boleh blocked (dd sendiri tetap dangerous via base list)
    r1 = pc.classify_command("dd if=/dev/zero of=swapfile bs=1M count=1024")
    assert r1.risk_level.value != "blocked", f"MASIH FALSE POSITIVE: {r1.risk_level.value}"
    r2 = pc.classify_command("dd if=/dev/zero of=/dev/null")
    assert r2.risk_level.value != "blocked", f"MASIH FALSE POSITIVE: {r2.risk_level.value}"
    print(f"OK (swapfile -> {r1.risk_level.value}, /dev/null -> {r2.risk_level.value})")


if __name__ == "__main__":
    test_1_import()
    test_2_trivial_command()
    test_3_blocked_command_rejected()
    test_4_path_traversal_rejected()
    test_5_command_inside_workspace_allowed()
    test_6_api_key_not_leaked()
    test_7_dd_regex_no_false_positive()
