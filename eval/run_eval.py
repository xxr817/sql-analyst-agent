"""Evaluate the agent against questions with known correct answers.

For each question the reference ("gold") SQL is executed and compared with the
result of the agent's LAST successful query. Column names and row order are
ignored; numbers are compared with a small tolerance. This is a common
"execution accuracy" metric for Text-to-SQL systems.

Usage:
    python eval/run_eval.py                 # all questions
    python eval/run_eval.py --limit 3       # quick, cheaper check
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from sql_agent import Database, SQLAgent  # noqa: E402

DB_PATH = ROOT / "data" / "autos.db"


def _norm(value):
    if isinstance(value, (int, float)):
        return round(float(value), 1)
    return str(value).strip().lower()


def results_match(gold_rows, agent_rows) -> bool:
    """Each gold row must appear (as a sub-multiset of values) in a distinct agent row."""
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


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    questions = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    questions = questions[: args.limit] if args.limit else questions
    db = Database(DB_PATH)
    agent = SQLAgent(DB_PATH, model=args.model)

    report, correct = [], 0
    for q in questions:
        gold = db.run_sql(q["gold_sql"]).rows
        t0 = time.time()
        res = agent.run(q["question"])
        ok = results_match(gold, res.final_result.rows if res.final_result else None)
        correct += ok
        report.append(
            {
                "id": q["id"],
                "difficulty": q["difficulty"],
                "correct": ok,
                "steps": len(res.steps),
                "sql_errors_self_corrected": res.sql_errors,
                "seconds": round(time.time() - t0, 1),
                "tokens": res.input_tokens + res.output_tokens,
                "final_sql": res.final_sql,
                "answer": res.answer,
            }
        )
        mark = "OK  " if ok else "FAIL"
        print(f"[{mark}] {q['id']} ({q['difficulty']}) - {q['question']}")

    acc = correct / len(questions)
    print(f"\nExecution Accuracy: {correct}/{len(questions)} = {acc:.0%}")
    out = ROOT / "eval" / "results.json"
    out.write_text(
        json.dumps({"model": agent.model, "accuracy": acc, "results": report},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Details gespeichert in {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
