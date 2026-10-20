"""Local model backends. Every one of them talks to a Gemma model on *your* machine.

* ``server``   - a llama.cpp ``llama-server`` (or any OpenAI-compatible local server).
                 Fastest: the model stays warm and the few-shot prompt prefix is cached.
* ``ollama``   - a local Ollama daemon (``ollama pull gemma3:1b``).
* ``llamacpp`` - loads the Gemma GGUF in-process with llama-cpp-python. Zero daemons.
* ``auto``     - (default) use a running llama-server, else a running Ollama, else in-process.

Each backend exposes ``chat_json(messages, schema)``: Gemma answers with a JSON object
constrained to ``schema`` (grammar-constrained decoding), so a 1B model physically
cannot answer with anything other than a well-formed commit.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

DEFAULT_GGUF_REPO = "unsloth/gemma-3-1b-it-GGUF"  # ungated GGUF conversion of google/gemma-3-1b-it
DEFAULT_GGUF_FILE = "gemma-3-1b-it-Q4_0.gguf"  # Q4_0 gets fast repacked kernels on ARM & x86
DEFAULT_OLLAMA_MODEL = "gemma3:1b"
DEFAULT_SERVER_URL = "http://127.0.0.1:8080"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
CACHE_DIR = Path(os.environ.get("SLOTH_CACHE", Path.home() / ".cache" / "slothcommit"))

# Local servers must never be routed through an HTTP proxy (very common when
# you live behind one, e.g. in mainland China). Your diff stays on localhost.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Backend(Protocol):
    name: str

    def chat_json(self, messages: list[dict], schema: dict, max_tokens: int = 256) -> dict: ...


class BackendError(RuntimeError):
    pass


def parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise BackendError(f"model did not return JSON: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _post(url: str, payload: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with _LOCAL_OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _alive(url: str) -> bool:
    try:
        with _LOCAL_OPENER.open(url, timeout=0.5) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001 - any failure means "not running"
        return False


def resolve_gguf(path: str | None = None) -> Path:
    """Find (or download once) the Gemma GGUF file."""
    path = path or os.environ.get("SLOTH_MODEL")
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise BackendError(f"model file not found: {p}")
        return p
    target = CACHE_DIR / DEFAULT_GGUF_FILE
    if target.exists():
        return target
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{DEFAULT_GGUF_REPO}/resolve/main/{DEFAULT_GGUF_FILE}"
    print(f"sloth: first run, downloading Gemma 3 1B (~720 MB) to {target}", file=sys.stderr)
    print("sloth: (this is the only time SlothCommit touches the internet)", file=sys.stderr)
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as fh:  # noqa: S310
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    tmp.rename(target)
    return target


class ServerBackend:
    """llama.cpp's llama-server (OpenAI-compatible /v1/chat/completions)."""

    name = "llama-server"

    def __init__(self, url: str | None = None):
        self.url = (url or os.environ.get("SLOTH_SERVER_URL", DEFAULT_SERVER_URL)).rstrip("/")

    def chat_json(self, messages, schema, max_tokens=256):
        try:
            data = _post(
                f"{self.url}/v1/chat/completions",
                {
                    "messages": messages,
                    "json_schema": schema,  # llama-server turns this into a GBNF grammar
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                    "cache_prompt": True,
                },
            )
        except urllib.error.URLError as exc:
            raise BackendError(f"can't reach llama-server at {self.url} ({exc})") from exc
        self.last_usage = data.get("usage", {})
        return parse_json(data["choices"][0]["message"]["content"])


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or os.environ.get("SLOTH_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        host = host or os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL)
        self.host = (host if host.startswith("http") else "http://" + host).rstrip("/")

    def chat_json(self, messages, schema, max_tokens=256):
        try:
            data = _post(
                f"{self.host}/api/chat",
                {
                    "model": self.model,
                    "messages": messages,
                    "format": schema,  # Ollama structured outputs
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": max_tokens},
                },
            )
        except urllib.error.URLError as exc:
            raise BackendError(
                f"can't reach Ollama at {self.host} ({exc}). Is `ollama serve` running "
                f"and did you `ollama pull {self.model}`?"
            ) from exc
        self.last_usage = {
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
        }
        return parse_json(data["message"]["content"])


@contextlib.contextmanager
def _quiet_stderr():
    """llama.cpp's C code logs straight to fd 2; hush it unless SLOTH_DEBUG is set."""
    if os.environ.get("SLOTH_DEBUG"):
        yield
        return
    sys.stderr.flush()
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


class LlamaCppBackend:
    name = "llama-cpp-python"

    def __init__(self, model_path: str | None = None, n_ctx: int = 4096):
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise BackendError(
                "no local model found: start llama-server or Ollama, or "
                "`pip install 'slothcommit[llamacpp]'` for the in-process backend"
            ) from exc
        self.model_path = resolve_gguf(model_path)
        with _quiet_stderr():
            self.llm = Llama(
                model_path=str(self.model_path),
                n_ctx=n_ctx,
                n_threads=int(os.environ.get("SLOTH_THREADS", os.cpu_count() or 2)),
                verbose=False,
            )

    def chat_json(self, messages, schema, max_tokens=256):
        with _quiet_stderr():
            out = self.llm.create_chat_completion(
                messages=messages,
                response_format={"type": "json_object", "schema": schema},
                temperature=0.2,
                max_tokens=max_tokens,
            )
        self.last_usage = out.get("usage", {})
        return parse_json(out["choices"][0]["message"]["content"])


def get_backend(name: str | None = None) -> Backend:
    name = (name or os.environ.get("SLOTH_BACKEND") or "auto").lower()
    if name in ("server", "llama-server"):
        return ServerBackend()
    if name == "ollama":
        return OllamaBackend()
    if name in ("llamacpp", "llama-cpp-python", "inprocess"):
        return LlamaCppBackend()
    if name == "auto":
        server = ServerBackend()
        if _alive(f"{server.url}/health"):
            return server
        ollama = OllamaBackend()
        if _alive(f"{ollama.host}/api/version"):
            return ollama
        return LlamaCppBackend()
    raise BackendError(f"unknown backend {name!r} (use auto, server, ollama or llamacpp)")
