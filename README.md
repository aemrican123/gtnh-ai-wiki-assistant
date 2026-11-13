# GTNH Field Guide

A local, persistent wiki assistant for **GT New Horizons**. It collects permitted wiki pages, preserves tables and machine specifications, indexes them with local embeddings and keyword search, and answers with linked evidence using OpenAI.

## Windows quick start

Use PowerShell from this project directory. Python 3.11–3.13 is supported; this installation was tested with Python 3.13 on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

If `.env` already exists, **keep it**. Edit it locally to set `OPENAI_API_KEY` and the model available to your account. Do not paste a key into chat or commit `.env`.

```powershell
.\.venv\Scripts\python -m streamlit run app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

Open **http://127.0.0.1:8501**. In **Knowledge base**, start with 20 articles; use 0 for all remaining articles. Collection and indexing run in a background thread. The page reports counts, errors, and the current operation. You can cancel and resume. The first indexing run downloads the local embedding model; it uses CPU and no embedding API. Later runs use the cached model.

The UI's API-key field is session-only. Other settings are persisted through `.env`; widget overrides last for the current session. Chat history is session-local and can be cleared. The knowledge base persists independently of chat history.

Select **Search local wiki without an API call** to inspect evidence without API credits or generated answers. For a reproducible environment, install `requirements-lock.txt` before installing the editable project; it records the Windows/Python 3.13 versions used during verification.

## Command line

```powershell
# Pilot collection (does not call OpenAI)
.\.venv\Scripts\python -m gtnh_assistant.cli scrape --limit 20
# Full collection or resume a checkpoint
.\.venv\Scripts\python -m gtnh_assistant.cli scrape
# Embed new/changed articles
.\.venv\Scripts\python -m gtnh_assistant.cli index
# Local retrieval only
.\.venv\Scripts\python -m gtnh_assistant.cli search "Electric Blast Furnace heating coils"
# Paid answer generation; requires the API key
.\.venv\Scripts\python -m gtnh_assistant.cli ask "How does the EBF work?"
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

Answers use the OpenAI Responses API with `store=False`. The model receives the question, bounded recent conversation, and selected wiki passages. It can request up to two additional local searches. The total newly selected evidence stays within the configured context budget; each follow-up API call can resend earlier evidence and is included in usage totals.

The prompt requires factual support, exact units/names, missing-information acknowledgments, and citations. Retrieved material is treated as untrusted data. Citation IDs resolve only to application-owned wiki URLs. Invalid references and missing citations are flagged. These checks do not prove factual correctness: verify important gameplay requirements using the displayed passages.

Actual API usage is recorded after each question, including all completed search rounds. Estimates use configured prices for input, cached input, and output tokens. Unknown pricing is shown as unavailable. Failed calls may incur usage that the SDK did not return; the UI explicitly notes incomplete accounting after failures. Context budget estimates use `cl100k_base`; actual billing counts come from the API and can differ by model.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | empty | Needed only for generated answers |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Set to a Responses-compatible model available to your account |
| `GTNH_DATA_DIR` | `data` | SQLite, Chroma, model cache, backups |
| `GTNH_REQUEST_INTERVAL` | `2` | Minimum seconds between requests; minimum configurable value 1 |
| `GTNH_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Local Sentence Transformers model |
| `GTNH_CONTEXT_TOKENS` | `5000` | Evidence budget across search rounds |
| `GTNH_HISTORY_TOKENS` | `800` | Recent conversation sent to OpenAI |
| `GTNH_OUTPUT_TOKENS` | `1000` | Maximum output per API call |
| `GTNH_RETRIEVAL_LIMIT` | `8` | Maximum retrieved chunks per search |
| `GTNH_SEARCH_ROUNDS` | `2` | Additional tool-search rounds |
| `GTNH_INPUT_PRICE` | unset | USD per million uncached input tokens |
| `GTNH_CACHED_INPUT_PRICE` | unset | USD per million cached input tokens |
| `GTNH_OUTPUT_PRICE` | unset | USD per million output tokens |
| `GTNH_PRICE_DATE` | empty | Date the configured prices were verified |

The public tokenizer is cached under `data/tokenizers` relative to the launch directory; set `TIKTOKEN_CACHE_DIR` to override this. The first tokenizer/model download requires internet. Local retrieval subsequently works without OpenAI or an internet connection. Bind Streamlit to localhost: the app has no authentication and is intended for personal use.

## Backup and restoration

```powershell
.\.venv\Scripts\python -m gtnh_assistant.cli backup data/backups/wiki.zip
.\.venv\Scripts\python -m gtnh_assistant.cli restore data/backups/wiki.zip restored-data
.\.venv\Scripts\python -m gtnh_assistant.cli --data-dir restored-data index --rebuild
```

Restoration requires an empty destination and never overwrites an existing database. A backup contains an integrity-checkable SQLite snapshot, raw article content, metadata, checkpoints, and cached embeddings. It excludes `.env`, API keys, model binaries, and physical Chroma files. Rebuilding Chroma from cached vectors makes the backup portable and avoids copying a live vector database. Set `GTNH_DATA_DIR=restored-data` and restart the UI to use it. The embedding model may need downloading again for new queries.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m pip check
```

Tests exercise real SQLite and Chroma persistence with deterministic test embeddings, mocked HTTP/OpenAI responses, extraction, robots wildcard rules and CDN redirects, interrupted indexing, stale-revision filtering, deletion, backup/restore, citations, usage, and Streamlit controls. No paid API calls are made. The first tokenizer load requires its public download; after caching it, the suite runs offline.

Live verification is separate: collect a small set, index it with the actual embedding model, inspect retrieved excerpts, and use `ask` with your own key. Check exact figures and sources for EBF construction, heating coils, power requirements, and progression. Include an intentionally unsupported recipe question to verify that the model admits insufficient evidence.

## Project layout

`src/gtnh_assistant/` contains collection/extraction, SQLite storage, indexing/retrieval, answering, job coordination, backup, and CLI modules. `app.py` is the Streamlit interface; `tests/` contains automated checks. `data/`, `.env`, and `.venv/` are gitignored.

Wiki material remains attributed to the [GT New Horizons Wiki](https://wiki.gtnewhorizons.com/wiki/Main_Page), under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) unless otherwise noted. Individual media may have different terms. This is an independent assistant, not an official GTNH or Minecraft product.
