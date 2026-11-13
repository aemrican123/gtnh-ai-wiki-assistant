"""Run with: python -m streamlit run app.py --server.address 127.0.0.1 (or start_gtnh.bat)"""

from dataclasses import asdict
from datetime import datetime

import streamlit as st

from gtnh_assistant.answer import Answerer
from gtnh_assistant.backup import backup, restore
from gtnh_assistant.config import Settings
from gtnh_assistant.index import Index
from gtnh_assistant.jobs import Jobs, writer_busy
from gtnh_assistant.llm import LLMError, OllamaClient
from gtnh_assistant.store import Store

st.set_page_config(page_title="GTNH Field Guide", page_icon="⚙️", layout="wide")
CONTEXT_CHOICES = [4096, 8192, 12288, 16384, 24576, 32768]


@st.cache_resource
def resources():
    settings = Settings().prepare()
    store = Store(settings.data_dir)
    # Lazy model loading: chat UI and scraper do not need an embedding download to start.
    holder = {}

    def index():
        if "index" not in holder:
            holder["index"] = Index(store, settings)
        return holder["index"]

    return settings, store, index, Jobs(store, settings, index)


@st.cache_data(ttl=15, show_spinner=False)
def ollama_status(host):
    """Cached briefly so every rerun does not hit the local server."""
    client = OllamaClient(host, timeout=5)
    try:
        return {
            "ok": True,
            "version": client.version(),
            "models": client.list_models(),
            "loaded": client.loaded_models(),
        }
    except LLMError as exc:
        return {"ok": False, "error": str(exc), "models": [], "loaded": []}


settings, store, get_index, jobs = resources()
if not isinstance(settings, Settings):
    # The code was updated while the app was running: the cached objects come from the old modules.
    resources.clear()
    settings, store, get_index, jobs = resources()
st.title("GTNH Field Guide")
st.caption("Your local wiki companion · Answers with evidence, from steam to the Stargate")

with st.sidebar:
    st.subheader("Local model")
    status = ollama_status(settings.ollama_host)
    if status["ok"]:
        st.success(f"Ollama {status['version']} is running", icon="🟢")
    else:
        st.error(
            f"Ollama is not reachable at {settings.ollama_host}. Run start_gtnh.bat or `ollama serve`.",
            icon="🔴",
        )
    installed = status["models"]
    choices = installed if settings.llm_model in installed else [settings.llm_model, *installed]
    model = st.selectbox("Model", choices, index=choices.index(settings.llm_model) if choices else 0)
    if status["ok"] and model not in installed:
        st.warning(f"`{model}` is not installed. Run `ollama pull {model}` in a terminal.")
    for loaded in status["loaded"]:
        st.caption(
            f"In memory: {loaded['name']} · {loaded['vram_gb']:.1f} GB on GPU ({loaded['gpu_percent']}%)"
        )
    if st.button("Check Ollama", use_container_width=True):
        ollama_status.clear()
        st.rerun()
    search_only = st.checkbox("Search the wiki only (no model)", value=False)
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    with st.expander("Generation and retrieval settings"):
        default_ctx = settings.num_ctx if settings.num_ctx in CONTEXT_CHOICES else 8192
        num_ctx = st.select_slider("Context length (tokens)", CONTEXT_CHOICES, value=default_ctx)
        st.caption("Larger contexts use more GPU memory. Keep the model at 100% GPU (shown above).")
        temperature = st.slider("Temperature", 0.0, 1.0, float(settings.temperature), 0.05)
        output_tokens = st.slider("Maximum answer length (tokens)", 200, 4000, settings.output_tokens, 100)
        context = st.slider("Evidence budget (tokens)", 500, 20000, settings.context_tokens, 500)
        retrieval_limit = st.slider("Passages per search", 1, 30, settings.retrieval_limit)
        search_rounds = st.slider("Extra wiki searches the model may run", 0, 3, settings.search_rounds)
    st.caption("Search, embeddings and answers all run on this computer. No paid API is used.")

chat_tab, admin_tab = st.tabs(["Ask the wiki", "Knowledge base"])
if "messages" not in st.session_state:
    st.session_state.messages = []


def show_answer(data):
    st.markdown(data["text"])
    for warning in data.get("warnings", []):
        st.warning(warning)
    if data.get("calls"):
        parts = [data.get("model", "")]
        if data.get("tokens_per_second"):
            parts.append(f"{data['tokens_per_second']:.1f} tokens/s")
        if data.get("first_token_ms") is not None:
            parts.append(f"first token {data['first_token_ms'] / 1000:.1f} s")
        if data.get("load_ms", 0) > 500:
            parts.append(f"model load {data['load_ms'] / 1000:.1f} s")
        parts.append(f"retrieval {data.get('retrieval_ms', 0):.0f} ms")
        parts.append(f"{data['input_tokens']:,} prompt · {data['output_tokens']:,} output tokens")
        parts.append(f"{data['calls']} model call{'s' if data['calls'] != 1 else ''}")
        st.caption(" · ".join(parts))
    if data.get("sources"):
        with st.expander(f"Retrieved evidence ({len(data['sources'])})"):
            for s in data["sources"]:
                st.markdown(f"**[{s['id']}: {s['title']}]({s['url']})** — {s['section']}")
                st.text(s["text"])


