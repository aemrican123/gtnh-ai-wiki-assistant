from types import SimpleNamespace as NS

from gtnh_assistant.answer import SEARCH_TOOL, Answerer
from gtnh_assistant.config import Settings
from gtnh_assistant.llm import ChatResult, ModelNotFound, OllamaUnavailable


class StubIndex:
    def __init__(self, entities=None):
        self.queries = []
        self.usage = []
        self.entity_map = entities or {}
        self.store = NS(record_usage=self.usage.append, entities=self.find_entities)

    def find_entities(self, text):
        return {k: v for k, v in self.entity_map.items() if v.casefold() in text.casefold()}

    def search(self, query, limit=None):
        self.queries.append(query)
        return [
            {
                "id": query,
                "article_id": "65",
                "title": "EBF",
                "section": "Heat",
                "text": "Use coils rated 1800 K.",
                "url": "https://wiki.gtnewhorizons.com/wiki/Electric_Blast_Furnace#Heat",
            }
        ]


def reply(text="Use 1800 K coils. [S1]", tool_calls=None, done_reason="stop"):
    return ChatResult(
        content=text,
        tool_calls=tool_calls or [],
        done_reason=done_reason,
        prompt_tokens=100,
        output_tokens=20,
        load_ms=1500,
        eval_ms=500,
        total_ms=2100,
        first_token_ms=1600,
    )


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, model, messages, tools=None, options=None, keep_alive=None, think=None, on_token=None):
        self.calls.append(
            {
                "model": model,
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "options": options,
                "think": think,
            }
        )
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        if on_token and result.content:
            on_token(result.content)
        return result


def search_call(query="coil temperatures"):
    return [{"name": "search_wiki", "arguments": {"query": query}}]


def test_citations_metrics_and_bounded_history():
    index = StubIndex()
    api = FakeClient([reply()])
    settings = Settings(history_tokens=10, llm_model="qwen3.5:9b")
    streamed = []
    result = Answerer(index, settings, api).answer(
        "What coils?", [{"role": "user", "content": "old " * 1000}], on_token=streamed.append
    )
    assert "[S1](https://wiki.gtnewhorizons.com" in result.text
    assert streamed == ["Use 1800 K coils. [S1]"]
    assert result.input_tokens == 100 and result.output_tokens == 20
    assert result.tokens_per_second == 40 and result.load_ms == 1500
    assert result.model == "qwen3.5:9b"
    call = api.calls[0]
    assert call["model"] == "qwen3.5:9b" and call["think"] is False
    assert call["options"] == {"num_ctx": 8192, "temperature": 0.2, "num_predict": 1000}
    assert call["messages"][0]["role"] == "system"
    assert len(call["messages"][1]["content"]) < 1000
    assert call["tools"] == [SEARCH_TOOL]
    assert index.usage[0]["output_tokens"] == 20 and index.usage[0]["model"] == "qwen3.5:9b"
    assert not result.warnings


