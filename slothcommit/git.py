"""Thin, dependency-free wrappers around the git CLI."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Files whose diffs are noise for a commit message (huge, machine-written).
NOISY_PATTERNS = (
    "*.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "*.min.js",
    "*.min.css",
    "*.svg",
    "*.ipynb",
)


class GitError(RuntimeError):
    pass


def run_git(*args: str, cwd: str | Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def repo_root(cwd: str | Path | None = None) -> Path:
    return Path(run_git("rev-parse", "--show-toplevel", cwd=cwd).strip())


def staged_files(cwd: str | Path | None = None) -> list[str]:
    out = run_git("diff", "--cached", "--name-only", cwd=cwd)
    return [line for line in out.splitlines() if line.strip()]


def staged_name_status(cwd: str | Path | None = None) -> list[tuple[str, str]]:
    """[(status, path), ...] for staged files, e.g. [("A", "cli.py"), ("M", "gpa.py")]."""
    out = run_git("diff", "--cached", "--name-status", "--no-renames", cwd=cwd)
    pairs = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            pairs.append((parts[0].strip(), parts[-1].strip()))
    return pairs


def staged_diff(cwd: str | Path | None = None, max_chars: int = 2500, with_flag: bool = False):
    """Return a compact staged diff: a --stat header plus the patch.

    Lockfiles and other generated files show up in the stat but their patch is
    excluded, and big patches are condensed to ``max_chars`` so a 1B model on a
    laptop CPU never has to chew through 50k tokens.
    """
    stat = run_git("diff", "--cached", "--stat", "--no-color", cwd=cwd).strip()
    excludes = [f":(exclude){p}" for p in NOISY_PATTERNS]
    patch = run_git(
        "diff", "--cached", "--no-color", "--unified=2", "--", ".", *excludes, cwd=cwd
    )
    condensed = len(patch) > max_chars
    patch = condense_patch(patch, max_chars)
    text = f"{stat}\n\n{patch}".strip()
    return (text, condensed) if with_flag else text


# Changed lines that carry the most meaning per character: definitions,
# comments, docstrings, CLI flags. When a diff is too big for a 1B model,
# these are what we keep.
_SIGNAL = re.compile(
    r"""^[+-]\s*(async\s+def\s|def\s|class\s|function\s|export\s|interface\s|struct\s|enum\s|fn\s|func\s"""
    r"""|public\s|private\s|#|//|/\*|\"\"\"|'''|@[\w.]+|[\w.]+\.add_argument|[\w.]+\.add_parser)"""
)


def condense_patch(patch: str, max_chars: int) -> str:
    """Shrink a large patch to its most informative lines.

    Small patches pass through untouched. Large ones become, per file, the
    ``diff --git`` header, a line count, and only the changed lines that define
    or document something. A small model summarises "these functions were
    added" far better than it reads 400 lines of fresh code.
    """
    if len(patch) <= max_chars:
        return patch
    out = []
    for chunk in _split_files(patch):
        lines = chunk.splitlines()
        if not lines:
            continue
        changed = [ln for ln in lines[1:] if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
        signal = [ln[:120] for ln in changed if _SIGNAL.match(ln)]
        added = sum(1 for ln in changed if ln.startswith("+"))
        removed = len(changed) - added
        keep = signal or [ln[:120] for ln in changed[:8]]
        out.append(f"{lines[0]}\n(+{added}/-{removed} lines; key lines:)\n" + "\n".join(keep))
    return trim_patch("\n".join(out), max_chars)


def _split_files(patch: str) -> list[str]:
    files = patch.split("\ndiff --git ")
    return [files[0]] + ["diff --git " + f for f in files[1:]]


def trim_patch(patch: str, max_chars: int) -> str:
    if len(patch) <= max_chars:
        return patch
    # Keep a fair share of every file instead of only the first one.
    files = _split_files(patch)
    budget = max(400, max_chars // max(1, len(files)))
    kept = []
    for chunk in files:
        if len(chunk) > budget:
            chunk = chunk[:budget].rstrip() + "\n... (truncated)"
        kept.append(chunk)
    out = "\n".join(kept)
    return out[:max_chars].rstrip() + ("\n... (truncated)" if len(out) > max_chars else "")


@dataclass
class Commit:
    sha: str
    date: str
    subject: str
    body: str = ""
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    extra: dict = field(default_factory=dict)


SEP = "\x1e"  # record separator
FSEP = "\x1f"  # field separator


def log_since(
    since: str = "7 days ago",
    author: str | None = None,
    cwd: str | Path | None = None,
) -> list[Commit]:
    args = [
        "log",
        f"--since={since}",
        "--no-merges",
        f"--pretty=format:{SEP}%h{FSEP}%ad{FSEP}%s{FSEP}%b{FSEP}",
        "--date=short",
        "--shortstat",
    ]
    if author:
        args.append(f"--author={author}")
    try:
        out = run_git(*args, cwd=cwd)
    except GitError as exc:  # empty repo
        if "does not have any commits" in str(exc):
            return []
        raise
    commits = []
    for record in out.split(SEP):
        if not record.strip():
            continue
        parts = record.split(FSEP)
        sha, date, subject, body = (parts + ["", "", "", ""])[:4]
        stat = parts[4] if len(parts) > 4 else ""
        c = Commit(sha=sha.strip(), date=date.strip(), subject=subject.strip(), body=body.strip())
        for piece in stat.strip().split(","):
            piece = piece.strip()
            num = piece.split(" ")[0]
            if not num.isdigit():
                continue
            if "file" in piece:
                c.files_changed = int(num)
            elif "insertion" in piece:
                c.insertions = int(num)
            elif "deletion" in piece:
                c.deletions = int(num)
        commits.append(c)
    return commits


def user_email(cwd: str | Path | None = None) -> str | None:
    try:
        return run_git("config", "user.email", cwd=cwd).strip() or None
    except GitError:
        return None
