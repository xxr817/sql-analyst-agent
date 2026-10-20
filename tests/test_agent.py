"""Tests the agent loop offline with a scripted fake client (no API key needed)."""
from pathlib import Path
from types import SimpleNamespace as NS

from sql_agent import SQLAgent

DB = Path(__file__).resolve().parents[1] / "data" / "autos.db"


def tool_use(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def text(t):
    return NS(type="text", text=t)


class FakeClient:
    """Returns pre-scripted responses and records what the agent sent."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content, stop = self._responses.pop(0)
        return NS(content=content, stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


def test_self_correction_after_sql_error():
    client = FakeClient(
        [
            ([tool_use("1", "list_tables")], "tool_use"),
            ([tool_use("2", "run_sql", query="SELECT nme FROM brands")], "tool_use"),  # typo
            ([tool_use("3", "run_sql", query="SELECT COUNT(*) FROM brands")], "tool_use"),
            ([text("Es gibt 10 Marken (synthetische Demo-Daten).")], "end_turn"),
        ]
    )
    result = SQLAgent(DB, client=client).run("Wie viele Marken gibt es?")

    assert result.answer.startswith("Es gibt 10 Marken")
    assert [s.tool for s in result.steps] == ["list_tables", "run_sql", "run_sql"]
    assert result.steps[1].is_error and "no such column" in result.steps[1].output
    assert result.sql_errors == 1
    assert result.final_result.rows[0][0] == 10
    # The error message must have been sent back to the model:
    # messages: [question, assistant, tool_result, assistant, tool_result(error), ...]
    sent = client.calls[2]["messages"][4]["content"][0]
    assert sent["is_error"] is True and "FEHLER" in sent["content"]
    assert result.input_tokens == 40


def test_guardrail_blocks_and_reports_to_model():
    client = FakeClient(
        [
            ([tool_use("1", "run_sql", query="DROP TABLE brands")], "tool_use"),
            ([text("Das ist nicht erlaubt.")], "end_turn"),
        ]
    )
    result = SQLAgent(DB, client=client).run("Lösche alles")
    assert result.steps[0].is_error
    assert "BLOCKIERT" in result.steps[0].output
    assert result.final_result is None


def test_stops_after_max_steps():
    looping = [([tool_use(str(i), "list_tables")], "tool_use") for i in range(5)]
    result = SQLAgent(DB, client=FakeClient(looping), max_steps=3).run("?")
    assert result.stopped_early
    assert len(result.steps) == 3
