# Decisions

Newest first. Each entry: decision, reason, consequences.

## 2026-11-13 — Linked-article expansion off by default; citation reminder added

**Decision.** `GTNH_LINKED_ARTICLES` defaults to 0 (the expansion from the earlier retrieval decision is now
opt-in, and when on it keeps only chunks of the linked article). A short citation instruction now ends the
user prompt.

**Reason.** First `qwen3.5:4b` benchmark (11 questions): expansion added unrelated articles (Portable Scanner,
AR Glasses, Charging for an EBF power question; Hot Isostatic Pressurization Unit and Plasma Forge for a
coil question), pushed one prompt against the context limit, and its passages were cited only once, wrongly.
Two of 11 answers (EBF construction, Cleanroom) had correct-looking content but no [S#] citations.

**Open.** Re-run `scripts/benchmark_llm.py` and confirm every answer cites sources.

## 2026-11-13 — Default model changed to `qwen3.5:4b` after measurement

**Decision.** `GTNH_LLM_MODEL` now defaults to `qwen3.5:4b`. `qwen3.5:9b` stays usable by setting it in `.env`.

**Reason.** `cli doctor` on the RTX 4070 Laptop (8 GB), Ollama 0.40.16, `num_ctx=8192`: `qwen3.5:9b` loaded as
6.39 GB with only 5.60 GB (88%) in GPU memory; total GPU memory in use 7,413 / 8,188 MB. Generation ran at
1.1 tokens/s, first token 71 s (42.5 s of it model load). The CPU-resident share makes it far too slow for chat.

**Open.** Confirm `qwen3.5:4b` is 100% on GPU and measure it with `scripts/benchmark_llm.py`.

## 2026-11-13 — Migrate answer generation from OpenAI to local Ollama

**Decision.** Answers are generated only by a local model served by Ollama. The OpenAI client, API-key
handling, price settings and cost estimates were removed (the owner chose removal over keeping an opt-in
provider). There is no remote fallback.

**Reason.** API credit was exhausted; the goal is a self-hosted assistant with no recurring cost that works
offline after setup.

**Consequences.** `openai` is no longer a dependency. Old `OPENAI_*`/`GTNH_*_PRICE` keys in an existing
`.env` are ignored (settings use `extra="ignore"`). The `usage` table now records local metrics instead of
cost.

## 2026-11-13 — Default model `qwen3.5:9b`, fallback `qwen3.5:4b`

**Decision.** Default `GTNH_LLM_MODEL=qwen3.5:9b` (about 6.6 GB at Ollama's default 4-bit quantization),
with `num_ctx=8192`. If it does not stay 100% on the 8 GB GPU or is too slow, switch to `qwen3.5:4b`
(about 3.4 GB). Only one model is downloaded until measurements justify another.

**Reason.** At the time of the migration the Qwen3.5 small models were the strongest open models under
10B parameters in independent benchmarks, support tool calling, and have thinking disabled by default for the
small sizes. Qwen 2.5 7B (suggested in the original brief) is a generation older with a 32K context limit.

**Open.** Not yet measured on the target laptop. Fill in `HANDOFF.md` with `cli doctor` and
`scripts/benchmark_llm.py` results; revisit if the model spills to CPU.

## 2026-11-13 — Keep local MiniLM embeddings on the CPU

**Decision.** No embedding migration. `sentence-transformers/all-MiniLM-L6-v2` already runs locally and is
cached per model + content hash; Chroma collections are keyed by embedding model.

**Reason.** Embeddings were never paid; keeping them avoids reindexing and keeps all GPU memory for the
language model. A stronger embedder can be evaluated later as a separate collection, gated by
`scripts/evaluate_retrieval.py`, without deleting existing data.

## 2026-11-13 — Stdlib HTTP client for Ollama

**Decision.** `llm.py` uses `urllib` instead of the `ollama` package or `httpx`.

**Reason.** No new dependency, easy to test with a fake local server, and the API surface needed is small
(`/api/chat`, `/api/tags`, `/api/ps`, `/api/version`, `/api/generate` for unloading).

## 2026-11-13 — Context budgeting against the model's window

**Decision.** The evidence budget is reduced so that system prompt + tool schema + history + question +
evidence + output fit in `num_ctx` × 0.85. The app warns when evidence is reduced and refuses (without a
model call) when even 300 evidence tokens would not fit.

**Reason.** Ollama silently truncates prompts that exceed `num_ctx`, which would drop evidence or
instructions. `cl100k_base` is only an approximation of Qwen's tokenizer, hence the margin.

## 2026-11-13 — Retrieval changes kept deliberately small

**Decision.** Kept hybrid BM25 + vector retrieval as is. Added (1) follow-up retrieval that reuses the
previous question's named subjects when the new question names none, and (2) for progression / requirement /
recipe / comparison questions, up to two linked articles mentioned by the first passages, each capped at a
sixth of the budget. Neighbouring-chunk expansion for split tables was deferred.

**Reason.** The existing retrieval already covers hybrid search, dedup, entity matching and multi-subject
reservation. Deterministic rewrites avoid an extra model call per question. Both additions must be checked
with `scripts/evaluate_retrieval.py` and the benchmark on real data; remove them if they do not help.
