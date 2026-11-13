import socket
from pathlib import Path

from streamlit.testing.v1 import AppTest


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_empty_ui_reports_ollama_down_and_clears_history(tmp_path, monkeypatch):
    monkeypatch.setenv("GTNH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GTNH_OLLAMA_HOST", f"http://127.0.0.1:{closed_port()}")
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "GTNH Field Guide"
    assert any("knowledge base is empty" in item.value for item in app.info)
    assert any("Ollama is not reachable" in item.value for item in app.error)
    assert app.selectbox[0].value == "qwen3.5:4b"
    assert not any("OpenAI" in item.value for item in app.caption)
    app.session_state.messages = [{"role": "user", "content": "old question"}]
    app.run()
    clear = next(button for button in app.button if button.label == "Clear conversation")
    clear.click().run()
    assert app.session_state.messages == []
    assert not app.exception
