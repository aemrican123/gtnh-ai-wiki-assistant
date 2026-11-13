"""Run after full indexing: python scripts/evaluate_retrieval.py (no paid API calls)."""

import json
from pathlib import Path

from gtnh_assistant.config import Settings
from gtnh_assistant.index import Index
from gtnh_assistant.store import Store

CASES = [
    ("How does the EBF work?", "Electric Blast Furnace", "heating coils"),
    ("What materials do I need to construct the EBF?", "Electric Blast Furnace", "16 Heating Coil"),
    ("How many EU/t does smelting aluminium require in an EBF?", "Electric Blast Furnace", "120 EU/t"),
    ("What progression is required to get into LuV?", "Ludicrous Voltage (LuV)", None),
    ("How do Heating Coils affect energy efficiency?", "Heating Coils", "900"),
    ("What does Pollution do?", "Pollution", None),
    ("Explain the Assembly Line", "Assembly Line", None),
    (
        "What is the difference between the Bricked Blast Furnace and Electric Blast Furnace?",
        "Bricked Blast Furnace",
        None,
    ),
    (
        "What is the difference between the Bricked Blast Furnace and Electric Blast Furnace?",
        "Electric Blast Furnace",
        None,
    ),
    ("How do I build a Cleanroom?", "Cleanroom", None),
    ("What is the role of a Fusion Reactor?", "Fusion Reactor", None),
    ("How does the Distillation Tower work?", "Distillation Tower", None),
]


def main():
    settings = Settings()
    index = Index(Store(settings.data_dir), settings)
    report = []
    for question, title, phrase in CASES:
        results = index.search(question)
        matched = [r for r in results if r["title"] == title]
        passed = bool(matched) and (
            phrase is None or any(phrase.casefold() in r["text"].casefold() for r in matched)
        )
        report.append(
            {
                "question": question,
                "expected_title": title,
                "expected_phrase": phrase,
                "passed": passed,
                "retrieved": [
                    {"title": r["title"], "section": r["section"], "url": r["url"]} for r in results
                ],
            }
        )
        print("PASS" if passed else "FAIL", question, "=>", title, flush=True)
    Path(settings.data_dir / "retrieval-evaluation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    raise SystemExit(0 if all(r["passed"] for r in report) else 1)


if __name__ == "__main__":
    main()
