# GTNH Field Guide

A fully local, persistent wiki assistant for **GT New Horizons**. It collects permitted wiki pages, preserves tables and machine specifications, indexes them with local embeddings and keyword search, and answers with linked evidence using a **local language model served by [Ollama](https://ollama.com)**. No API key, paid service, or internet connection is needed to ask questions once setup is done.

## Windows quick start

### 1. Install Ollama (once)

Download and run the Windows installer from <https://ollama.com/download/windows>. It installs the `ollama` command and a tray app that keeps the local server running on `http://127.0.0.1:11434`. No administrator rights are normally needed; if Windows SmartScreen asks, choose **More info → Run anyway** only for the installer downloaded from ollama.com. Ollama uses the NVIDIA GPU automatically when a current NVIDIA driver is installed.

### 2. Install the app (once)

Use PowerShell from this project directory. Python 3.11–3.13 is supported.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

If `.env` already exists, **keep it**. Old `OPENAI_*` and price entries are ignored and can be deleted. To set the local model, add or edit `GTNH_LLM_MODEL=qwen3.5:4b` (see `.env.example` for every setting).

### 3. Download the model (once, about 3.4 GB)

```powershell
ollama pull qwen3.5:4b
```

`start_gtnh.bat` offers to do this for you if the model is missing.

### 4. Start and stop

Double-click **`start_gtnh.bat`**. It checks that Ollama is installed, starts the Ollama service if it is not already running (it never starts a second copy), checks the model is downloaded, then opens **http://127.0.0.1:8501**.

To stop: close the launcher window (or press Ctrl+C in it), or double-click **`stop_gtnh.bat`**, which also unloads the model from GPU memory. `stop_gtnh.bat --all` also stops the Ollama service.

Manual start, equivalent to the script:

```powershell
.\.venv\Scripts\python -m streamlit run app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

### 5. Check everything

```powershell
.\.venv\Scripts\python -m gtnh_assistant.cli doctor
```

`doctor` reports whether Ollama is installed and running, the installed models, a test answer with load time, first-token time and tokens/second, how much of the model sits in GPU memory, NVIDIA memory use, and knowledge-base counts. In `ollama ps` (or the app sidebar) the model should show **100% GPU**; if part of it is on the CPU, generation becomes very slow: lower `GTNH_NUM_CTX` or choose a smaller model. On the RTX 4070 Laptop (8 GB), `qwen3.5:9b` measured only 88% on GPU at 8K context and 1.1 tokens/s, so `qwen3.5:4b` is the default.

### Using the app

In **Knowledge base**, start with 20 articles; use 0 for all remaining articles. Collection and indexing run in a background thread. The page reports counts, errors, and the current operation. You can cancel and resume. The first indexing run downloads the local embedding model; it uses the CPU, leaving GPU memory for the language model. Later runs use the cached model.

The sidebar shows Ollama status, the installed models (pick one to switch), what is loaded in GPU memory, and generation settings: context length, temperature, answer length, evidence budget, passages per search, and extra searches. Settings come from `.env`; sidebar changes last for the current session. Answers stream as they are written and show the model, tokens/second, first-token time, retrieval time, and token counts. Chat history is session-local and can be cleared. The knowledge base persists independently of chat history.

Select **Search the wiki only (no model)** to inspect evidence without running the model.

## Offline use

| Works offline after setup | Needs internet |
|---|---|
| Asking questions, follow-ups, citations | Installing Ollama and Python packages |
| Ollama and downloaded models | `ollama pull` (first model download) |
| Local embeddings (cached in `data/models`) | First embedding-model and tokenizer download |
| SQLite + Chroma knowledge base | Collecting or updating wiki articles |

Nothing in the question-answering path calls an external AI service. There is no remote fallback: if Ollama is not running, the app says so and still shows the retrieved wiki passages.

## Command line

```powershell
# Pilot collection
.\.venv\Scripts\python -m gtnh_assistant.cli scrape --limit 20
# Full collection or resume a checkpoint
.\.venv\Scripts\python -m gtnh_assistant.cli scrape
# Embed new/changed articles
.\.venv\Scripts\python -m gtnh_assistant.cli index
# Local retrieval only
.\.venv\Scripts\python -m gtnh_assistant.cli search "Electric Blast Furnace heating coils"
# Local answer generation through Ollama (optionally --model NAME)
.\.venv\Scripts\python -m gtnh_assistant.cli ask "How does the EBF work?"
# Check Ollama, the model, GPU memory and the knowledge base
.\.venv\Scripts\python -m gtnh_assistant.cli doctor
# Revalidate existing URLs and discover new articles
.\.venv\Scripts\python -m gtnh_assistant.cli scrape --update
.\.venv\Scripts\python -m gtnh_assistant.cli index
# Inspect counts and failed URLs
.\.venv\Scripts\python -m gtnh_assistant.cli status
# Rebuild from locally saved articles, reusing cached embeddings
.\.venv\Scripts\python -m gtnh_assistant.cli index --rebuild
```

Place `--data-dir another-directory` before the subcommand to select another database. `--seed https://wiki.gtnewhorizons.com/wiki/Electric_Blast_Furnace` can be repeated for a targeted pilot. Seeds do not restrict subsequent link discovery. CLI collection and indexing are separate operations; the UI runs both sequentially.

Only one writer may operate on a data directory at a time. A file lock prevents concurrent app/CLI collection, indexing, or backups. Avoid running multiple Streamlit instances against one embedded Chroma database. Closing the app stops its worker; unfinished URLs remain queued. A failed URL is recorded for inspection; an update retries failed URLs as well as completed ones.

## Collection behavior

The wiki identifies itself as MediaWiki. Its current robots.txt disallows the usual API route. Consequently, collection uses the advertised sitemap plus article links, not disallowed API requests. The compressed sitemap redirects to the wiki's `static.wikitide.net/gtnhwiki/sitemaps/` directory. That exact sitemap scope is supported with a separate robots check; arbitrary cross-site redirects are refused.

Requests have an identifiable user agent and a minimum interval of two seconds by default. Robots crawl delays and Retry-After responses can increase the interval. Requests retry transient failures with backoff. Denied access stops collection. The application does not bypass access controls or download image binaries.

Main-namespace articles and useful category pages are collected; user, talk, template, file, and administrative namespaces are excluded. Redirect aliases, canonical URLs, page/revision IDs, categories, headings, lists, expanded tables, image metadata, references, and article links are retained. PortableInfobox specifications are extracted explicitly. Raw HTML is stored for verification and reprocessing.

Conditional HTTP requests reduce unchanged downloads where the server supports them. Content hashes prevent unnecessary embedding. Updates revalidate URLs even when the sitemap is unchanged, because template edits can change rendered content. A 404/410 retires an article; a missing sitemap entry alone never does. A missing redirect does not delete its live target.

Coverage means the publicly accessible pages discovered through the sitemap and links. The wiki can omit recipes, contain outdated version details, or put necessary information only inside images. Image captions and alt text are searchable; image pixels are not interpreted. The assistant must acknowledge those gaps.

## Retrieval, grounding, and token limits

SQLite FTS5 supplies keyword rankings; Chroma supplies semantic rankings. Reciprocal rank fusion combines them, with exact title preference and duplicate removal. Short text blocks are grouped within sections. Large tables split by rows with repeated headers; individual rows are not cut. Whole originals remain in SQLite.

`sentence-transformers/all-MiniLM-L6-v2` runs locally. Long inputs are embedded in windows and averaged so later text is not silently truncated by its input limit. Embeddings are cached by model/algorithm and content hash. Changing the embedding model uses a separate Chroma collection and requires indexing again.

Answers are generated by the configured Ollama model through its local `/api/chat` endpoint. The model receives a system prompt, bounded recent conversation, and selected wiki passages. It can request up to two additional local searches through a `search_wiki` tool. Follow-up questions without a named subject reuse the subjects of the previous question for retrieval. Questions about progression, requirements, recipes, or comparisons also pull in up to two articles that the first passages mention, using at most a sixth of the evidence budget each.

The evidence budget is automatically reduced so that the system prompt, history, evidence, and answer fit inside the model's context window (`GTNH_NUM_CTX`) with a safety margin; the app warns when this happens. Token counts use the `cl100k_base` tokenizer as an approximation; the model's own counts are shown after each answer.

The prompt requires factual support, exact units/names, missing-information acknowledgments, and citations. Retrieved material is treated as untrusted data. Citation IDs resolve only to application-owned wiki URLs. Invalid references and missing citations are flagged. These checks do not prove factual correctness: verify important gameplay requirements using the displayed passages. Small local models are more likely than large hosted ones to miss details, so the retrieved evidence is always shown.

Each answer's local metrics (model, load time, first-token time, tokens/second, retrieval time, token counts) are stored in the `usage` table.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `GTNH_LLM_MODEL` | `qwen3.5:4b` | Ollama model used for answers |
| `GTNH_OLLAMA_HOST` (or `OLLAMA_HOST`) | `http://127.0.0.1:11434` | Local Ollama server |
| `GTNH_NUM_CTX` | `8192` | Model context window; larger uses more GPU memory |
| `GTNH_TEMPERATURE` | `0.2` | Lower is more literal |
| `GTNH_KEEP_ALIVE` | `30m` | How long the model stays in GPU memory after a question |
| `GTNH_LLM_TIMEOUT` | `180` | Seconds to wait for Ollama per model call |
| `GTNH_THINK` | `false` | Ask thinking-capable models to skip their reasoning phase (faster) |
| `GTNH_DATA_DIR` | `data` | SQLite, Chroma, model cache, backups |
| `GTNH_REQUEST_INTERVAL` | `2` | Minimum seconds between wiki requests; minimum 1 |
| `GTNH_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Local Sentence Transformers model |
| `GTNH_CONTEXT_TOKENS` | `5000` | Evidence budget across search rounds |
| `GTNH_HISTORY_TOKENS` | `800` | Recent conversation sent to the model |
| `GTNH_OUTPUT_TOKENS` | `1000` | Maximum output per model call |
| `GTNH_RETRIEVAL_LIMIT` | `8` | Maximum retrieved chunks per search |
| `GTNH_SEARCH_ROUNDS` | `2` | Additional tool-search rounds |

To try another model: `ollama pull <name>`, then pick it in the sidebar or set `GTNH_LLM_MODEL`. On an 8 GB laptop GPU, Windows and other programs already use part of the memory, so 9B models may not fit entirely; check `ollama ps` shows 100% GPU.

The public tokenizer is cached under `data/tokenizers` relative to the launch directory; set `TIKTOKEN_CACHE_DIR` to override this. The first tokenizer/model download requires internet. Retrieval and answering subsequently work without an internet connection. Bind Streamlit to localhost: the app has no authentication and is intended for personal use.

## Backup and restoration

```powershell
.\.venv\Scripts\python -m gtnh_assistant.cli backup data/backups/wiki.zip
.\.venv\Scripts\python -m gtnh_assistant.cli restore data/backups/wiki.zip restored-data
.\.venv\Scripts\python -m gtnh_assistant.cli --data-dir restored-data index --rebuild
```

Restoration requires an empty destination and never overwrites an existing database. A backup contains an integrity-checkable SQLite snapshot, raw article content, metadata, checkpoints, and cached embeddings. It excludes `.env`, model binaries, and physical Chroma files. Rebuilding Chroma from cached vectors makes the backup portable and avoids copying a live vector database. Set `GTNH_DATA_DIR=restored-data` and restart the UI to use it. The embedding model may need downloading again for new queries.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m pip check
```

Tests exercise real SQLite and Chroma persistence with deterministic test embeddings, mocked HTTP, a fake local Ollama server, extraction, robots wildcard rules and CDN redirects, interrupted indexing, stale-revision filtering, deletion, backup/restore, citations, tool-search rounds, follow-up retrieval, context-window budgeting, Ollama error handling, and Streamlit controls. No model needs to be installed to run them. The first tokenizer load requires its public download; after caching it, the suite runs offline.

Live verification is separate: with Ollama running and articles indexed, run `python scripts/evaluate_retrieval.py` (retrieval only) and `python scripts/benchmark_llm.py` (end to end). The benchmark asks real GTNH questions, including a follow-up, a multi-article progression question, a comparison, and an intentionally unanswerable recipe question, and writes every answer plus load time, first-token latency, tokens/second, retrieval latency, RAM, and GPU memory to `data/benchmark-*.json`. Read the answers against their cited passages; the script checks that citations resolve, not that answers are correct.

## Project layout

`src/gtnh_assistant/` contains collection/extraction, SQLite storage, indexing/retrieval, the Ollama client (`llm.py`), answering, job coordination, backup, and CLI modules. `start_gtnh.bat` / `stop_gtnh.bat` launch and stop the app on Windows. `app.py` is the Streamlit interface; `tests/` contains automated checks. `data/`, `.env`, and `.venv/` are gitignored.

Wiki material remains attributed to the [GT New Horizons Wiki](https://wiki.gtnewhorizons.com/wiki/Main_Page), under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) unless otherwise noted. Individual media may have different terms. This is an independent assistant, not an official GTNH or Minecraft product.
