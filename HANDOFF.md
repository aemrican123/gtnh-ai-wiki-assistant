# Handoff

_Last updated: 2026-11-14, branch `main`._

## State
The assistant runs fully locally on the target laptop (Windows 11, RTX 4070 Laptop 8 GB) and the owner
uses it day to day. Everything below has been run there unless marked otherwise.

- **AI:** Ollama `qwen3.5:4b` at `num_ctx` 8192, 100% on the GPU; embeddings on the CPU. No OpenAI or
  other paid API anywhere.
- **Knowledge base:** the whole wiki is collected (collection queue 0) and indexed. `Update wiki` in the
  Knowledge base view rechecks saved pages for changes.
- **Interface:** React + Base UI in the shadcn/ui style (`frontend/`), served by `api.py` (FastAPI) on
  127.0.0.1:8501. Streamlit was removed on 2026-11-14.
- **Starting it:** the desktop / Start-menu shortcut (`install_shortcuts.bat`) opens an Edge app window with
  no console; closing the window stops the app and unloads the model. `start_gtnh.bat` is the console
  alternative; `stop_gtnh.bat` is the emergency stop.
- **Quality:** latest benchmark and retrieval check below. Every grounded answer cites, every citation
  resolves, and the unanswerable question is refused.

## How the pieces fit
- `api.py`: `GET /api/status` (Ollama, models, GPU residency, VRAM, knowledge-base counts, job state,
  `.env` defaults; cached 10 s, `?refresh=true` bypasses), `POST /api/ask` (NDJSON stream: `status`,
  `token`, `reset`, `final`, `error`), `GET /api/search`, `POST /api/jobs` and `/api/jobs/cancel`,
  `GET /api/errors`, `POST /api/backup`, `POST /api/restore`, `POST /api/closing` (window-closed beacon).
  Serves `frontend/dist` with an SPA fallback.
- `frontend/`: Vite 8, React 19, TypeScript 5.9, `@base-ui/react` 1.9, CSS modules; tokens in
  `src/global.css`; Geist fonts bundled from npm, no CDN. Chat history and settings live in localStorage.
- `launcher.py` (run by the shortcut through `pythonw`): reuses a running app, starts `ollama serve` hidden,
  hands setup problems to `start_gtnh.bat --prepare` in a console, opens an Edge/Chrome `--app` window,
  logs to `data/launcher.log`.
- `lifecycle.py`: after the `pagehide` beacon, 15 s without a request (or 300 s of silence) with no job or
  answer running stops uvicorn and unloads the models used.
- `start_gtnh.bat` rebuilds the interface when `frontend/src` or `package-lock.json` is newer than the
  build, and reinstalls npm packages when the lock file changed (needs Node.js LTS).

## Known limits
- The 4B model sometimes misreads tables: in the 2026-11-14 benchmark it described the EBF voltage-tier heat
  bonus table as coil temperatures, and gave a doubtful aluminium heat figure. The cited passages are right;
  check the evidence for exact numbers. A bigger model needs more VRAM than this laptop has (9B ran at 88%
  GPU and 1.1 tokens/s).
- Evidence is capped at about 4,500 tokens at `num_ctx` 8192; a warning says when that happens.

## Measurements

### 2026-11-14 07:38 — qwen3.5:4b, num_ctx 8192, full wiki indexed (`scripts/benchmark_llm.py`)
- **100% GPU**, 3.36 GB model; GPU memory 2,318 MB → 6,271 MB of 8,188 with the model loaded.
- Cold model load 5.5 s; embedding model 0.07 s (cached); median first token **0.63 s**; median
  **65.3 tokens/s**; median retrieval **55 ms**; answers 1.9–16.3 s end to end (16.3 s includes the cold load).
- **11/11 answers behaved as expected**: all 10 grounded answers cited sources, all citations valid, the
  follow-up resolved "it" to the EBF, and the "Quantum Banana Compressor" question was declined.
  (The 2026-11-13 run had 2 answers without citations; the fix held.)
- `scripts/evaluate_retrieval.py`: **12/12 PASS** on the full wiki.
- Fixed after this run: grouped citations such as `[S6, S7]` were left unlinked (now split into
  `[S6][S7]`); a declined answer no longer gets a "no citations" warning; the benchmark's gap check no longer
  matches the in-game error text "not enough output space".

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