def test_additional_search_round_uses_tool_messages():
    api = FakeClient([reply("", tool_calls=search_call()), reply("The table says 1800 K. [S2]")])
    index = StubIndex()
    statuses = []
    result = Answerer(index, Settings(), api).answer(
        "How does it heat?", [{"role": "user", "content": "EBF"}], on_status=statuses.append
    )
    assert "EBF" in index.queries[0]
    assert index.queries[-1] == "coil temperatures"
    assert statuses == ["Searching the wiki for: coil temperatures"]
    second = api.calls[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "search_wiki"
    assert second[-1] == {"role": "tool", "tool_name": "search_wiki", "content": second[-1]["content"]}
    assert "[S2]" in second[-1]["content"]
    assert result.calls == 2 and result.input_tokens == 200 and result.output_tokens == 40


def test_follow_up_reuses_entities_from_earlier_question():
    index = StubIndex({"65": "Electric Blast Furnace"})
    api = FakeClient([reply()])
    history = [
        {"role": "user", "content": "How does the Electric Blast Furnace work?"},
        {"role": "assistant", "content": "It smelts. [S1]"},
    ]
    Answerer(index, Settings(), api).answer("And at higher tiers?", history)
    assert index.queries[0] == "And at higher tiers? Electric Blast Furnace"


def test_question_naming_its_own_subject_is_not_rewritten():
    index = StubIndex({"65": "Electric Blast Furnace", "70": "Cleanroom"})
    history = [{"role": "user", "content": "How does the Electric Blast Furnace work?"}]
    Answerer(index, Settings(), FakeClient([reply()])).answer("How do I build a Cleanroom?", history)
    assert index.queries[0] == "How do I build a Cleanroom?"


def test_linked_articles_are_off_by_default():
    index = StubIndex({"65": "EBF", "80": "1800 K"})
    Answerer(index, Settings(), FakeClient([reply()])).answer("What do I need before the EBF?")
    assert index.queries[1:] == []


def test_linked_articles_only_keep_the_linked_article():
    index = StubIndex({"65": "EBF", "80": "1800 K"})
    api = FakeClient([reply()])
    result = Answerer(index, Settings(linked_articles=2), api).answer("What do I need before the EBF?")
    assert index.queries[1:] == ["1800 K"]
    # The stub returns article 65 for every query, so the linked search adds nothing.
    assert len(result.sources) == 1


def test_citation_reminder_ends_the_prompt():
    api = FakeClient([reply()])
    Answerer(StubIndex(), Settings(), api).answer("Q")
    assert api.calls[0]["messages"][1]["content"].endswith("right after every fact you take from it.")


def test_no_evidence_does_not_call_model():
    index = StubIndex()
    index.search = lambda query, limit=None: []
    api = FakeClient([])
    result = Answerer(index, Settings(), api).answer("Missing recipe")
    assert "no usable evidence" in result.text
    assert not api.calls


def test_unknown_citation_and_invented_url():
    api = FakeClient([reply("Claim. [S99] https://evil.example")])
    result = Answerer(StubIndex(), Settings(), api).answer("Recipe")
    assert "evil.example" not in result.text
    assert "source unavailable" in result.text
    assert result.warnings


def test_missing_citations_are_flagged():
    result = Answerer(StubIndex(), Settings(), FakeClient([reply("Just trust me.")])).answer("Recipe")
    assert any("no source citations" in w for w in result.warnings)


def test_reasoning_block_is_removed():
    result = Answerer(StubIndex(), Settings(), FakeClient([reply("<think>hmm</think>1800 K. [S1]")])).answer(
        "Q"
    )
    assert "hmm" not in result.text and result.text.startswith("1800 K.")


def test_ollama_down_explains_how_to_start_it_and_keeps_sources():
    api = FakeClient([OllamaUnavailable("refused")])
    result = Answerer(StubIndex(), Settings(), api).answer("Recipe")
    assert "Ollama is not running" in result.text and "start_gtnh.bat" in result.text
    assert result.sources
    assert not any("no source citations" in w for w in result.warnings)


def test_missing_model_names_the_pull_command():
    api = FakeClient([ModelNotFound("missing")])
    result = Answerer(StubIndex(), Settings(llm_model="qwen3.5:9b"), api).answer("Recipe")
    assert "ollama pull qwen3.5:9b" in result.text


def test_unexpected_failure_does_not_disclose_details():
    api = FakeClient([RuntimeError("internal-detail-example")])
    result = Answerer(StubIndex(), Settings(), api).answer("Recipe")
    assert "internal-detail-example" not in result.text
    assert "failed" in result.text


def test_tool_loop_stops_at_configured_limit():
    api = FakeClient(
        [reply("", tool_calls=search_call("another topic")), reply("", tool_calls=search_call())]
    )
    result = Answerer(StubIndex(), Settings(search_rounds=1), api).answer("Question")
    assert result.calls == 2
    assert api.calls[-1]["tools"] is None
    assert "search limit" in result.text


def test_malformed_tool_call_is_answered_not_crashed():
    bad = [{"name": "search_wiki", "arguments": None}]
    api = FakeClient([reply("", tool_calls=bad), reply("1800 K. [S1]")])
    result = Answerer(StubIndex(), Settings(), api).answer("Question")
    assert api.calls[1]["messages"][-1]["content"] == "Invalid search request."
    assert "1800 K." in result.text


def test_evidence_budget_shrinks_to_fit_small_context_window():
    settings = Settings(num_ctx=4096, output_tokens=1000, context_tokens=5000)
    result = Answerer(StubIndex(), settings, FakeClient([reply()])).answer("Question")
    assert any("Evidence was limited" in w for w in result.warnings)


def test_context_window_too_small_is_explained_without_calling_model():
    api = FakeClient([])
    settings = Settings(num_ctx=2048, output_tokens=1500)
    result = Answerer(StubIndex(), settings, api).answer("Question")
    assert "too small" in result.text and not api.calls


def test_truncated_output_is_reported():
    result = Answerer(
        StubIndex(), Settings(), FakeClient([reply("Partial [S1]", done_reason="length")])
    ).answer("Q")
    assert any("output limit" in w for w in result.warnings)


def sources(n):
    return [
        {
            "id": f"S{i}",
            "title": "Pollution",
            "section": "Basics",
            "url": f"https://wiki.gtnewhorizons.com/wiki/P{i}",
        }
        for i in range(1, n + 1)
    ]


def test_grouped_citations_are_split_and_linked():
    from gtnh_assistant.answer import Answer as AnswerResult
    from gtnh_assistant.answer import finalize_citations

    result = AnswerResult(
        text="Explosions pollute [S1, S2] and rockets too [S1; S2].", sources=sources(2), calls=1
    )
    finalize_citations(result)
    assert result.text.count("](https://") == 4 and "[S1, S2]" not in result.text
    assert not result.warnings


def test_admitted_gap_needs_no_citation_warning():
    from gtnh_assistant.answer import ADMITS_GAP, finalize_citations
    from gtnh_assistant.answer import Answer as AnswerResult

    result = AnswerResult(
        text="The wiki evidence does not mention a Quantum Banana Compressor.", sources=sources(1), calls=1
    )
    finalize_citations(result)
    assert result.warnings == []
    assert not ADMITS_GAP.search('It shows the error "not enough output space" in the GUI.')
