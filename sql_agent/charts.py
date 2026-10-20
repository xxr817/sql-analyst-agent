"""Choose a sensible chart for a query result.

- Rankings (text label + number)  -> horizontal bar chart, sorted by value
- Time periods (YYYY or YYYY-MM)  -> line chart, one line per series
- Anything else (1 row, no numbers, no labels) -> no chart

Column names produced by SQL (e.g. "SUM(r.units)") can contain characters that
Altair/Vega-Lite interpret as field paths, so the data is copied into neutral
column names before plotting.
"""
from __future__ import annotations

import re

import altair as alt
import pandas as pd

BLUE = "#1f5fa8"
PERIOD = re.compile(r"^\d{4}(-\d{2})?$")


def build_chart(df: pd.DataFrame) -> alt.Chart | None:
    numeric = df.select_dtypes("number").columns.tolist()
    labels = [c for c in df.columns if c not in numeric]
    if len(df) < 2 or not numeric or not labels:
        return None

    period_cols = [c for c in labels if df[c].astype(str).str.match(PERIOD).all()]
    if period_cols:
        x = period_cols[0]
        others = [c for c in labels if c != x]
        if others:  # long format, e.g. (month, brand, units)
            long = pd.DataFrame(
                {
                    "Periode": df[x].astype(str).to_numpy(),
                    "Serie": df[others].astype(str).agg(" ".join, axis=1).to_numpy(),
                    "Wert": df[numeric[0]].to_numpy(),
                }
            )
        else:  # wide format, e.g. (month, byd, tesla)
            long = pd.concat(
                [
                    pd.DataFrame(
                        {"Periode": df[x].astype(str).to_numpy(), "Serie": str(c),
                         "Wert": df[c].to_numpy()}
                    )
                    for c in numeric
                ],
                ignore_index=True,
            )
        multi = long["Serie"].nunique() > 1
        return (
            alt.Chart(long)
            .mark_line(point=True)
            .encode(
                x=alt.X("Periode:O", sort="ascending", title=None),
                y=alt.Y("Wert:Q", title=None),
                color=alt.Color("Serie:N", title=None) if multi else alt.value(BLUE),
                tooltip=["Periode:O", "Serie:N", "Wert:Q"],
            )
        )

    data = pd.DataFrame(
        {
            "Kategorie": df[labels].astype(str).agg(" ".join, axis=1).to_numpy(),
            "Wert": df[numeric[0]].to_numpy(),
        }
    )
    return (
        alt.Chart(data)
        .mark_bar(color=BLUE)
        .encode(
            y=alt.Y("Kategorie:N", sort="-x", title=None),
            x=alt.X("Wert:Q", title=str(numeric[0])),
            tooltip=["Kategorie:N", "Wert:Q"],
        )
    )
