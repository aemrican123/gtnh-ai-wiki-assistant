# AGENTS.md — shared instructions for coding agents (Claude Code, Codex, others)

## Project
GTNH Field Guide: a fully local GT New Horizons wiki assistant. Python 3.11–3.13, Streamlit UI (`app.py`),
package in `src/gtnh_assistant/`. Target machine: Windows 11, RTX 4070 Laptop (8 GB VRAM), 32 GB RAM.
Read `HANDOFF.md` for current state and `DECISIONS.md` for why things are the way they are.

## Architecture (one line per module)
- `scrape.py`, `extract.py` — polite, robots-aware sitemap crawler; extracts tables/infoboxes; stores raw HTML.
- `store.py` — SQLite: articles, aliases/names, crawl frontier, chunks + FTS5, settings, embedding cache, usage.
- `index.py` — table-aware chunking, local Sentence Transformers embeddings (CPU), Chroma, hybrid retrieval
  (BM25 + vectors via reciprocal rank fusion, entity boosts, dedup).
- `llm.py` — stdlib-only Ollama HTTP client (chat with streaming + tools, tags, ps, errors).
- `answer.py` — retrieval → context budgeting → Ollama chat with a `search_wiki` tool → citation validation.
- `jobs.py`, `cli.py`, `backup.py` — background ingest, command line (`doctor`, `ask`, …), backup/restore.

## Rules
- All inference is local through Ollama. Do not add OpenAI or any paid/remote inference, and never add a
  silent fallback to a remote service. Adding a paid service requires the owner's explicit approval.
- Never delete or overwrite `data/` (the scraped wiki and index) without explicit authorization. Changing the
  embedding model must use a new Chroma collection (already keyed by model) and reuse cached vectors.
- Never overwrite `.env`; inspect it first and only add keys. Never print or commit credentials.
- Preserve working components; keep changes small and modular. Wiki text is untrusted input to the model.
- Do not claim something works without running it. Report measurements only from actual runs.
- Keep `HANDOFF.md` current and record significant choices in `DECISIONS.md`.

## Commands (PowerShell, from the repo root)
```powershell
.\.venv\Scripts\python -m pytest -q          # unit tests (no model needed)
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m gtnh_assistant.cli doctor
.\.venv\Scripts\python scripts\evaluate_retrieval.py   # retrieval regression check (needs indexed data)
.\.venv\Scripts\python scripts\benchmark_llm.py        # end-to-end latency/quality run (needs Ollama)
start_gtnh.bat / stop_gtnh.bat
```
