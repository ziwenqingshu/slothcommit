import subprocess

import pytest


class FakeBackend:
    """Stands in for Gemma so the test suite runs in milliseconds with no model."""

    name = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat_json(self, messages, schema, max_tokens=256):
        self.calls.append((messages, schema))
        return self.reply


@pytest.fixture
def fake_backend():
    return FakeBackend


def git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "sloth@example.com")
    git(tmp_path, "config", "user.name", "Sloth")
    git(tmp_path, "config", "commit.gpgsign", "false")
    monkeypatch.chdir(tmp_path)
    return tmp_path
