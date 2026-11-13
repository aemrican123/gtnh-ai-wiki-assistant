from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_empty_ui_and_clear_history(tmp_path, monkeypatch):
    monkeypatch.setenv("GTNH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "GTNH Field Guide"
    assert any("knowledge base is empty" in item.value for item in app.info)
    app.session_state.messages = [{"role": "user", "content": "old question"}]
    app.run()
    clear = next(button for button in app.button if button.label == "Clear conversation")
    clear.click().run()
    assert app.session_state.messages == []
    assert not app.exception
