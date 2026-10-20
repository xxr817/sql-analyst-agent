import pandas as pd

from sql_agent.charts import build_chart


def mark_of(chart):
    mark = chart.to_dict()["mark"]
    return mark["type"] if isinstance(mark, dict) else mark


def test_ranking_becomes_sorted_bar_chart():
    df = pd.DataFrame({"name": ["Volkswagen", "BMW", "Skoda"], "SUM(r.units)": [137134, 74265, 57880]})
    spec = build_chart(df).to_dict()  # must not fail on special characters in column names
    assert mark_of(build_chart(df)) == "bar"
    assert spec["encoding"]["y"]["sort"] == "-x"


def test_months_wide_format_becomes_line_chart_with_series():
    df = pd.DataFrame({"month": ["2025-01", "2025-02"], "byd": [10, 12], "tesla": [30, 28]})
    chart = build_chart(df)
    assert mark_of(chart) == "line"
    assert chart.to_dict()["encoding"]["color"]["field"] == "Serie"


def test_months_long_format_uses_text_column_as_series():
    df = pd.DataFrame({"month": ["2025-01", "2025-01"], "brand": ["BYD", "Tesla"], "units": [10, 30]})
    assert mark_of(build_chart(df)) == "line"


def test_no_chart_for_single_value_or_missing_labels():
    assert build_chart(pd.DataFrame({"n": [10]})) is None
    assert build_chart(pd.DataFrame({"a": [1, 2], "b": [3, 4]})) is None
    assert build_chart(pd.DataFrame({"name": ["x", "y"]})) is None
