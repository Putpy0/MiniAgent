"""Pytest configuration: make repo importable and locate coreutils on Windows."""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# On Windows the POSIX-flavored commands used by executor tests (echo, cp,
# env, tee, sleep) are provided by Git for Windows' coreutils, which is often
# not on PATH. Add the well-known location when available.
if os.name == "nt" and not shutil.which("echo"):
    for candidate in (r"C:\Program Files\Git\usr\bin", r"C:\Program Files (x86)\Git\usr\bin"):
        if Path(candidate).is_dir():
            os.environ["PATH"] = candidate + os.pathsep + os.environ["PATH"]
            break

import shutil as _shutil  # noqa: E402  (re-import after PATH change)

HAS_COREUTILS = all(_shutil.which(c) for c in ("echo", "cp", "env", "tee", "sleep"))


import pytest  # noqa: E402


@pytest.fixture()
def repo_root():
    return ROOT