with chat_tab:
    if not store.stats()["chunks"]:
        st.info(
            "Your knowledge base is empty. Start a collection in Knowledge base, then index the articles."
        )
    if not st.session_state.messages:
        st.markdown("Try **How does the Electric Blast Furnace work?** or **What progression leads to LuV?**")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                show_answer(message["answer"])
            else:
                st.markdown(message["content"])
    if question := st.chat_input("Ask about machines, materials, or progression…"):
        history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                current = settings.model_copy(
                    update={
                        "llm_model": model,
                        "num_ctx": num_ctx,
                        "temperature": temperature,
                        "output_tokens": output_tokens,
                        "context_tokens": context,
                        "retrieval_limit": retrieval_limit,
                        "search_rounds": search_rounds,
                    }
                )
                if search_only:
                    with st.spinner("Searching your wiki…"):
                        found = get_index().search(question, limit=retrieval_limit)
                    answer = {
                        "text": "Retrieved local wiki passages. Expand the evidence below to read them."
                        if found
                        else "No indexed passages were found.",
                        "sources": [
                            {
                                "id": f"S{n}",
                                "title": c["title"],
                                "section": c["section"],
                                "url": c["url"],
                                "text": c["text"],
                            }
                            for n, c in enumerate(found, 1)
                        ],
                    }
                else:
                    activity = st.status("Searching your wiki…", expanded=False)
                    stream = st.empty()
                    buffer = []

                    def on_token(piece):
                        if not buffer:
                            activity.update(label="Writing the answer…")
                        buffer.append(piece)
                        stream.markdown("".join(buffer) + "▌")

                    def on_status(text):
                        # A new search round starts; text streamed so far was only a preamble.
                        buffer.clear()
                        stream.empty()
                        activity.update(label=text)

                    activity.update(label=f"Searching your wiki, then asking {model}…")
                    result = Answerer(get_index(), current).answer(question, history, on_token, on_status)
                    activity.update(label="Done", state="complete")
                    stream.empty()
                    answer = asdict(result)
                show_answer(answer)
                st.session_state.messages.append(
                    {"role": "assistant", "content": answer["text"], "answer": answer}
                )
            except Exception as exc:
                st.error(f"Could not answer ({type(exc).__name__}). Check the sidebar status and indexing status.")

with admin_tab:
    st.subheader("Local knowledge base")
    st.caption(f"Embedding model (CPU): {settings.embedding_model} · Data folder: {settings.data_dir}")

    @st.fragment(run_every="2s")
    def status_panel():
        counts = store.stats()
        cols = st.columns(4)
        for col, label, key in zip(
            cols,
            ["Articles", "Indexed articles", "Chunks", "Queued"],
            ["articles", "indexed_articles", "chunks", "pending"],
        ):
            col.metric(label, counts[key])
        external = writer_busy(settings.data_dir) and not jobs.running
        st.write(
            "A collection or indexing command is running in another process." if external else jobs.message
        )
        if external:
            st.caption(store.get("progress", "Check the command's terminal for progress."))
        if jobs.running or external:
            total = counts["done"] + counts["pending"] + counts["errors"] + counts.get("skipped", 0)
            st.progress(
                counts["done"] / max(1, total), text="Collection checkpoints are saved after each page"
            )
            if jobs.running and st.button("Cancel after current operation"):
                jobs.stop.set()
        if jobs.error:
            st.error(jobs.error)
        if jobs.result:
            st.json(jobs.result, expanded=False)
        if counts["errors"]:
            with st.expander(f"Collection errors ({counts['errors']})"):
                st.dataframe(store.errors(), use_container_width=True)

    status_panel()
    limit = st.number_input("Article limit (0 = all remaining articles)", min_value=0, value=20, step=10)
    cols = st.columns(4)
    for col, label, kind in zip(
        cols,
        ["Collect / resume", "Update wiki", "Index pending", "Rebuild index"],
        ["scrape", "update", "index", "rebuild"],
    ):
        if col.button(
            label, disabled=jobs.running or writer_busy(settings.data_dir), use_container_width=True
        ):
            jobs.start(kind, int(limit) or None)
            st.rerun()
    st.caption(
        "Collection uses permitted sitemap and article URLs, with rate limits. Updates recheck saved URLs; "
        "rebuild uses saved content. Run only one app/CLI writer per data directory."
    )
    with st.expander("Backup and restore"):
        st.write("Backups include original pages and cached embeddings. Your .env settings are excluded.")
        if st.button("Create backup", disabled=jobs.running or writer_busy(settings.data_dir)):
            try:
                target = (
                    settings.data_dir / "backups" / (datetime.now().strftime("gtnh-%Y%m%d-%H%M%S") + ".zip")
                )
                st.success(f"Saved {backup(store, target)}")
            except Exception as exc:
                st.error(str(exc))
        archive_path = st.text_input("Backup ZIP path")
        restore_path = st.text_input("Restore into an empty directory")
        if st.button("Restore backup", disabled=jobs.running or not archive_path or not restore_path):
            try:
                restore(archive_path, restore_path)
                st.success(
                    "Restored. Set GTNH_DATA_DIR to that directory, restart the app, and rebuild the index."
                )
            except Exception as exc:
                st.error(str(exc))
    st.caption("Wiki content: CC BY-SA 4.0 unless otherwise noted. This is an independent local assistant.")
