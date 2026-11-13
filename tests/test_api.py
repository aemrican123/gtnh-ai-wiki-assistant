import json

from fastapi.testclient import TestClient
from test_answer import FakeClient, StubIndex, reply, search_call

from gtnh_assistant.api import create_app
from gtnh_assistant.config import Settings
from gtnh_assistant.llm import OllamaUnavailable


class StatusClient:
    def __init__(self, up=True):
        self.up = up

    def version(self):
        if not self.up:
            raise OllamaUnavailable("Cannot reach Ollama at http://127.0.0.1:1")
        return "0.40.16"

    def list_models(self):
        return ["qwen3.5:4b"]

    def loaded_models(self):
        return [
            {"name": "qwen3.5:4b", "size_gb": 3.4, "vram_gb": 3.4, "gpu_percent": 100, "context_length": 8192}
        ]


def make(tmp_path, replies=(), up=True):
    index = StubIndex()
    chat = FakeClient(list(replies))
    app = create_app(
        Settings(data_dir=tmp_path),
        client_factory=lambda: StatusClient(up),
        index_factory=lambda: index,
        chat_client_factory=lambda settings: chat,
        gpu=lambda: None,
    )
    return TestClient(app), index, chat


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_status_reports_ollama_models_and_knowledge_base(tmp_path):
    client, _, _ = make(tmp_path)
    data = client.get("/api/status").json()
    assert data["ollama"]["ok"] and data["ollama"]["version"] == "0.40.16"
    assert data["ollama"]["loaded"][0]["gpu_percent"] == 100
    assert data["knowledge_base"]["chunks"] == 0
    assert data["defaults"]["model"] == "qwen3.5:4b"
    assert data["job"]["running"] is False
    assert "openai" not in json.dumps(data).casefold()


def test_status_when_ollama_is_down(tmp_path):
    client, _, _ = make(tmp_path, up=False)
    data = client.get("/api/status").json()["ollama"]
    assert data["ok"] is False and "Cannot reach Ollama" in data["error"]
    assert data["models"] == []


def test_ask_streams_status_tokens_and_final_answer(tmp_path):
    client, _, chat = make(tmp_path, [reply()])
    response = client.post(
        "/api/ask",
        json={
            "question": "What coils?",
            "history": [{"role": "user", "content": "earlier"}],
            "options": {"model": "qwen3.5:9b", "temperature": 0.5, "num_ctx": 8192},
        },
    )
    assert response.status_code == 200
    stream = events(response)
    kinds = [e["type"] for e in stream]
    assert kinds[0] == "status" and "token" in kinds and kinds[-1] == "final"
    final = stream[-1]["answer"]
    assert "[S1](https://wiki.gtnewhorizons.com" in final["text"]
    assert final["sources"][0]["id"] == "S1" and "article_id" not in final["sources"][0]
    assert final["model"] == "qwen3.5:9b"
    assert chat.calls[0]["model"] == "qwen3.5:9b" and chat.calls[0]["options"]["temperature"] == 0.5


def test_ask_search_round_resets_streamed_preamble(tmp_path):
    client, index, _ = make(tmp_path, [reply("Let me check.", tool_calls=search_call()), reply()])
    stream = events(client.post("/api/ask", json={"question": "What coils?"}))
    kinds = [e["type"] for e in stream]
    assert "reset" in kinds and kinds.index("reset") < len(kinds) - 1
    assert any(e["type"] == "status" and "coil temperatures" in e["text"] for e in stream)
    assert index.queries[-1] == "coil temperatures"


def test_ask_search_only_skips_the_model(tmp_path):
    client, _, chat = make(tmp_path)
    final = events(client.post("/api/ask", json={"question": "EBF", "search_only": True}))[-1]
    assert final["type"] == "final" and final["answer"]["sources"][0]["title"] == "EBF"
    assert chat.calls == []


def test_ask_rejects_out_of_range_options(tmp_path):
    client, _, _ = make(tmp_path)
    assert client.post("/api/ask", json={"question": "x", "options": {"num_ctx": 100}}).status_code == 422


def test_ollama_failure_is_explained_in_the_final_answer(tmp_path):
    client, _, _ = make(tmp_path, [OllamaUnavailable("down")])
    final = events(client.post("/api/ask", json={"question": "What coils?"}))[-1]
    assert final["type"] == "final" and "Ollama is not running" in final["answer"]["text"]


def test_search_endpoint(tmp_path):
    client, _, _ = make(tmp_path)
    assert client.get("/api/search", params={"q": "EBF"}).json()["sources"][0]["id"] == "S1"
    assert client.get("/api/search", params={"q": " "}).json() == {"sources": []}


def test_cancel_without_a_job_and_errors(tmp_path):
    client, _, _ = make(tmp_path)
    assert client.post("/api/jobs/cancel").json()["running"] is False
    assert client.get("/api/errors").json() == {"errors": []}
    assert client.post("/api/jobs", json={"kind": "delete-everything"}).status_code == 422


def test_restore_refuses_non_empty_destination(tmp_path):
    client, _, _ = make(tmp_path / "data")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("x")
    response = client.post(
        "/api/restore", json={"archive": str(tmp_path / "missing.zip"), "destination": str(occupied)}
    )
    assert response.status_code == 400
    assert (occupied / "keep.txt").exists()


def test_unknown_api_path_is_404_not_the_interface(tmp_path):
    client, _, _ = make(tmp_path)
    assert client.get("/api/nope").status_code == 404
