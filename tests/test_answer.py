from types import SimpleNamespace as NS

from gtnh_assistant.answer import Answerer
from gtnh_assistant.config import Settings


class StubIndex:
    def __init__(self):
        self.queries = []
        self.usage = []
        self.store = NS(record_usage=self.usage.append)

    def search(self, query):
        self.queries.append(query)
        return [
            {
                "id": query,
                "title": "EBF",
                "section": "Heat",
                "text": "Use coils rated 1800 K.",
                "url": "https://wiki.gtnewhorizons.com/wiki/Electric_Blast_Furnace#Heat",
            }
        ]


def response(text="Use 1800 K coils. [S1]", output=None):
    return NS(
        output_text=text,
        output=output or [],
        status="completed",
        usage=NS(input_tokens=100, output_tokens=20, input_tokens_details=NS(cached_tokens=30)),
    )


def client(responses):
    calls = []

    def create(**kwargs):
        calls.append(kwargs.copy())
        return responses.pop(0)

    return NS(responses=NS(create=create), calls=calls)


def test_citations_usage_and_bounded_history():
    index = StubIndex()
    api = client([response()])
    settings = Settings(input_price=1, cached_input_price=0.5, output_price=2, history_tokens=10)
    result = Answerer(index, settings, api).answer(
        "What coils?", [{"role": "user", "content": "old " * 1000}]
    )
    assert "[S1](https://wiki.gtnewhorizons.com" in result.text
    assert result.input_tokens == 100 and result.output_tokens == 20
    assert abs(result.estimated_cost - 0.000125) < 1e-10
    assert api.calls[0]["store"] is False
    assert len(api.calls[0]["input"][0]["content"]) < 1000
    assert index.usage[0]["input_tokens"] == 100


def test_additional_search_and_total_usage():
    tool = NS(
        type="function_call", name="search_wiki", call_id="call_1", arguments='{"query":"coil temperatures"}'
    )
    api = client([response(output=[tool]), response("The table says 1800 K. [S2]")])
    index = StubIndex()
    result = Answerer(index, Settings(), api).answer(
        "How does it heat?", [{"role": "user", "content": "EBF"}]
    )
    assert "EBF" in index.queries[0]
    assert index.queries[-1] == "coil temperatures"
    assert result.calls == 2 and result.input_tokens == 200
    assert result.output_tokens == 40
    assert result.estimated_cost is None


def test_no_evidence_does_not_call_api():
    index = StubIndex()
    index.search = lambda _: []
    api = client([])
    result = Answerer(index, Settings(), api).answer("Missing recipe")
    assert "no usable evidence" in result.text
    assert not api.calls


def test_unknown_citation_and_invented_url():
    api = client([response("Claim. [S99] https://evil.example")])
    result = Answerer(StubIndex(), Settings(), api).answer("Recipe")
    assert "evil.example" not in result.text
    assert "source unavailable" in result.text
    assert result.warnings


def test_failure_does_not_disclose_secret():
    def fail(**kwargs):
        raise RuntimeError("secret-key-example")

    api = NS(responses=NS(create=fail))
    result = Answerer(StubIndex(), Settings(), api).answer("Recipe")
    assert "secret-key-example" not in result.text
    assert "failed" in result.text


def test_quota_error_explains_action_without_leaking_key():
    class QuotaError(Exception):
        code = "credit_balance_exhausted"

    def fail(**kwargs):
        raise QuotaError("secret-key-example")

    result = Answerer(StubIndex(), Settings(), NS(responses=NS(create=fail))).answer("Recipe")
    assert "credit is exhausted" in result.text
    assert "secret-key-example" not in result.text
    assert result.sources


def test_tool_loop_stops_at_configured_limit():
    tool = NS(type="function_call", name="search_wiki", call_id="one", arguments='{"query":"another topic"}')
    api = client([response(output=[tool]), response(output=[tool])])
    result = Answerer(StubIndex(), Settings(search_rounds=1), api).answer("Question")
    assert result.calls == 2
    assert api.calls[-1]["tools"] == []
    assert "search limit" in result.text
