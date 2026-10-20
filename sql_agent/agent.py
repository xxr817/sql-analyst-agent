"""The agent loop: think -> call a tool -> observe -> repeat until done.

Written without an agent framework on purpose, so every step is visible:
1. Send the question plus tool definitions to Claude.
2. If Claude answers with `tool_use` blocks, execute them locally.
3. Send the results (or the error message) back as `tool_result` blocks.
4. Repeat until Claude gives a final text answer or `max_steps` is reached.

Errors from SQL are returned to the model instead of crashing, which lets the
agent read the error and correct its own query (self-correction).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SPECS, Database, GuardrailError, QueryResult

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")


@dataclass
class Step:
    tool: str
    input: dict[str, Any]
    output: str
    is_error: bool = False


@dataclass
class AgentResult:
    question: str
    answer: str
    steps: list[Step] = field(default_factory=list)
    final_sql: str | None = None
    final_result: QueryResult | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    stopped_early: bool = False

    @property
    def sql_errors(self) -> int:
        return sum(1 for s in self.steps if s.tool == "run_sql" and s.is_error)


class SQLAgent:
    def __init__(self, db_path, client=None, model: str | None = None, max_steps: int = 10):
        self.db = Database(db_path)
        if client is None:
            import anthropic  # imported lazily so tests run without the SDK/key

            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        self.client = client
        self.model = model or DEFAULT_MODEL
        self.max_steps = max_steps

    # ---- tool execution -------------------------------------------------
    def _execute(self, name: str, args: dict[str, Any], result: AgentResult) -> Step:
        try:
            if name == "list_tables":
                output = ", ".join(self.db.list_tables())
            elif name == "describe_table":
                output = self.db.describe_table(args["table"])
            elif name == "run_sql":
                qr = self.db.run_sql(args["query"])
                result.final_sql, result.final_result = args["query"], qr
                output = qr.as_text() if qr.rows else "(keine Zeilen)"
            else:
                raise ValueError(f"Unbekanntes Werkzeug: {name}")
            return Step(name, args, output)
        except GuardrailError as exc:
            return Step(name, args, f"BLOCKIERT durch Sicherheitsregel: {exc}", True)
        except Exception as exc:  # SQL errors go back to the model for self-correction
            return Step(name, args, f"FEHLER: {type(exc).__name__}: {exc}", True)

    # ---- main loop --------------------------------------------------------
    def run(self, question: str, on_step=None) -> AgentResult:
        result = AgentResult(question=question, answer="")
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

        for _ in range(self.max_steps):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOL_SPECS,
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                result.input_tokens += getattr(usage, "input_tokens", 0) or 0
                result.output_tokens += getattr(usage, "output_tokens", 0) or 0

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                result.answer = "\n".join(
                    b.text for b in response.content if getattr(b, "type", "") == "text"
                ).strip()
                return result

            tool_results = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                step = self._execute(block.name, dict(block.input or {}), result)
                result.steps.append(step)
                if on_step:
                    on_step(step)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": step.output,
                        "is_error": step.is_error,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        result.stopped_early = True
        result.answer = (
            "Abgebrochen: Die maximale Anzahl an Schritten wurde erreicht, "
            "ohne dass eine abschließende Antwort vorlag."
        )
        return result
