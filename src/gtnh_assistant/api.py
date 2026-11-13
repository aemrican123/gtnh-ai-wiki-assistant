"""Local HTTP API for the React interface (``frontend/``). Bound to 127.0.0.1 only.

Run with ``python -m gtnh_assistant.api`` (or ``start_gtnh.bat``). It reuses the existing modules unchanged:
``Answerer`` for streaming answers, ``Jobs`` for collection/indexing and ``backup`` for backups.
"""

import argparse
import json
import queue
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .answer import Answerer
from .backup import backup, restore
from .config import Settings
from .index import Index
from .jobs import Jobs, writer_busy
from .lifecycle import Lifecycle
from .llm import LLMError, OllamaClient
from .store import Store

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
STATUS_TTL = 10.0


class Options(BaseModel):
    """Per-question overrides; ranges match ``Settings``."""

    model: str | None = Field(default=None, max_length=200)
    num_ctx: int | None = Field(default=None, ge=2048, le=131072)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    output_tokens: int | None = Field(default=None, ge=200, le=8000)
    context_tokens: int | None = Field(default=None, ge=500, le=20000)
    retrieval_limit: int | None = Field(default=None, ge=1, le=30)
    search_rounds: int | None = Field(default=None, ge=0, le=3)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=40000)


class AskRequest(BaseModel):
    question: str = Field(max_length=20000)
    history: list[Turn] = Field(default_factory=list, max_length=100)
    options: Options = Field(default_factory=Options)
    search_only: bool = False


class JobRequest(BaseModel):
    kind: Literal["scrape", "update", "index", "rebuild"]
    limit: int | None = Field(default=None, ge=0)


class RestoreRequest(BaseModel):
    archive: str = Field(min_length=1)
    destination: str = Field(min_length=1)


def source_view(n, chunk):
    return {
        "id": f"S{n}",
        "title": chunk["title"],
        "section": chunk["section"],
        "url": chunk["url"],
        "text": chunk["text"],
    }


