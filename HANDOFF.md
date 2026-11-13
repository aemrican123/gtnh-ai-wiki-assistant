# Handoff

_Last updated: 2026-11-14, branch `ollama-local-migration`._

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

## React + Base UI interface (built 2026-11-14, not yet run on the laptop)
- `src/gtnh_assistant/api.py`: FastAPI + uvicorn on 127.0.0.1:8501. `GET /api/status` (Ollama, models, GPU
  residency, nvidia-smi VRAM, knowledge-base counts, job state, `.env` defaults; Ollama/GPU cached 10 s,
  `?refresh=true` bypasses), `POST /api/ask` (NDJSON stream: `status`, `token`, `reset`, `final`, `error`),
  `GET /api/search`, `POST /api/jobs` / `/api/jobs/cancel`, `GET /api/errors`, `POST /api/backup`,
  `POST /api/restore`. Serves `frontend/dist` with an SPA fallback. Existing modules unchanged.
- `frontend/`: Vite 8 + React 19 + TypeScript 5.9 + `@base-ui/react` 1.9, CSS modules styled after shadcn/ui
  (owner's choice, 2026-11-14: neutral oklch tokens, rounded corners, soft shadows, pill tabs, 3 px focus ring,
  light/dark/system theme). Geist fonts are bundled from npm (`@fontsource-variable/*`), so nothing loads from a CDN.
  Ask view: streaming answers, citation chips with tooltips, collapsible evidence, metrics, warnings, stop,
  clear (confirm dialog); settings panel (model Select with GPU note, context Select, Sliders, search-only
  Switch, reset to `.env`); chat and settings persisted in localStorage. Knowledge base view: stat tiles,
  collection Progress, NumberField limit, collect/update/index, rebuild (confirm dialog), cancel, error table,
  backup/restore, Toast when a job ends.
- `start_gtnh.bat` builds the interface when `frontend/dist` is missing or older than `frontend/src` (needs
  Node.js LTS), falls back to Streamlit without Node, and keeps `--classic` for Streamlit.
- Verified in the cloud workspace: `pytest` 56 passed (incl. 11 new API tests and the Streamlit UI test) with
  all dependencies except `sentence-transformers`/`torch` (download blocked there; tests use fake embeddings);
  `ruff check` clean; `tsc` clean; `vite build` OK; headless-Chromium screenshots of both views in light and
  dark with no console errors, against the real API with a fake Ollama and stub index.
- Not verified: `start_gtnh.bat` on Windows, the UI against real Ollama + the real `data/` index, collection
  jobs started from the new UI.

## Desktop shortcut (built 2026-11-14, not yet run on the laptop)
- `install_shortcuts.bat` → `gtnh_assistant.shortcuts`: desktop + Start-menu `GTNH Field Guide.lnk` (icon
  `assets/gtnh.ico`) running `.venv\Scripts\pythonw.exe -m gtnh_assistant.launcher` in the project folder.
- `launcher.py`: reuses a running app, starts `ollama serve` hidden if needed, otherwise hands over to
  `start_gtnh.bat --prepare` in a console (Ollama missing, model missing, UI build), checks port 8501, then
  `api.serve(exit_when_closed=True)` and opens an Edge/Chrome `--app` window. Logs to `data/launcher.log`.
- `lifecycle.py`: the UI sends a `pagehide` beacon to `/api/closing`; with no request for 15 s afterwards (or
  300 s of silence) and no job or answer stream running, uvicorn stops and the used models are unloaded.
- Verified here: 63 tests pass (incl. 7 new); real uvicorn run exits 16 s after the beacon; in headless
  Chromium a reload keeps it running and leaving the page stops it. Headless `page.close()` does not send the
  beacon (test-tool quirk), so the 300 s fallback matters if a real browser ever skips it.
- Not verified: the shortcut, pythonw launch, Edge app window and message boxes on Windows.

## Next steps
0. On the laptop after pulling: install Node.js LTS if missing, reinstall Python deps (adds `fastapi`,
   `uvicorn`), run `start_gtnh.bat`, ask a few questions and run a small collection from Knowledge base.
   If the new UI works, retire `app.py`/`--classic` and `tests/test_ui.py` in a separate change.
1. On the laptop: `git fetch && git checkout ollama-local-migration`, reinstall
   (`.\.venv\Scripts\python -m pip install -e ".[dev]"`), run `pytest -q`.
2. Install Ollama, run `start_gtnh.bat` (it offers to pull the model), then `cli doctor`.
3. Run `scripts/evaluate_retrieval.py` and `scripts/benchmark_llm.py`; record results below.
4. If the 9B model is not 100% on GPU at `num_ctx=8192`, try `GTNH_NUM_CTX=6144` or `qwen3.5:4b`.

## Measurements

### 2026-11-13 23:33 — qwen3.5:4b, num_ctx 8192 (`cli doctor` + `scripts/benchmark_llm.py`)
- **100% GPU**, 3.36 GB model; GPU memory 1,754 MB idle → 5,929 MB loaded (of 8,188).
- Cold model load 3.7 s; embedding model load 7.7 s (CPU, once per process).
- Median first token **1.1 s** (first question after cold load 10.2 s); median **59.3 tokens/s**;
  median retrieval **41 ms**; answers took 3–17 s end to end.
- `scripts/evaluate_retrieval.py`: **12/12 PASS** after indexing all 372 collected articles (5,666 chunks).
- All citations resolved to retrieved sources. Unanswerable "Quantum Banana Compressor" question: correctly
  said the wiki has no such information. Follow-up question correctly resolved "it" to the EBF.
- Problems found and fixed in code (not yet re-measured): 2/11 answers without citations; noisy
  linked-article expansion. App process RAM not measured (`psutil` not installed).
- 405 wiki URLs are still queued for collection; coverage is partial until collection finishes.
### 2026-11-13 — `cli doctor`, qwen3.5:9b, num_ctx 8192, Ollama 0.40.16
- Loaded size 6.39 GB, 5.60 GB on GPU (**88% GPU**); GPU memory in use 7,413 / 8,188 MB, 3% utilisation.
- Cold load 42.5 s; first token 71.0 s; **1.1 tokens/s**. Too slow → default switched to `qwen3.5:4b`.
- Knowledge base: 372 articles, only **7 indexed** (266 chunks); 405 URLs still queued, 2 errors.
  Run `cli index` before judging answer quality; resume collection to cover the rest of the wiki.
