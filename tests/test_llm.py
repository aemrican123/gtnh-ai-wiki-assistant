import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gtnh_assistant.llm import (
    LLMTimeout,
    ModelLoadError,
    ModelNotFound,
    OllamaClient,
    OllamaUnavailable,
    normalize_host,
)

DONE = {
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 120,
    "eval_count": 8,
    "load_duration": 2_000_000_000,
    "prompt_eval_duration": 50_000_000,
    "eval_duration": 200_000_000,
    "total_duration": 2_300_000_000,
}


class FakeOllama(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/version":
            self.reply(200, {"version": "0.99.0"})
        elif self.path == "/api/tags":
            self.reply(200, {"models": [{"name": "qwen3.5:9b"}, {"name": "llama3.1:latest"}]})
        elif self.path == "/api/ps":
            self.reply(200, {"models": [{"name": "qwen3.5:9b", "size": 8_000_000_000, "size_vram": 8_000_000_000}]})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.requests.append(body)
        model = body.get("model")
        if model == "missing":
            return self.reply(404, {"error": f"model '{model}' not found"})
        if model == "huge":
            return self.reply(500, {"error": "model requires more system memory (12 GiB) than is available"})
        if model == "nothink" and "think" in body:
            return self.reply(400, {"error": f"\"{model}\" does not support thinking"})
        if model == "slow":
            import time

            time.sleep(2)
        if self.path == "/api/generate":
            return self.reply(200, {"done": True})
        if body.get("tools"):
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "search_wiki", "arguments": {"query": "coils"}}}],
            }
            return self.reply(200, {"message": message} | DONE)
        if not body["stream"]:
            return self.reply(200, {"message": {"role": "assistant", "content": "OK"}} | DONE)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for piece in ["Use ", "1800 K ", "coils. [S1]"]:
            self.wfile.write((json.dumps({"message": {"role": "assistant", "content": piece}, "done": False}) + "\n").encode())
            self.wfile.flush()
        self.wfile.write((json.dumps({"message": {"role": "assistant", "content": ""}} | DONE) + "\n").encode())


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_normalize_host_accepts_ollama_formats():
    assert normalize_host("") == "http://127.0.0.1:11434"
    assert normalize_host("0.0.0.0") == "http://127.0.0.1:11434"
    assert normalize_host("127.0.0.1:11500") == "http://127.0.0.1:11500"
    assert normalize_host("http://localhost:11434/") == "http://localhost:11434"


def test_service_information(server):
    client = OllamaClient(server)
    assert client.version() == "0.99.0"
    assert client.list_models() == ["llama3.1:latest", "qwen3.5:9b"]
    assert client.has_model("qwen3.5:9b") and client.has_model("llama3.1") and not client.has_model("phi4")
    assert client.loaded_models()[0]["gpu_percent"] == 100


def test_streaming_chat_reports_tokens_and_metrics(server):
    pieces = []
    result = OllamaClient(server).chat(
        "qwen3.5:9b", [{"role": "user", "content": "q"}], options={"num_ctx": 8192}, on_token=pieces.append
    )
    assert "".join(pieces) == result.content == "Use 1800 K coils. [S1]"
    assert result.prompt_tokens == 120 and result.output_tokens == 8
    assert result.load_ms == 2000 and result.tokens_per_second == 40
    assert result.first_token_ms is not None
    assert FakeOllama.requests[-1]["options"] == {"num_ctx": 8192}


def test_tool_calls_are_parsed(server):
    result = OllamaClient(server).chat("qwen3.5:9b", [], tools=[{"type": "function"}])
    assert result.tool_calls == [{"name": "search_wiki", "arguments": {"query": "coils"}}]


def test_errors_are_classified(server):
    with pytest.raises(ModelNotFound):
        OllamaClient(server).chat("missing", [])
    with pytest.raises(ModelLoadError):
        OllamaClient(server).chat("huge", [])
    with pytest.raises(OllamaUnavailable):
        OllamaClient(f"http://127.0.0.1:{free_port()}").version()
    with pytest.raises(LLMTimeout):
        OllamaClient(server, timeout=0.5).chat("slow", [])


def test_think_flag_is_dropped_for_models_without_thinking(server):
    result = OllamaClient(server).chat("nothink", [], think=False)
    assert result.content == "OK"
    assert "think" not in FakeOllama.requests[-1]