def create_app(
    settings=None, client_factory=None, index_factory=None, chat_client_factory=None, gpu=None, lifecycle=None
):
    """Build the app. The factories exist so tests can run without Ollama or an embedding model.

    ``lifecycle`` (optional) is told about every request so the app can stop when its window closes."""
    settings = (settings or Settings()).prepare()
    store = Store(settings.data_dir)
    holder = {}
    lock = threading.Lock()

    def get_index():
        # Lazy: the UI and status endpoints must not wait for the embedding model to load.
        with lock:
            if "index" not in holder:
                holder["index"] = (index_factory or (lambda: Index(store, settings)))()
            return holder["index"]

    jobs = Jobs(store, settings, get_index)
    client_factory = client_factory or (lambda: OllamaClient(settings.ollama_host, timeout=5))
    chat_client_factory = chat_client_factory or (
        lambda s: OllamaClient(s.ollama_host, timeout=s.llm_timeout)
    )
    if gpu is None:
        from .cli import gpu_memory as gpu
    cache = {}

    def ollama_status(refresh=False):
        """Cached briefly so polling the status does not hit Ollama or nvidia-smi every time."""
        hit = cache.get("status")
        if hit and not refresh and time.monotonic() - hit[0] < STATUS_TTL:
            return hit[1]
        client = client_factory()
        try:
            status = {
                "ok": True,
                "host": settings.ollama_host,
                "version": client.version(),
                "models": client.list_models(),
                "loaded": client.loaded_models(),
            }
        except LLMError as exc:
            status = {
                "ok": False,
                "host": settings.ollama_host,
                "error": str(exc),
                "models": [],
                "loaded": [],
            }
        try:
            status["gpu"] = gpu()
        except Exception:
            status["gpu"] = None
        cache["status"] = (time.monotonic(), status)
        return status

    def job_state():
        external = writer_busy(settings.data_dir) and not jobs.running
        return {
            "running": jobs.running,
            "external": external,
            "message": jobs.message,
            "progress": store.get("progress") if external else None,
            "error": jobs.error,
            "result": jobs.result,
        }

    app = FastAPI(title="GTNH Field Guide", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.jobs = jobs
    app.state.store = store
    app.state.settings = settings
    app.state.models_used = {settings.llm_model}
    if lifecycle is not None:
        lifecycle.busy = lambda: jobs.running

        @app.middleware("http")
        async def track_activity(request: Request, call_next):
            lifecycle.seen()
            return await call_next(request)

    @app.post("/api/closing", status_code=204)
    def closing():
        """Beacon sent by the interface when its window closes or reloads."""
        if lifecycle is not None:
            lifecycle.closing()
        return Response(status_code=204)

    @app.get("/api/status")
    def status(refresh: bool = False):
        return {
            "ollama": ollama_status(refresh),
            "knowledge_base": store.stats(),
            "job": job_state(),
            "defaults": {
                "model": settings.llm_model,
                "num_ctx": settings.num_ctx,
                "temperature": settings.temperature,
                "output_tokens": settings.output_tokens,
                "context_tokens": settings.context_tokens,
                "retrieval_limit": settings.retrieval_limit,
                "search_rounds": settings.search_rounds,
            },
            "embedding_model": settings.embedding_model,
            "data_dir": str(settings.data_dir),
        }

    @app.get("/api/knowledge-base")
    def knowledge_base():
        return {"stats": store.stats(), "job": job_state()}

    @app.get("/api/search")
    def search(q: str, limit: int = 8):
        if not q.strip():
            return {"sources": []}
        found = get_index().search(q, limit=max(1, min(limit, 30)))
        return {"sources": [source_view(n, c) for n, c in enumerate(found, 1)]}

    @app.post("/api/ask")
    def ask(request: AskRequest):
        overrides = {
            {"model": "llm_model"}.get(key, key): value
            for key, value in request.options.model_dump().items()
            if value is not None
        }
        current = settings.model_copy(update=overrides)
        app.state.models_used.add(current.llm_model)
        history = [turn.model_dump() for turn in request.history]
        events = queue.Queue()

        def emit(kind, **payload):
            events.put(json.dumps({"type": kind, **payload}) + "\n")

        def work():
            try:
                if request.search_only:
                    emit("status", text="Searching your wiki…")
                    found = get_index().search(request.question, limit=current.retrieval_limit)
                    text = (
                        "Retrieved local wiki passages. Open the evidence below to read them."
                        if found
                        else "No indexed passages were found."
                    )
                    answer = {"text": text, "sources": [source_view(n, c) for n, c in enumerate(found, 1)]}
                else:
                    emit("status", text=f"Searching your wiki, then asking {current.llm_model}…")
                    seen = []

                    def on_token(piece):
                        if not seen:
                            seen.append(True)
                            emit("status", text="Writing the answer…")
                        emit("token", text=piece)

                    def on_status(text):
                        # A new search round starts; text streamed so far was only a preamble.
                        seen.clear()
                        emit("reset")
                        emit("status", text=text)

                    answerer = Answerer(get_index(), current, chat_client_factory(current))
                    result = answerer.answer(request.question, history, on_token, on_status)
                    answer = asdict(result)
                    for source in answer["sources"]:
                        source.pop("article_id", None)
                emit("final", answer=answer)
            except Exception as exc:
                emit(
                    "error",
                    message=f"Could not answer ({type(exc).__name__}). Check the Ollama and index status.",
                )
            finally:
                events.put(None)

        if lifecycle is not None:
            lifecycle.stream_started()
        threading.Thread(target=work, name="gtnh-answer", daemon=True).start()

        def stream():
            try:
                while (item := events.get()) is not None:
                    yield item
            finally:
                if lifecycle is not None:
                    lifecycle.stream_finished()

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.post("/api/jobs")
    def start_job(request: JobRequest):
        if jobs.running or writer_busy(settings.data_dir):
            raise HTTPException(409, "Another collection or indexing job is already running")
        if not jobs.start(request.kind, request.limit or None):
            raise HTTPException(409, "Another job is already running")
        return job_state()

    @app.post("/api/jobs/cancel")
    def cancel_job():
        if jobs.running:
            jobs.stop.set()
        return job_state()

    @app.get("/api/errors")
    def errors():
        return {"errors": store.errors()}

    @app.post("/api/backup")
    def create_backup():
        if jobs.running or writer_busy(settings.data_dir):
            raise HTTPException(409, "Wait for the running job to finish before creating a backup")
        target = settings.data_dir / "backups" / (datetime.now().strftime("gtnh-%Y%m%d-%H%M%S") + ".zip")
        try:
            return {"path": str(backup(store, target))}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/restore")
    def restore_backup(request: RestoreRequest):
        if jobs.running:
            raise HTTPException(409, "Wait for the running job to finish before restoring")
        try:
            restore(request.archive, request.destination)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from None
        return {
            "message": "Restored. Set GTNH_DATA_DIR to that directory, restart the app, and rebuild the index."
        }

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        index_html = FRONTEND / "index.html"
        if not index_html.exists():
            raise HTTPException(
                503, "The interface is not built. Run `npm install` and `npm run build` in frontend/."
            )
        candidate = (FRONTEND / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(FRONTEND):
            return FileResponse(candidate)
        return FileResponse(index_html)

    return app


def unload_models(app):
    """Free GPU memory for the models this app used, if they are still loaded."""
    settings = app.state.settings
    client = OllamaClient(settings.ollama_host, timeout=10)
    try:
        loaded = {m["name"] for m in client.loaded_models()}
        for model in app.state.models_used & loaded:
            client.unload(model)
    except LLMError:
        pass


def serve(port=8501, exit_when_closed=False, on_ready=None):
    """Run the app until stopped (Ctrl+C), or, with ``exit_when_closed``, until its window has closed."""
    import uvicorn

    holder = {}
    lifecycle = (
        Lifecycle(on_idle=lambda: setattr(holder["server"], "should_exit", True))
        if exit_when_closed
        else None
    )
    app = create_app(lifecycle=lifecycle)
    # Loopback only: the app has no authentication and must not be reachable from the network.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    holder["server"] = server
    if on_ready:

        def wait_until_started():
            while not server.started and not server.should_exit:
                time.sleep(0.1)
            if server.started:
                on_ready()

        threading.Thread(target=wait_until_started, daemon=True).start()
    if lifecycle is not None:
        lifecycle.start()
    try:
        server.run()
    finally:
        if exit_when_closed:
            unload_models(app)
    return server.started


def main():
    parser = argparse.ArgumentParser(description="Serve the GTNH Field Guide interface on this computer")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument(
        "--exit-when-closed", action="store_true", help="stop and unload the model once the app window closes"
    )
    args = parser.parse_args()
    serve(args.port, args.exit_when_closed)


if __name__ == "__main__":
    main()
