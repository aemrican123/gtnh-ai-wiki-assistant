"""End-to-end benchmark of the local assistant with real GTNH questions.

Run after indexing, with Ollama running:
    .venv\\Scripts\\python scripts\\benchmark_llm.py [--model qwen3.5:4b] [--num-ctx 8192]

It measures cold model load, first-token latency, generation speed, retrieval latency, process RAM and
GPU memory, and checks that citations resolve to retrieved wiki sources. Results are written to
data/benchmark-<model>-<timestamp>.json. Nothing is sent anywhere except the local Ollama server.
Answer quality still needs a human read: compare each answer with its cited passages.
"""

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from gtnh_assistant.answer import ADMITS_GAP, Answerer
from gtnh_assistant.cli import gpu_memory
from gtnh_assistant.config import Settings
from gtnh_assistant.index import Index
from gtnh_assistant.llm import OllamaClient
from gtnh_assistant.store import Store

# (question, follow-up-of-previous?, expectation)
QUESTIONS = [
    ("How does the Electric Blast Furnace work?", False, "grounded"),
    ("What heating coils does it need for higher temperatures?", True, "follow-up"),
    ("What materials do I need to construct the EBF?", False, "grounded"),
    ("How many EU/t does smelting aluminium require in an EBF?", False, "exact figure"),
    ("What progression is required to get into LuV?", False, "multi-article"),
    ("What is the difference between the Bricked Blast Furnace and Electric Blast Furnace?", False, "comparison"),
    ("How do I build a Cleanroom?", False, "grounded"),
    ("Explain the Assembly Line", False, "grounded"),
    ("How does the Distillation Tower work?", False, "grounded"),
    ("What does Pollution do?", False, "grounded"),
    ("What is the exact crafting recipe for the Quantum Banana Compressor?", False, "should admit gap"),
]


def rss_mb():
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / 1e6)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--num-ctx", type=int)
    parser.add_argument("--warm", action="store_true", help="Skip unloading the model before the first question")
    args = parser.parse_args()
    settings = Settings().prepare()
    updates = {k: v for k, v in {"llm_model": args.model, "num_ctx": args.num_ctx}.items() if v}
    settings = settings.model_copy(update=updates)
    client = OllamaClient(settings.ollama_host, timeout=settings.llm_timeout)
    print(f"Ollama {client.version()} · model {settings.llm_model} · num_ctx {settings.num_ctx}", flush=True)
    if not client.has_model(settings.llm_model):
        raise SystemExit(f"Model {settings.llm_model} is not installed. Run: ollama pull {settings.llm_model}")

    index = Index(Store(settings.data_dir), settings)
    started = time.perf_counter()
    index.search("Electric Blast Furnace")  # load the embedding model before timing retrieval
    embed_load_s = time.perf_counter() - started
    if not args.warm:
        client.unload(settings.llm_model)
        time.sleep(2)

    answerer = Answerer(index, settings, client)
    gpu_idle = gpu_memory()
    history, rows = [], []
    for number, (question, follow_up, expectation) in enumerate(QUESTIONS, 1):
        if not follow_up:
            history = []
        result = answerer.answer(question, history, on_token=lambda _: None)
        cited = sorted(set(re.findall(r"\[(S\d+)\]\(", result.text)))
        source_ids = {s["id"] for s in result.sources}
        admits_gap = bool(ADMITS_GAP.search(result.text))
        rows.append(
            {
                "question": question,
                "expectation": expectation,
                "answer": result.text,
                "warnings": result.warnings,
                "sources": [f"{s['id']} {s['title']} / {s['section']}" for s in result.sources],
                "articles": sorted({s["title"] for s in result.sources}),
                "citations": cited,
                "citations_valid": all(c in source_ids for c in cited),
                "admits_gap": admits_gap,
                "load_s": round(result.load_ms / 1000, 2),
                "first_token_s": round((result.first_token_ms or 0) / 1000, 2),
                "tokens_per_second": round(result.tokens_per_second or 0, 1),
                "retrieval_ms": round(result.retrieval_ms),
                "total_s": round(result.total_ms / 1000, 2),
                "prompt_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "model_calls": result.calls,
            }
        )
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": result.text}]
        r = rows[-1]
        print(
            f"{number:2}. {r['first_token_s']:5.1f}s first token · {r['tokens_per_second']:5.1f} tok/s · "
            f"{r['retrieval_ms']:4} ms retrieval · {len(r['articles'])} articles · "
            f"{len(cited)} citations{'' if r['citations_valid'] else ' (INVALID)'} · {question}",
            flush=True,
        )

    loaded = client.loaded_models()
    summary = {
        "model": settings.llm_model,
        "num_ctx": settings.num_ctx,
        "date": datetime.now().isoformat(timespec="seconds"),
        "embedding_model_load_s": round(embed_load_s, 2),
        "cold_model_load_s": rows[0]["load_s"],
        "median_first_token_s": sorted(r["first_token_s"] for r in rows[1:])[len(rows[1:]) // 2],
        "median_tokens_per_second": sorted(r["tokens_per_second"] for r in rows)[len(rows) // 2],
        "median_retrieval_ms": sorted(r["retrieval_ms"] for r in rows)[len(rows) // 2],
        "app_process_ram_mb": rss_mb(),
        "ollama_loaded": loaded,
        "gpu_before": gpu_idle,
        "gpu_after": gpu_memory(),
        "questions": rows,
    }
    target = Path(settings.data_dir) / (
        f"benchmark-{settings.llm_model.replace(':', '_').replace('/', '_')}-"
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    target.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "questions"}, indent=2))
    print(f"Full results, including every answer: {target}")


if __name__ == "__main__":
    main()
