"""Evaluate the agent against questions with known correct answers.

Two metrics are reported for every question:

1. Execution accuracy (strict): the reference ("gold") SQL is executed and its
   result is compared with the result of the agent's LAST successful query.
   Column names and row order are ignored; numbers are compared after rounding
   to one decimal. Extra rows or derived values computed outside SQL count as
   wrong - this is the classic, strict Text-to-SQL metric.

2. Answer accuracy: every value of the gold result (names and numbers) must
   appear in the agent's natural-language answer. German number formats such as
   "137.134" or "98,1" are understood. This measures what the user actually sees.

Usage:
    python eval/run_eval.py                       # all questions
    python eval/run_eval.py --limit 3             # quick, cheaper check
    python eval/run_eval.py --label v2            # saves eval/results/v2.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "autos.db"
NUMBER = re.compile(r"-?\d[\d.,]*")


def _norm(value):
    if isinstance(value, (int, float)):
        return round(float(value), 1)
    return str(value).strip().lower()


def results_match(gold_rows, agent_rows) -> bool:
    """Strict: same number of rows, each gold row's values found in a distinct agent row."""
    if agent_rows is None or len(agent_rows) != len(gold_rows):
        return False
    remaining = [[_norm(v) for v in row] for row in agent_rows]
    for g in gold_rows:
        g_vals = [_norm(v) for v in g]
        for i, cand in enumerate(remaining):
            pool = list(cand)
            if all(v in pool and not pool.remove(v) for v in g_vals):
                remaining.pop(i)
                break
        else:
            return False
    return True


def numbers_in_text(text: str) -> set[float]:
    """Extract numbers, accepting German (1.234,5) and English (1,234.5) formats."""
    text = re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", text)  # "66 700" -> "66700"
    found: set[float] = set()
    for token in NUMBER.findall(text):
        token = token.rstrip(".,")
        for candidate in (token.replace(".", "").replace(",", "."), token.replace(",", "")):
            try:
                found.add(round(float(candidate), 1))
            except ValueError:
                pass
    return found


def answer_contains(gold_rows, answer: str) -> bool:
    """Answer-level: all gold values (names and numbers) appear in the answer text."""
    if not answer:
        return False
    text, numbers = answer.lower(), numbers_in_text(answer)
    for row in gold_rows:
        for value in row:
            if isinstance(value, (int, float)):
                if round(float(value), 1) not in numbers:
                    return False
            elif str(value).strip().lower() not in text:
                return False
    return True


def main() -> int:
    from dotenv import load_dotenv

    from sql_agent import Database, SQLAgent

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--label", default="latest", help="name of the results file")
    args = parser.parse_args()

    questions = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    questions = questions[: args.limit] if args.limit else questions
    db = Database(DB_PATH)
    agent = SQLAgent(DB_PATH, model=args.model)

    report, strict_ok, answer_ok = [], 0, 0
    for q in questions:
        gold = db.run_sql(q["gold_sql"]).rows
        t0 = time.time()
        res = agent.run(q["question"])
        strict = results_match(gold, res.final_result.rows if res.final_result else None)
        in_answer = answer_contains(gold, res.answer)
        strict_ok += strict
        answer_ok += in_answer
        report.append(
            {
                "id": q["id"],
                "difficulty": q["difficulty"],
                "execution_correct": strict,
                "answer_correct": in_answer,
                "steps": len(res.steps),
                "sql_errors_self_corrected": res.sql_errors,
                "seconds": round(time.time() - t0, 1),
                "tokens": res.input_tokens + res.output_tokens,
                "final_sql": res.final_sql,
                "answer": res.answer,
            }
        )
        print(f"[SQL {'OK  ' if strict else 'FAIL'} | Antwort {'OK  ' if in_answer else 'FAIL'}] "
              f"{q['id']} ({q['difficulty']}) - {q['question']}")

    n = len(questions)
    tokens = sum(r["tokens"] for r in report)
    print(f"\nExecution Accuracy (strikt): {strict_ok}/{n} = {strict_ok / n:.0%}")
    print(f"Answer Accuracy:             {answer_ok}/{n} = {answer_ok / n:.0%}")
    print(f"Tokens gesamt: {tokens}  |  Ø Schritte: {sum(r['steps'] for r in report) / n:.1f}"
          f"  |  Ø Sekunden: {sum(r['seconds'] for r in report) / n:.1f}")

    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{args.label}.json"
    out.write_text(
        json.dumps(
            {"model": agent.model, "execution_accuracy": strict_ok / n,
             "answer_accuracy": answer_ok / n, "total_tokens": tokens, "results": report},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Details gespeichert in {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
