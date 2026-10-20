"""Database tools the agent can call, including read-only guardrails.

The agent never gets a raw database connection. It can only call these three
functions, and every SQL statement passes through `validate_sql` first.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

MAX_ROWS = 200            # rows returned to the model per query
QUERY_TIMEOUT_S = 5.0     # abort long-running queries

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|"
    r"VACUUM|REINDEX|TRUNCATE|GRANT|REVOKE|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)


class GuardrailError(ValueError):
    """Raised when a query violates the read-only policy."""


def _strip_comments_and_strings(sql: str) -> str:
    """Remove comments and string literals so keyword checks are not fooled."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return sql


def validate_sql(sql: str) -> str:
    """Return a cleaned query or raise GuardrailError.

    Policy: exactly one statement, must start with SELECT or WITH,
    no write/DDL/admin keywords.
    """
    if not sql or not sql.strip():
        raise GuardrailError("Leere Abfrage.")
    cleaned = sql.strip().rstrip(";").strip()
    code = _strip_comments_and_strings(cleaned)
    if ";" in code:
        raise GuardrailError("Nur eine einzelne SQL-Anweisung ist erlaubt.")
    first = code.lstrip().split(None, 1)[0].upper() if code.strip() else ""
    if first not in ("SELECT", "WITH"):
        raise GuardrailError("Nur lesende Abfragen (SELECT/WITH) sind erlaubt.")
    match = FORBIDDEN.search(code)
    if match:
        raise GuardrailError(f"Verbotenes Schlüsselwort: {match.group(1).upper()}")
    return cleaned


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool

    def as_text(self) -> str:
        lines = [" | ".join(self.columns)]
        lines += [" | ".join("" if v is None else str(v) for v in r) for r in self.rows]
        if self.truncated:
            lines.append(f"... (gekürzt auf {MAX_ROWS} Zeilen)")
        return "\n".join(lines)


class Database:
    """Read-only access to a SQLite file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Datenbank nicht gefunden: {self.path}")

    def _connect(self) -> sqlite3.Connection:
        # Second safety layer: the file itself is opened read-only.
        con = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        con.execute("PRAGMA query_only = ON")
        return con

    def list_tables(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        return [r[0] for r in rows]

    def describe_table(self, table: str) -> str:
        if table not in self.list_tables():
            raise ValueError(f"Unbekannte Tabelle: {table}")
        with self._connect() as con:
            ddl = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            sample = con.execute(f'SELECT * FROM "{table}" LIMIT 3')
            cols = [d[0] for d in sample.description]
            rows = sample.fetchall()
        preview = QueryResult(cols, rows, False).as_text()
        return f"{ddl}\n\nBeispielzeilen:\n{preview}"

    def run_sql(self, sql: str) -> QueryResult:
        query = validate_sql(sql)
        with self._connect() as con:
            deadline = time.monotonic() + QUERY_TIMEOUT_S
            # Returning non-zero aborts the query -> protects against runaway joins.
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            cur = con.execute(query)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        return QueryResult(cols, rows[:MAX_ROWS], truncated)


# Tool definitions in the format of the Anthropic Messages API.
TOOL_SPECS = [
    {
        "name": "list_tables",
        "description": "Listet alle Tabellen der Datenbank auf.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_table",
        "description": "Zeigt das Schema (Spalten, Typen, Kommentare) und 3 Beispielzeilen einer Tabelle.",
        "input_schema": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "Tabellenname"}},
            "required": ["table"],
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Führt genau eine lesende SQLite-Abfrage (SELECT oder WITH) aus und gibt "
            f"höchstens {MAX_ROWS} Zeilen zurück. Schreibende Befehle werden blockiert."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "SQLite-Abfrage"}},
            "required": ["query"],
        },
    },
]
