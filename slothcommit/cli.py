"""`sloth` command line interface."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from slothcommit import __version__, chores, git, hook
from slothcommit.backends import BackendError, get_backend

SLOTH = "\U0001f9a5"


def eprint(*args) -> None:
    print(*args, file=sys.stderr, flush=True)


def generate_commit_message(backend=None, hint=None, with_body=True, cwd=None, verbose=True) -> str:
    if not git.staged_files(cwd):
        raise SystemExit("sloth: nothing staged. `git add` something first (I'm lazy, not psychic).")
    diff, condensed = git.staged_diff(cwd, with_flag=True)
    files = git.staged_name_status(cwd)
    t0 = time.perf_counter()
    backend = backend or get_backend()
    t1 = time.perf_counter()
    messages = chores.build_commit_messages(diff, files, hint)
    data = backend.chat_json(messages, chores.commit_schema(files, allow_body=not condensed), max_tokens=200)
    if chores.copied_example(data):
        if verbose:
            eprint(f"{SLOTH} Gemma copied an example instead of reading the diff; using a plain file-list message.")
        data = chores.fallback_commit(files)
    t2 = time.perf_counter()
    if verbose:
        load = f", model load {t1 - t0:.1f}s" if t1 - t0 > 0.05 else ""
        eprint(f"{SLOTH} Gemma via {backend.name}: {t2 - t1:.1f}s{load}. Nothing left this machine.")
    return chores.format_commit(data, with_body=with_body)


def cmd_msg(args) -> int:
    print(generate_commit_message(hint=args.hint, with_body=not args.no_body))
    return 0


def cmd_commit(args) -> int:
    msg = generate_commit_message(hint=args.hint, with_body=not args.no_body)
    print("\n" + msg + "\n")
    choice = "y" if args.yes else input("Commit with this message? [Y]es / [e]dit / [n]o: ").strip().lower()
    if choice in ("", "y", "yes"):
        return subprocess.call(["git", "commit", "-m", msg])
    if choice in ("e", "edit"):
        return subprocess.call(["git", "commit", "-e", "-m", msg])
    eprint("sloth: ok, not committing. Back to napping.")
    return 1


def cmd_week(args) -> int:
    author = None if args.all else (args.author or git.user_email())
    commits = git.log_since(args.since, author=author)
    if not commits:
        eprint(f"sloth: no commits since '{args.since}'" + (f" by {author}" if author else "") + ". A truly restful week.")
        return 0
    data = None
    if not args.no_ai:
        backend = get_backend()
        t0 = time.perf_counter()
        prompt = chores.build_week_prompt(commits, args.since, args.lang)
        data = backend.chat_json([{"role": "user", "content": prompt}], chores.WEEK_SCHEMA, max_tokens=300)
        eprint(f"{SLOTH} Gemma summarized {len(commits)} commits in {time.perf_counter() - t0:.1f}s.")
    report = chores.week_report(commits, data, args.since, args.lang)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        eprint(f"sloth: wrote {args.output}")
    else:
        print(report)
    return 0


def cmd_hook(args) -> int:
    if args.action == "install":
        path = hook.install()
        print(f"{SLOTH} hook installed at {path}. Now just run `git commit` and let Gemma type.")
    else:
        print("hook removed" if hook.uninstall() else "no slothcommit hook found")
    return 0


def cmd_hook_run(args) -> int:
    path = Path(args.msgfile)
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if not hook.message_is_empty(existing) or not git.staged_files():
        return 0
    try:
        msg = generate_commit_message()
    except Exception as exc:  # noqa: BLE001 - never block a commit because the sloth tripped
        eprint(f"sloth: couldn't generate a message ({exc}); write one yourself this time.")
        return 0
    path.write_text(msg + "\n\n" + existing, encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sloth",
        description="Let a local Gemma model do your git chores. Offline, free, lazy.",
    )
    p.add_argument("--version", action="version", version=f"slothcommit {__version__}")
    p.add_argument(
        "--backend",
        choices=["auto", "server", "ollama", "llamacpp"],
        help="where Gemma runs (default: $SLOTH_BACKEND or auto)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, fn, helptext in (
        ("msg", cmd_msg, "print a commit message for the staged changes"),
        ("commit", cmd_commit, "write a commit message for the staged changes and commit"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--hint", help="one line of context for the model, e.g. 'fixes #12'")
        sp.add_argument("--no-body", action="store_true", help="subject line only")
        if name == "commit":
            sp.add_argument("-y", "--yes", action="store_true", help="don't ask, just commit")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("week", help="summarize recent commits into a weekly report + changelog")
    sp.add_argument("--since", default="7 days ago", help="git date, e.g. '7 days ago', 'last monday', '2026-10-01'")
    sp.add_argument("--author", help="only this author (default: your git user.email)")
    sp.add_argument("--all", action="store_true", help="include every author")
    sp.add_argument("--lang", default="en", help="report language: en or zh", choices=["en", "zh"])
    sp.add_argument("--no-ai", action="store_true", help="changelog only, skip the model")
    sp.add_argument("-o", "--output", help="write the report to a file")
    sp.set_defaults(func=cmd_week)

    sp = sub.add_parser("hook", help="install/uninstall the prepare-commit-msg hook")
    sp.add_argument("action", choices=["install", "uninstall"])
    sp.set_defaults(func=cmd_hook)

    sp = sub.add_parser("hook-run", help=argparse.SUPPRESS)
    sp.add_argument("msgfile")
    sp.add_argument("source", nargs="?")
    sp.set_defaults(func=cmd_hook_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.backend:
        os.environ["SLOTH_BACKEND"] = args.backend
    try:
        return args.func(args)
    except (git.GitError, BackendError, FileExistsError) as exc:
        eprint(f"sloth: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
