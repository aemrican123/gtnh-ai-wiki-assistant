import argparse
import json
import shutil
import subprocess
import time
from dataclasses import asdict

from filelock import FileLock

from .config import Settings
from .store import Store


def gpu_memory():
    """NVIDIA GPU memory from nvidia-smi, or None when unavailable."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    name, used, total, util = [part.strip() for part in out.splitlines()[0].split(",")]
    return {"name": name, "memory_used_mb": int(used), "memory_total_mb": int(total), "utilization_percent": int(util)}


def doctor(settings, store):
    """Check every local component needed to answer questions and report what is missing."""
    from .llm import LLMError, OllamaClient

    report = {"ollama_host": settings.ollama_host, "model": settings.llm_model, "checks": {}}
    checks = report["checks"]
    client = OllamaClient(settings.ollama_host, timeout=settings.llm_timeout)
    checks["ollama_installed"] = bool(shutil.which("ollama"))
    try:
        checks["ollama_version"] = client.version()
        checks["ollama_running"] = True
    except LLMError as exc:
        checks["ollama_running"] = False
        checks["ollama_error"] = str(exc)
    if checks["ollama_running"]:
        models = client.list_models()
        checks["installed_models"] = models
        checks["model_available"] = client.has_model(settings.llm_model)
        if checks["model_available"]:
            started = time.perf_counter()
            try:
                reply = client.chat(
                    settings.llm_model,
                    [{"role": "user", "content": "Reply with the single word OK."}],
                    options={"num_ctx": settings.num_ctx, "num_predict": 16, "temperature": 0},
                    keep_alive=settings.keep_alive,
                    think=settings.think,
                    on_token=lambda _: None,
                )
                checks["inference"] = {
                    "reply": reply.content.strip()[:40],
                    "wall_ms": round((time.perf_counter() - started) * 1000),
                    "load_ms": round(reply.load_ms),
                    "first_token_ms": round(reply.first_token_ms or 0),
                    "tokens_per_second": round(reply.tokens_per_second or 0, 1),
                }
            except LLMError as exc:
                checks["inference_error"] = f"{type(exc).__name__}: {exc}"
            checks["loaded_models"] = client.loaded_models()
    checks["gpu"] = gpu_memory()
    checks["knowledge_base"] = store.stats()
    checks["embedding_model"] = settings.embedding_model
    report["ready"] = bool(
        checks.get("ollama_running") and checks.get("model_available") and "inference" in checks
        and checks["knowledge_base"]["chunks"]
    )
    return report


def main():
    parser = argparse.ArgumentParser(description="Local GTNH wiki assistant")
    parser.add_argument("--data-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    scrape = sub.add_parser("scrape", help="Collect permitted wiki articles; resumes checkpoints")
    scrape.add_argument("--limit", type=int)
    scrape.add_argument("--update", action="store_true")
    scrape.add_argument("--retry-errors", action="store_true")
    scrape.add_argument("--seed", action="append")
    index = sub.add_parser("index", help="Embed changed articles locally")
    index.add_argument("--rebuild", action="store_true")
    sub.add_parser("status")
    sub.add_parser("doctor", help="Check Ollama, the model, GPU use and the knowledge base")
    value = sub.add_parser("config-value", help="Print one setting (used by start_gtnh.bat)")
    value.add_argument("name")
    search = sub.add_parser("search")
    search.add_argument("query")
    ask = sub.add_parser("ask", help="Answer a question with the local Ollama model")
    ask.add_argument("question")
    ask.add_argument("--model", help="Override GTNH_LLM_MODEL for this question")
    back = sub.add_parser("backup")
    back.add_argument("destination")
    rest = sub.add_parser("restore")
    rest.add_argument("archive")
    rest.add_argument("destination", help="An empty directory")
    args = parser.parse_args()
    settings = Settings(**({"data_dir": args.data_dir} if args.data_dir else {}))
    if args.command == "config-value":
        if args.name not in Settings.model_fields:
            parser.error(f"unknown setting: {args.name}")
        value = getattr(settings, args.name)
        if args.name == "ollama_host":
            from .llm import normalize_host

            value = normalize_host(value)
        print(value)
        return
    settings.prepare()
    store = Store(settings.data_dir)
    if args.command == "status":
        output = store.stats() | {"failures": store.errors()}
    elif args.command == "doctor":
        output = doctor(settings, store)
    elif args.command == "scrape":
        from .scrape import crawl

        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be positive")
        with FileLock(str(settings.data_dir / "writer.lock"), timeout=0):
            if args.retry_errors:
                store.retry_errors()
            output = crawl(
                store,
                settings,
                limit=args.limit,
                update=args.update,
                seeds=args.seed,
                progress=lambda x: print(x, flush=True),
            )
    elif args.command in {"index", "search", "ask"}:
        from .index import Index

        index = Index(store, settings)
        if args.command == "index":
            with FileLock(str(settings.data_dir / "writer.lock"), timeout=0):
                output = index.sync(rebuild=args.rebuild, progress=lambda x: print(x, flush=True))
        elif args.command == "search":
            output = index.search(args.query)
        else:
            from .answer import Answerer

            if args.model:
                settings = settings.model_copy(update={"llm_model": args.model})
            output = asdict(Answerer(index, settings).answer(args.question))
    elif args.command == "backup":
        from .backup import backup

        output = {"backup": str(backup(store, args.destination))}
    else:
        from .backup import restore

        output = restore(args.archive, args.destination).stats()
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
