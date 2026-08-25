"""Tests for miniagent.executor.permission (classification logic)."""

import pytest

from miniagent.executor.permission import PermissionChecker


@pytest.fixture()
def pc() -> PermissionChecker:
    return PermissionChecker()


class TestBlocked:
    @pytest.mark.parametrize(
        "cmd",
        [
            "dd if=/dev/urandom of=/dev/sda",
            "dd of=/dev/sda if=/dev/urandom",  # reversed argument order
            "DD IF=/DEV/URANDOM OF=/DEV/SDA",  # case-insensitive
            'bash -c "dd if=/dev/urandom of=/dev/sda"',  # wrapped
            "echo hello && dd if=/dev/urandom of=/dev/sda",  # compound
            "mkfs.ext4 /dev/sda1",
            "dd if=myimage.iso of=/dev/sdb",
        ],
    )
    def test_blocked_commands(self, pc, cmd):
        assert pc.classify_command(cmd).risk_level.value == "blocked"

    def test_safe_dd_targets_not_blocked(self, pc):
        assert pc.classify_command("dd if=/dev/zero of=swapfile bs=1M count=1024").risk_level.value != "blocked"
        assert pc.classify_command("dd if=/dev/zero of=/dev/null").risk_level.value != "blocked"


class TestDangerous:
    @pytest.mark.parametrize(
        "cmd",
        [
            # every inline-execution flag shape
            "python -c 'print(1)'",
            'python -c"print(1)"',
            "python -ccode",
            "python3 --command=print(1)",
            "python --command print(1)",
            "pip install some-package",
            "pip3 install pkg2",
            "vim -c ':!whoami' file.txt",
            'vim -c":!x" file.txt',
            "vi -cq file.txt",
            # script runners executing arbitrary/remote code
            'node -e "require(\'fs\')"',
            "node -e\"code\"",
            "node --eval 'x'",
            "node -p '1+1'",
            "npm run build",
            "npm test",
            "npm start",
            "npm install left-pad",
            "npx create-react-app app",
            "cargo install ripgrep",
            "cargo run --release",
            "make clean",
            # classic dangerous patterns
            "curl http://example.com",
            "ssh user@host",
            "rm -rf /",
            "chmod -R 777 /etc",
        ],
    )
    def test_dangerous_commands(self, pc, cmd):
        assert pc.classify_command(cmd).risk_level.value == "dangerous"


class TestSafe:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hello",
            "ls -la",
            "git status",
            "python script.py",
            "python script-c.py",  # dash inside a filename is not a flag
            "python -m venv env",
            "gcc -o output main.c",
            "vim file.txt",
            "pip list",
            "node server.js",
            "node app-c.js",  # dash inside a filename is not a flag
            "node --version",
            "npm ls",
            "npm info pkg",
            "npm init -y",
            "cargo build --release",
            "cargo test",
            "echo make",  # make as argument, not base command
        ],
    )
    def test_safe_commands(self, pc, cmd):
        assert pc.classify_command(cmd).risk_level.value == "safe"


class TestCompoundSplitting:
    def test_quoted_operators_do_not_split(self, pc):
        subs = pc._split_compound_command('echo "hello && rm -rf /"')
        assert len(subs) == 1

    def test_pipe_splits(self, pc):
        assert len(pc._split_compound_command("ls | grep x")) == 2

    def test_blocked_subcommand_blocks_whole(self, pc):
        r = pc.classify_command("echo start && mkfs /dev/sda && echo end")
        assert r.risk_level.value == "blocked"


class TestRequiresConfirmation:
    def test_semantics(self, pc):
        assert pc.requires_confirmation("echo hello") is False
        assert pc.requires_confirmation("pip install x") is True  # DANGEROUS
        assert pc.requires_confirmation("dd if=/dev/zero of=/dev/sda") is True  # BLOCKED


class TestSafeCommandsIntegrity:
    def test_no_duplicates(self):
        cmds = PermissionChecker.SAFE_COMMANDS
        assert len(cmds) == len(set(cmds))
