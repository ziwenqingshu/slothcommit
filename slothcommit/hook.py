"""Install a prepare-commit-msg hook so a bare `git commit` gets a Gemma-written message."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

from slothcommit.git import run_git

MARKER = "# installed by slothcommit"

HOOK_TEMPLATE = """#!/bin/sh
{marker}
# Fills in the commit message with a local Gemma model when you run plain `git commit`.
# Skipped for `git commit -m`, merges, squashes and amends. Never blocks a commit.
case "$2" in message|merge|squash|commit) exit 0 ;; esac
"{python}" -m slothcommit hook-run "$1" || true
"""


def hooks_dir(cwd: str | Path | None = None) -> Path:
    path = Path(run_git("rev-parse", "--git-path", "hooks", cwd=cwd).strip())
    if not path.is_absolute():
        path = Path(cwd or ".").resolve() / path
    return path


def install(cwd: str | Path | None = None, python: str | None = None) -> Path:
    d = hooks_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    hook = d / "prepare-commit-msg"
    if hook.exists() and MARKER not in hook.read_text(errors="replace"):
        raise FileExistsError(f"{hook} already exists and isn't ours; not touching it")
    hook.write_text(HOOK_TEMPLATE.format(marker=MARKER, python=python or sys.executable))
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook


def uninstall(cwd: str | Path | None = None) -> bool:
    hook = hooks_dir(cwd) / "prepare-commit-msg"
    if hook.exists() and MARKER in hook.read_text(errors="replace"):
        hook.unlink()
        return True
    return False


def message_is_empty(text: str) -> bool:
    return not any(line.strip() and not line.startswith("#") for line in text.splitlines())
