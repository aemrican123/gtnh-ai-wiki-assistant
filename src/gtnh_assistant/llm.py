"""Minimal client for a local Ollama server (https://github.com/ollama/ollama/blob/main/docs/api.md).

Only the Python standard library is used, so the client has no extra dependencies and works offline.
All answer generation goes through this module; there is no remote or paid fallback.
"""

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_HOST = "http://127.0.0.1:11434"


class LLMError(Exception):
    """Base class for local-model failures that the UI can explain to the user."""


class OllamaUnavailable(LLMError):
    pass


class ModelNotFound(LLMError):
    pass


class ModelLoadError(LLMError):
    pass


class LLMTimeout(LLMError):
    pass


def normalize_host(host):
    """Accept Ollama's own OLLAMA_HOST formats (``0.0.0.0``, ``127.0.0.1:11434``, full URLs)."""
    host = (host or "").strip() or DEFAULT_HOST
    if "://" not in host:
        host = "http://" + host
    scheme, rest = host.split("://", 1)
    rest = rest.rstrip("/")
    hostname, _, port = rest.partition(":")
    if hostname in {"0.0.0.0", "", "[::]"}:
        hostname = "127.0.0.1"
    return f"{scheme}://{hostname}:{port or '11434'}"


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    done_reason: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    load_ms: float = 0.0
    prompt_ms: float = 0.0
    eval_ms: float = 0.0
    total_ms: float = 0.0
    first_token_ms: float | None = None

    @property
    def tokens_per_second(self):
        return self.output_tokens / (self.eval_ms / 1000) if self.eval_ms else None


def _ms(nanoseconds):
    return (nanoseconds or 0) / 1_000_000


def _tool_calls(message):
    calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = None
        calls.append({"name": function.get("name", ""), "arguments": arguments})
    return calls


class OllamaClient:
    def __init__(self, host=DEFAULT_HOST, timeout=180.0):
        self.host = normalize_host(host)
        self.timeout = timeout

    # -- transport -------------------------------------------------------------------------------
    def _request(self, method, path, payload=None, timeout=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.host + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            return urllib.request.urlopen(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                message = json.loads(body).get("error", body)
            except ValueError:
                message = body
            raise self._classify(exc.code, message, payload) from None
        except TimeoutError as exc:
            raise LLMTimeout(f"Ollama did not respond within {timeout or self.timeout:.0f} s") from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise LLMTimeout(f"Ollama did not respond within {timeout or self.timeout:.0f} s") from exc
            raise OllamaUnavailable(f"Cannot reach Ollama at {self.host}") from exc

    @staticmethod
    def _classify(status, message, payload):
        text = str(message)
        lowered = text.casefold()
        model = (payload or {}).get("model", "")
        if status == 404 or ("model" in lowered and "not found" in lowered):
            return ModelNotFound(f"Model '{model}' is not installed in Ollama")
        if "memory" in lowered or "out of memory" in lowered or "cuda" in lowered:
            return ModelLoadError(text[:300])
        return LLMError(f"Ollama returned HTTP {status}: {text[:300]}")

    def _json(self, method, path, payload=None, timeout=None):
        with self._request(method, path, payload, timeout) as response:
            return json.loads(response.read().decode() or "{}")

    # -- service information ---------------------------------------------------------------------
    def version(self, timeout=3):
        return self._json("GET", "/api/version", timeout=timeout).get("version", "unknown")

    def list_models(self, timeout=5):
        return sorted(m.get("name", "") for m in self._json("GET", "/api/tags", timeout=timeout).get("models", []))

    def loaded_models(self, timeout=5):
        """Models currently in memory, with the share held in GPU memory."""
        result = []
        for m in self._json("GET", "/api/ps", timeout=timeout).get("models", []):
            size, vram = m.get("size", 0) or 0, m.get("size_vram", 0) or 0
            result.append(
                {
                    "name": m.get("name", ""),
                    "size_gb": size / 1e9,
                    "vram_gb": vram / 1e9,
                    "gpu_percent": round(100 * vram / size) if size else 0,
                    "context_length": m.get("context_length"),
                }
            )
        return result

    def has_model(self, name):
        models = self.list_models()
        return name in models or (":" not in name and f"{name}:latest" in models)

    def unload(self, model):
        """Release a model from memory (used for cold-start measurements and shutdown)."""
        self._json("POST", "/api/generate", {"model": model, "keep_alive": 0}, timeout=30)

    # -- generation ------------------------------------------------------------------------------
    def chat(self, model, messages, tools=None, options=None, keep_alive=None, think=None, on_token=None):
        """Run one chat completion. Streams tokens to ``on_token`` when given."""
        payload = {"model": model, "messages": messages, "stream": on_token is not None}
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if think is not None:
            payload["think"] = think
        try:
            return self._chat(payload, on_token)
        except LLMError as exc:
            # Models without a thinking mode reject the flag; retry once without it.
            if think is not None and "think" in str(exc).casefold():
                payload.pop("think")
                return self._chat(payload, on_token)
            raise

    def _chat(self, payload, on_token):
        started = time.perf_counter()
        result = ChatResult()
        parts = []
        try:
            self._consume(payload, on_token, started, result, parts)
        except TimeoutError as exc:
            raise LLMTimeout(f"Ollama stopped responding for {self.timeout:.0f} s") from exc
        except (ConnectionError, urllib.error.URLError) as exc:
            raise OllamaUnavailable(f"Lost the connection to Ollama at {self.host}") from exc
        result.content = "".join(parts)
        if not result.total_ms:
            result.total_ms = (time.perf_counter() - started) * 1000
        return result

    def _consume(self, payload, on_token, started, result, parts):
        with self._request("POST", "/api/chat", payload) as response:
            if not payload["stream"]:
                chunks = [json.loads(response.read().decode())]
            else:
                chunks = (json.loads(line) for line in response if line.strip())
            for chunk in chunks:
                if chunk.get("error"):
                    raise self._classify(500, chunk["error"], payload)
                message = chunk.get("message") or {}
                piece = message.get("content") or ""
                if piece:
                    if result.first_token_ms is None:
                        result.first_token_ms = (time.perf_counter() - started) * 1000
                    parts.append(piece)
                    if on_token:
                        on_token(piece)
                result.tool_calls.extend(_tool_calls(message))
                if chunk.get("done"):
                    result.done_reason = chunk.get("done_reason", "")
                    result.prompt_tokens = chunk.get("prompt_eval_count", 0) or 0
                    result.output_tokens = chunk.get("eval_count", 0) or 0
                    result.load_ms = _ms(chunk.get("load_duration"))
                    result.prompt_ms = _ms(chunk.get("prompt_eval_duration"))
                    result.eval_ms = _ms(chunk.get("eval_duration"))
                    result.total_ms = _ms(chunk.get("total_duration"))
