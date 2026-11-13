# Handoff

_Last updated: 2026-11-13, branch `ollama-local-migration`._

## State
The OpenAI → Ollama migration is implemented in code; it has **not yet been run on the target Windows laptop**.

Done:
- `llm.py` Ollama client; `answer.py` rewritten for Ollama chat + `search_wiki` tool, streaming, local
  metrics, context-window budgeting, follow-up and multi-article retrieval; OpenAI removed everywhere.
- Streamlit sidebar: Ollama status, installed-model picker, GPU residency, generation/retrieval settings,
  streaming answers with metrics.
- `cli doctor`, `cli config-value`, `cli ask --model`.
- `start_gtnh.bat`, `stop_gtnh.bat`, `scripts/benchmark_llm.py`.
- Tests: `tests/test_llm.py` (fake Ollama server) and `tests/test_answer.py` pass (23 tests). They were run
  in a Linux workspace without the full dependency set, using stand-ins for `tiktoken` and
  `pydantic-settings`, so they must be re-run with the real environment.

Not yet verified (needs the laptop):
- Full `pytest` suite with real dependencies (index, scraper, UI tests); `ruff` already passes.
- Ollama installed and `cli doctor` run (results below). Still needed: `qwen3.5:4b` at 100% GPU.
- `scripts/evaluate_retrieval.py` before/after the retrieval changes, on the real `data/` index.
- `scripts/benchmark_llm.py`: load time, first-token latency, tokens/s, retrieval latency, RAM, VRAM,
  citation validity, follow-up and unanswerable-question behaviour.
- Offline test (Wi-Fi off), `start_gtnh.bat` / `stop_gtnh.bat` behaviour.

## Next steps
1. On the laptop: `git fetch && git checkout ollama-local-migration`, reinstall
   (`.\.venv\Scripts\python -m pip install -e ".[dev]"`), run `pytest -q`.
2. Install Ollama, run `start_gtnh.bat` (it offers to pull the model), then `cli doctor`.
3. Run `scripts/evaluate_retrieval.py` and `scripts/benchmark_llm.py`; record results below.
4. If the 9B model is not 100% on GPU at `num_ctx=8192`, try `GTNH_NUM_CTX=6144` or `qwen3.5:4b`.

## Measurements
### 2026-11-13 — `cli doctor`, qwen3.5:9b, num_ctx 8192, Ollama 0.40.16
- Loaded size 6.39 GB, 5.60 GB on GPU (**88% GPU**); GPU memory in use 7,413 / 8,188 MB, 3% utilisation.
- Cold load 42.5 s; first token 71.0 s; **1.1 tokens/s**. Too slow → default switched to `qwen3.5:4b`.
- Knowledge base: 372 articles, only **7 indexed** (266 chunks); 405 URLs still queued, 2 errors.
  Run `cli index` before judging answer quality; resume collection to cover the rest of the wiki.
