"""Run with: python -m streamlit run app.py --server.address 127.0.0.1"""

import math
from dataclasses import asdict
from datetime import datetime

import streamlit as st

from gtnh_assistant.answer import Answerer
from gtnh_assistant.backup import backup, restore
from gtnh_assistant.config import Settings
from gtnh_assistant.index import Index
from gtnh_assistant.jobs import Jobs, writer_busy
from gtnh_assistant.store import Store

st.set_page_config(page_title="GTNH Field Guide", page_icon="⚙️", layout="wide")


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


settings, store, get_index, jobs = resources()
st.title("GTNH Field Guide")
st.caption("Your local wiki companion · Answers with evidence, from steam to the Stargate")

with st.sidebar:
    st.subheader("Answer settings")
    search_only = st.checkbox("Search local wiki without an API call", value=False)
    api_key = st.text_input(
        "OpenAI API key", type="password", help="Session only. Or set OPENAI_API_KEY in .env."
    )
    model = st.text_input("OpenAI model", value=settings.openai_model)
    context = st.slider("Evidence budget (tokens)", 500, 20000, settings.context_tokens, 500)
    st.caption("Embeddings and search run locally. Questions and selected passages go to OpenAI.")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    with st.expander("Cost estimate settings"):
        st.caption("Enter verified USD prices per million tokens. Blank means unknown.")
        input_price = st.text_input(
            "Input price", value="" if settings.input_price is None else str(settings.input_price)
        )
        cached_price = st.text_input(
            "Cached input price",
            value="" if settings.cached_input_price is None else str(settings.cached_input_price),
        )
        output_price = st.text_input(
            "Output price", value="" if settings.output_price is None else str(settings.output_price)
        )
        price_date = st.text_input("Price verification date", value=settings.price_date)

chat_tab, admin_tab = st.tabs(["Ask the wiki", "Knowledge base"])
if "messages" not in st.session_state:
    st.session_state.messages = []


def show_answer(data):
    st.markdown(data["text"])
    for warning in data.get("warnings", []):
        st.warning(warning)
    if data.get("calls"):
        cost = data.get("estimated_cost")
        cost_label = f"${cost:.6f} estimated" if cost is not None else "cost estimate unavailable"
        st.caption(
            f"{data['input_tokens']:,} input · {data['cached_input_tokens']:,} cached · "
            f"{data['output_tokens']:,} output tokens · {data['calls']} API calls · {cost_label}"
        )
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
        with st.chat_message("assistant"), st.spinner("Searching your wiki and checking evidence…"):
            try:

                def price(value):
                    if not value.strip():
                        return None
                    amount = float(value)
                    if amount < 0 or not math.isfinite(amount):
                        raise ValueError("Prices must be finite, nonnegative amounts")
                    return amount

                current = settings.model_copy(
                    update={
                        "openai_api_key": api_key or settings.openai_api_key,
                        "openai_model": model,
                        "context_tokens": context,
                        "input_price": price(input_price),
                        "cached_input_price": price(cached_price),
                        "output_price": price(output_price),
                        "price_date": price_date,
                    }
                )
                if search_only:
                    found = get_index().search(question)
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
                    answer = asdict(Answerer(get_index(), current).answer(question, history))
                show_answer(answer)
                st.session_state.messages.append(
                    {"role": "assistant", "content": answer["text"], "answer": answer}
                )
            except Exception as exc:
                st.error(f"Could not answer ({type(exc).__name__}). Check settings and the indexing status.")

with admin_tab:
    st.subheader("Local knowledge base")

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
            total = counts["done"] + counts["pending"] + counts["errors"]
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
        st.write("Backups include original pages and cached embeddings. API keys are excluded.")
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
