import os

import pytest

from slothcommit import cli, git, hook
from tests.conftest import git as run


def test_staged_diff_and_name_status(repo):
    (repo / "a.py").write_text("print('hi')\n")
    (repo / "poetry.lock").write_text("x" * 5000)
    run(repo, "add", "-A")
    assert sorted(git.staged_name_status()) == [("A", "a.py"), ("A", "poetry.lock")]
    diff = git.staged_diff()
    assert "a.py" in diff
    assert "x" * 100 not in diff  # lockfile patch excluded, only in --stat


def test_trim_patch_keeps_every_file():
    patch = "diff --git a/one\n" + "1" * 5000 + "\ndiff --git a/two\n" + "2" * 5000
    out = git.trim_patch(patch, 2000)
    assert "a/one" in out and "a/two" in out and len(out) < 2100


def test_log_since_parses_stats(repo):
    (repo / "f.txt").write_text("a\nb\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "feat: first")
    commits = git.log_since("1 year ago")
    assert len(commits) == 1
    assert commits[0].subject == "feat: first" and commits[0].insertions == 2


def test_msg_command_uses_backend(repo, fake_backend, monkeypatch, capsys):
    (repo / "README.md").write_text("# hi\n")
    run(repo, "add", "-A")
    fake = fake_backend({"type": "docs", "scope": "README.md", "subject": "Add title", "body": []})
    monkeypatch.setattr(cli, "get_backend", lambda: fake)
    assert cli.main(["msg"]) == 0
    assert capsys.readouterr().out.strip() == "docs(readme): add title"
    _, schema = fake.calls[0]
    assert schema["properties"]["type"]["enum"] == ["docs"]


def test_commit_yes_creates_commit(repo, fake_backend, monkeypatch):
    (repo / "x.py").write_text("x = 1\n")
    run(repo, "add", "-A")
    monkeypatch.setattr(cli, "get_backend", lambda: fake_backend({"type": "feat", "scope": "x", "subject": "add x", "body": []}))
    assert cli.main(["commit", "-y"]) == 0
    assert run(repo, "log", "-1", "--format=%s").strip() == "feat(x): add x"


def test_nothing_staged_exits(repo):
    with pytest.raises(SystemExit):
        cli.main(["msg"])


def test_week_no_ai(repo, capsys):
    (repo / "f").write_text("1")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "fix(core): stop crashing")
    assert cli.main(["week", "--no-ai", "--since", "1 year ago"]) == 0
    out = capsys.readouterr().out
    assert "### Bug fixes" in out and "stop crashing" in out


def test_hook_install_run_uninstall(repo, fake_backend, monkeypatch):
    path = hook.install(python="python3")
    assert os.access(path, os.X_OK) and hook.MARKER in path.read_text()
    (repo / "y.py").write_text("y = 2\n")
    run(repo, "add", "-A")
    msgfile = repo / ".git" / "COMMIT_EDITMSG"
    msgfile.write_text("# Please enter the commit message\n")
    monkeypatch.setattr(cli, "get_backend", lambda: fake_backend({"type": "feat", "scope": "y", "subject": "add y", "body": []}))
    cli.main(["hook-run", str(msgfile)])
    assert msgfile.read_text().startswith("feat(y): add y\n")
    # a message that already has content is left alone
    msgfile.write_text("my own message\n")
    cli.main(["hook-run", str(msgfile)])
    assert msgfile.read_text() == "my own message\n"
    assert hook.uninstall() and not path.exists()


def test_hook_refuses_to_clobber_foreign_hook(repo):
    d = hook.hooks_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "prepare-commit-msg").write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(FileExistsError):
        hook.install()


def test_message_is_empty():
    assert hook.message_is_empty("# comment\n\n# more\n")
    assert not hook.message_is_empty("feat: x\n# comment")


def test_condense_patch_keeps_definitions():
    body = "\n".join(f"+    x{i} = {i}" for i in range(400))
    patch = f"diff --git a/m.py b/m.py\n+++ b/m.py\n+def useful_function():\n{body}\n+class Thing:\n"
    out = git.condense_patch(patch, 1000)
    assert "def useful_function" in out and "class Thing" in out
    assert "x399" not in out and len(out) <= 1100
    assert git.condense_patch("small", 1000) == "small"


def test_cli_falls_back_when_model_copies_example(repo, fake_backend, monkeypatch, capsys):
    (repo / "core.py").write_text("x = 1\n")
    run(repo, "add", "-A")
    monkeypatch.setattr(cli, "get_backend", lambda: fake_backend({"type": "docs", "scope": "readme", "subject": "add install instructions", "body": []}))
    assert cli.main(["msg"]) == 0
    assert capsys.readouterr().out.strip() == "feat: add core.py"
