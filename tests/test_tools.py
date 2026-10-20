from pathlib import Path

import pytest

from sql_agent.tools import Database, GuardrailError, validate_sql

DB = Path(__file__).resolve().parents[1] / "data" / "autos.db"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM brands",
        "select name from brands;",
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
        "SELECT 'DROP TABLE brands' AS harmless_text",  # keyword inside a string is fine
    ],
)
def test_allowed_queries(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE brands",
        "DELETE FROM registrations",
        "UPDATE models SET base_price_eur = 0",
        "SELECT 1; DROP TABLE brands",
        "PRAGMA table_info(brands)",
        "ATTACH DATABASE 'x.db' AS x",
        "",
        "WITH x AS (SELECT 1) DELETE FROM brands",
    ],
)
def test_blocked_queries(sql):
    with pytest.raises(GuardrailError):
        validate_sql(sql)


def test_run_sql_returns_rows():
    db = Database(DB)
    res = db.run_sql("SELECT COUNT(*) AS n FROM brands")
    assert res.columns == ["n"]
    assert res.rows[0][0] == 10


def test_row_limit():
    db = Database(DB)
    res = db.run_sql("SELECT * FROM registrations")
    assert res.truncated and len(res.rows) == 200


def test_database_is_read_only_even_without_guardrail():
    db = Database(DB)
    with db._connect() as con, pytest.raises(Exception):
        con.execute("DELETE FROM brands")


def test_describe_unknown_table():
    with pytest.raises(ValueError):
        Database(DB).describe_table("nope")
