import json

import pytest

from slothcommit import backends


def test_parse_json_tolerates_fences():
    assert backends.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(backends.BackendError):
        backends.parse_json("no json here")


def test_server_backend_payload(monkeypatch):
    seen = {}

    def fake_post(url, payload, timeout=300):
        seen["url"], seen["payload"] = url, payload
        return {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}

    monkeypatch.setattr(backends, "_post", fake_post)
    out = backends.ServerBackend("http://127.0.0.1:9999/").chat_json([{"role": "user", "content": "hi"}], {"type": "object"})
    assert out == {"ok": True}
    assert seen["url"] == "http://127.0.0.1:9999/v1/chat/completions"
    assert seen["payload"]["json_schema"] == {"type": "object"} and seen["payload"]["cache_prompt"]


def test_ollama_backend_payload(monkeypatch):
    seen = {}

    def fake_post(url, payload, timeout=300):
        seen["url"], seen["payload"] = url, payload
        return {"message": {"content": json.dumps({"ok": 1})}, "eval_count": 5}

    monkeypatch.setattr(backends, "_post", fake_post)
    b = backends.OllamaBackend(host="localhost:11434")
    assert b.chat_json([{"role": "user", "content": "hi"}], {"type": "object"}) == {"ok": 1}
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["payload"]["model"] == "gemma3:1b" and seen["payload"]["format"] == {"type": "object"}


def test_auto_prefers_running_server(monkeypatch):
    monkeypatch.setattr(backends, "_alive", lambda url: url.endswith("/health"))
    assert isinstance(backends.get_backend("auto"), backends.ServerBackend)
    monkeypatch.setattr(backends, "_alive", lambda url: "11434" in url)
    assert isinstance(backends.get_backend("auto"), backends.OllamaBackend)


def test_unknown_backend():
    with pytest.raises(backends.BackendError):
        backends.get_backend("gpt-in-the-cloud")


def test_resolve_gguf_explicit_path(tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(b"GGUF")
    assert backends.resolve_gguf(str(f)) == f
    with pytest.raises(backends.BackendError):
        backends.resolve_gguf(str(tmp_path / "missing.gguf"))
